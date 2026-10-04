"""The JSON-RPC server: one instance per client connection.

It is transport-agnostic (stdio for the TUI, WebSocket for the desktop app and the
dashboard) and holds no conversation logic of its own: each runtime session is a
``ChatSession``, and this file only translates between JSON-RPC and that object.

Message kinds on the wire (JSON-RPC 2.0):

* request      ``{"jsonrpc": "2.0", "id": 1, "method": "session.create", "params": {...}}``
* response     ``{"jsonrpc": "2.0", "id": 1, "result": {...}}`` or ``{"id": 1, "error": {code, message}}``
* event        ``{"jsonrpc": "2.0", "method": "event", "params": {type, session_id, payload, seq}}``
* server request  ``{"jsonrpc": "2.0", "id": "srq-1", "method": "approval.request", "params": {...}}``
                  which the client answers with a response carrying the same id.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from clite import __version__
from clite.core.errors import AuthError, CliteError
from clite.rpc.contracts.base import EVENTS, METHODS, PROTOCOL_VERSION, SERVER_REQUESTS
from clite.rpc.transport import Transport

logger = logging.getLogger("clite.rpc")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
SESSION_NOT_FOUND, SESSION_BUSY, NOT_CONFIGURED, REQUEST_FAILED = 4001, 4002, 4003, 4004
SERVER_REQUEST_TIMEOUT_SECONDS = 300.0


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


Handler = Callable[["RpcServer", BaseModel], Any]
HANDLERS: dict[str, Handler] = {}


def rpc_method(name: str) -> Callable[[Handler], Handler]:
    """Bind a handler to a declared method. The contract must exist first."""

    def decorate(function: Handler) -> Handler:
        if name not in METHODS:
            raise KeyError(f"RPC method {name!r} has no contract in clite.rpc.contracts.schema")
        if name in HANDLERS:
            raise KeyError(f"RPC method {name!r} already has a handler")
        HANDLERS[name] = function
        return function

    return decorate


class RpcServer:
    def __init__(self, transport: Transport, *, platform: str = "tui", client_factory: Callable[[], Any] | None = None) -> None:
        from clite.rpc import methods  # noqa: F401 - registers the handlers

        self.transport = transport
        self.platform = platform
        self.client_factory = client_factory  # tests inject a scripted model client
        self.sessions: dict[str, Any] = {}  # runtime session id -> RpcSession
        self._lock = threading.RLock()
        self._seq = 0
        self._next_request = 0
        self._pending: dict[str, concurrent.futures.Future] = {}
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="clite-rpc")
        self.closed = False

    # ── outgoing ─────────────────────────────────────────────────────────────────────────

    def emit(self, event_type: str, session_id: str, payload: dict[str, Any] | BaseModel) -> None:
        """Send an event. Payloads are validated against the contract so a drift between the
        server and the declared protocol fails here, in a test, not in a client."""
        model = EVENTS[event_type]
        body = payload if isinstance(payload, BaseModel) else model.model_validate(payload)
        with self._lock:
            self._seq += 1
            seq = self._seq
        self.transport.write({
            "jsonrpc": "2.0", "method": "event",
            "params": {"type": event_type, "session_id": session_id, "payload": body.model_dump(mode="json"), "seq": seq},
        })

    def request_client(self, name: str, params: dict[str, Any], *, timeout: float = SERVER_REQUEST_TIMEOUT_SECONDS) -> dict[str, Any] | None:
        """Ask the client something and wait for the reply. ``None`` on timeout or disconnect."""
        spec = SERVER_REQUESTS[name]
        body = spec.params.model_validate(params).model_dump(mode="json")
        with self._lock:
            self._next_request += 1
            request_id = f"srq-{self._next_request}"
            future: concurrent.futures.Future = concurrent.futures.Future()
            self._pending[request_id] = future
        if not self.transport.write({"jsonrpc": "2.0", "id": request_id, "method": name, "params": body}):
            self._pending.pop(request_id, None)
            return None
        try:
            reply = future.result(timeout)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError):
            return None
        finally:
            self._pending.pop(request_id, None)
        try:
            return spec.result.model_validate(reply).model_dump(mode="json")
        except ValidationError:
            logger.warning("client sent an invalid reply to %s: %r", name, reply)
            return None

    def _respond(self, request_id: Any, result: Any = None, error: RpcError | None = None) -> None:
        if request_id is None:
            return  # a notification: no response
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = {"code": error.code, "message": error.message}
            if error.data is not None:
                message["error"]["data"] = error.data
        else:
            message["result"] = result
        self.transport.write(message)

    # ── incoming ─────────────────────────────────────────────────────────────────────────

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            self._respond("", error=RpcError(PARSE_ERROR, "invalid JSON"))
            return
        self.handle_message(message)

    def handle_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            self._respond("", error=RpcError(INVALID_REQUEST, "a request must be a JSON object"))
            return
        request_id = message.get("id")
        if "method" not in message:
            # A reply to one of our server requests.
            future = self._pending.get(str(request_id))
            if future is not None and not future.done():
                future.set_result(message.get("result") if "error" not in message else None)
            return
        name = message.get("method")
        spec, handler = METHODS.get(name), HANDLERS.get(name)
        if spec is None or handler is None:
            self._respond(request_id, error=RpcError(METHOD_NOT_FOUND, f"unknown method: {name}"))
            return
        try:
            params = spec.params.model_validate(message.get("params") or {})
        except ValidationError as exc:
            details = [{"field": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]} for error in exc.errors()]
            self._respond(request_id, error=RpcError(INVALID_PARAMS, f"invalid params for {name}", details))
            return
        # Handlers run off the reader thread: a slow one (a model list, a compression) must
        # not block the reply to a server request that the same client is about to send.
        self._pool.submit(self._run_handler, name, handler, spec, params, request_id)

    def _run_handler(self, name: str, handler: Handler, spec: Any, params: BaseModel, request_id: Any) -> None:
        try:
            result = handler(self, params)
            if isinstance(result, BaseModel):
                body = result.model_dump(mode="json")
            else:
                body = spec.result.model_validate(result if result is not None else {}).model_dump(mode="json")
            self._respond(request_id, body)
        except RpcError as exc:
            self._respond(request_id, error=exc)
        except AuthError as exc:
            self._respond(request_id, error=RpcError(NOT_CONFIGURED, str(exc), {"code": exc.code, "provider": exc.provider}))
        except CliteError as exc:
            self._respond(request_id, error=RpcError(REQUEST_FAILED, str(exc)))
        except Exception as exc:  # noqa: BLE001 - one bad request must not end the connection
            logger.exception("RPC handler %s failed", name)
            self._respond(request_id, error=RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))

    # ── sessions ─────────────────────────────────────────────────────────────────────────

    def get_session(self, session_id: str) -> Any:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise RpcError(SESSION_NOT_FOUND, f"no session {session_id!r}; call session.create first")
        return session

    def add_session(self, session: Any) -> str:
        session_id = uuid.uuid4().hex[:12]
        with self._lock:
            self.sessions[session_id] = session
        return session_id

    def remove_session(self, session_id: str) -> None:
        with self._lock:
            session = self.sessions.pop(session_id, None)
        if session is not None:
            session.close()

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def announce(self) -> None:
        self.emit("gateway.ready", "", {"version": __version__, "protocol_version": PROTOCOL_VERSION})

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            sessions = list(self.sessions.values())
            self.sessions.clear()
            pending = list(self._pending.values())
        for future in pending:
            future.cancel()  # unblock anything waiting on the client
        for session in sessions:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                logger.debug("closing an RPC session failed", exc_info=True)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.transport.close()

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Block until no session is running a turn (used by tests and clean shutdown)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                sessions = list(self.sessions.values())
            if not any(session.busy for session in sessions):
                return True
            time.sleep(0.01)
        return False


def reset_server_state() -> None:
    """Nothing process-global lives here; kept as the test suite's reset hook."""
