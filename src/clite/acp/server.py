"""The Agent Client Protocol server: an editor (Zed and others) drives the agent over stdio.

The wire is JSON-RPC 2.0 with newline-delimited framing — the same pipe the TUI speaks, see
``clite.rpc.transport`` — and the method names are ACP's. Like the RPC server, this file holds
no conversation logic: a session is a ``ChatSession`` and ``clite.acp.session`` translates
between it and ``session/update`` notifications.

The protocol is an external one and still moving; what this agent implements of it is written
down in ``docs/spesifikasi/acp.md``.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
import uuid
from collections.abc import Callable
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any

from clite import __version__
from clite.rpc.transport import Transport

logger = logging.getLogger("clite.acp")

PROTOCOL_VERSION = 1  # the MAJOR version this agent speaks
AGENT_NAME = "c-lite"
AGENT_TITLE = "C-lite"

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)
SESSION_NOT_FOUND, SESSION_BUSY, REQUEST_FAILED = 4001, 4002, 4003

CLIENT_REQUEST_TIMEOUT_SECONDS = 300.0
SESSION_ID_PREFIX = "sess_"
NO_REPLY = object()  # a notification: nothing goes back, not even an error


class AcpError(Exception):
    """A protocol-level failure: it becomes a JSON-RPC error reply, never a crash."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class Method:
    handler: Callable[[AcpServer, dict[str, Any]], Any]
    inline: bool = False  # run on the reader thread, not the pool (session/cancel)


ACP_METHODS: dict[str, Method] = {}


def acp_method(name: str, *, inline: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        if name in ACP_METHODS:
            raise KeyError(f"ACP method {name!r} already has a handler")
        ACP_METHODS[name] = Method(function, inline)
        return function

    return decorate


def mapping(value: Any, what: str) -> dict[str, Any]:
    """``value`` as a mapping; an absent one is empty. Anything else is the client's bug."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AcpError(INVALID_PARAMS, f"{what} must be an object")
    return value


def required_text(params: dict[str, Any], key: str, what: str = "") -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AcpError(INVALID_PARAMS, f"{what or key} must be a non-empty string")
    return value


class AcpServer:
    """One instance per client connection (the editor spawns one process, so usually one).

    Requests run on a worker pool so that ``session/cancel`` — which the client sends while a
    turn is still running — is read and acted on at once. Notifications never get a reply.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        client_factory: Callable[[], Any] | None = None,
        platform: str = "acp",
    ) -> None:
        self.transport = transport
        self.client_factory = client_factory  # tests inject a scripted model client
        self.platform = platform
        self.sessions: dict[str, Any] = {}  # session id -> AcpSession
        self.client_capabilities: dict[str, Any] = {}
        self.client_info: dict[str, Any] = {}
        self.initialized = False
        self.closed = False
        self._lock = threading.RLock()
        self._next_request = 0
        self._in_flight = 0  # requests submitted but not yet answered
        self._pending: dict[str, concurrent.futures.Future] = {}
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="clite-acp")

    # ── outgoing ─────────────────────────────────────────────────────────────────────────

    def notify(self, method: str, params: dict[str, Any]) -> bool:
        """Send a notification (no id, no reply). False when the peer is gone."""
        return self.transport.write({"jsonrpc": "2.0", "method": method, "params": params})

    def request_client(
        self, method: str, params: dict[str, Any], *, timeout: float = CLIENT_REQUEST_TIMEOUT_SECONDS
    ) -> dict[str, Any] | None:
        """Ask the client something and wait for its reply. ``None`` on timeout or disconnect.

        The caller decides what silence means; for a permission request it means no.
        """
        with self._lock:
            self._next_request += 1
            request_id = f"acp-{self._next_request}"
            future: concurrent.futures.Future = concurrent.futures.Future()
            self._pending[request_id] = future
        if not self.transport.write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}):
            self._pending.pop(request_id, None)
            return None
        try:
            reply = future.result(timeout)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError):
            return None
        finally:
            self._pending.pop(request_id, None)
        return reply if isinstance(reply, dict) else None

    def _respond(self, request_id: Any, result: Any = None, error: AcpError | None = None) -> None:
        if request_id is NO_REPLY:
            return  # a notification: no reply, ever. A request without an id still gets one
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = {"code": error.code, "message": error.message}
            if error.data is not None:
                message["error"]["data"] = error.data
        else:
            message["result"] = {} if result is None else result
        self.transport.write(message)

    # ── incoming ─────────────────────────────────────────────────────────────────────────

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            self._respond(None, error=AcpError(PARSE_ERROR, "invalid JSON"))
            return
        self.handle_message(message)

    def handle_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            self._respond(None, error=AcpError(INVALID_REQUEST, "a message must be a JSON object"))
            return
        request_id = message.get("id", NO_REPLY)
        if "method" not in message:
            self._resolve_pending(request_id, message)
            return
        name = str(message.get("method") or "")
        method = ACP_METHODS.get(name)
        if method is None:
            self._respond(request_id, error=AcpError(METHOD_NOT_FOUND, f"unknown method: {name}"))
            return
        try:
            params = mapping(message.get("params"), f"params of {name}")
        except AcpError as exc:
            self._respond(request_id, error=exc)
            return
        if method.inline:
            self._run_method(name, method, params, request_id)
        else:
            with self._lock:
                self._in_flight += 1
            self._pool.submit(copy_context().run, self._run_method, name, method, params, request_id)

    def _resolve_pending(self, request_id: Any, message: dict[str, Any]) -> None:
        future = self._pending.get(str(request_id))
        if future is not None and not future.done():
            future.set_result(message.get("result") if "error" not in message else None)

    def _run_method(self, name: str, method: Method, params: dict[str, Any], request_id: Any) -> None:
        try:
            result = method.handler(self, params)
        except AcpError as exc:
            self._respond(request_id, error=exc)
        except Exception as exc:  # noqa: BLE001 - one bad request must not end the connection
            logger.exception("ACP method %s failed", name)
            self._respond(request_id, error=AcpError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))
        else:
            self._respond(request_id, result)
        finally:
            with self._lock:
                self._in_flight = max(0, self._in_flight - 1)

    # ── sessions ─────────────────────────────────────────────────────────────────────────

    def new_session(self, **options: Any) -> Any:
        from clite.acp.session import AcpSession

        with self._lock:
            session_id = f"{SESSION_ID_PREFIX}{uuid.uuid4().hex[:12]}"
            session = AcpSession(self, session_id, client_factory=self.client_factory, **options)
            self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Any:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise AcpError(SESSION_NOT_FOUND, f"no session {session_id!r}; call session/new first")
        return session

    def close_session(self, session_id: str) -> None:
        with self._lock:
            session = self.sessions.pop(session_id, None)
        if session is not None:
            session.close()

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Block until no request is in flight and no session runs a turn.

        Shutting down while a reply is still being prepared would drop it, so the last
        messages of a connection are answered before the pool is taken away.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                sessions = list(self.sessions.values())
                in_flight = self._in_flight
            if not in_flight and not any(session.busy for session in sessions):
                return True
            time.sleep(0.01)
        return False

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
                logger.debug("closing an ACP session failed", exc_info=True)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.transport.close()


# ── methods ──────────────────────────────────────────────────────────────────────────────


@acp_method("initialize")
def handle_initialize(server: AcpServer, params: dict[str, Any]) -> dict[str, Any]:
    """Negotiate the protocol version and exchange capabilities.

    A client that speaks a version we do not know gets ours back and has to decide; the
    handshake is not refused, because the two versions may still agree on everything we use.
    """
    version = params.get("protocolVersion")
    if not isinstance(version, int) or isinstance(version, bool):
        raise AcpError(INVALID_PARAMS, "initialize needs an integer protocolVersion")
    if version != PROTOCOL_VERSION:
        logger.warning(
            "ACP client asked for protocol version %s; this agent speaks %s", version, PROTOCOL_VERSION
        )
    server.client_capabilities = mapping(params.get("clientCapabilities"), "clientCapabilities")
    server.client_info = mapping(params.get("clientInfo"), "clientInfo")
    server.initialized = True
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "agentCapabilities": {
            # Loading replays the stored transcript as session/update notifications.
            "loadSession": True,
            # Prompts carry text. Images, audio and embedded resources are not read yet, so
            # they are not announced: a client must not send what was declared unsupported.
            "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False},
        },
        "agentInfo": {"name": AGENT_NAME, "title": AGENT_TITLE, "version": __version__},
        "authMethods": [],
    }


@acp_method("session/new")
def handle_session_new(server: AcpServer, params: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path

    if not server.initialized:
        raise AcpError(INVALID_REQUEST, "initialize first: the session needs the negotiated capabilities")
    cwd = required_text(params, "cwd", "session/new needs an absolute cwd")
    if not Path(cwd).is_absolute():
        raise AcpError(INVALID_PARAMS, f"session/new needs an absolute cwd, got {cwd!r}")
    servers = params.get("mcpServers") or []
    if servers:
        logger.warning(
            "the client offered %d MCP server(s); c-lite takes its MCP servers from its own config, "
            "so these are ignored",
            len(servers) if isinstance(servers, list) else 1,
        )
    session = server.new_session(cwd=cwd)
    return {"sessionId": session.id}
