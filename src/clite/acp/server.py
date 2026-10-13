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
from collections.abc import Callable
from contextvars import copy_context
from dataclasses import dataclass
from pathlib import Path
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


def prompt_text(blocks: Any) -> str:
    """The text of an ACP prompt: a list of content blocks.

    Only text blocks arrive: the handshake announced that images, audio and embedded context
    are not supported, so a client that sends one anyway is told what it did wrong instead of
    having it silently dropped.
    """
    if not isinstance(blocks, list) or not blocks:
        raise AcpError(INVALID_PARAMS, "a prompt is a non-empty array of content blocks")
    texts: list[str] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise AcpError(INVALID_PARAMS, f"prompt[{index}] must be an object")
        kind = block.get("type")
        if kind != "text":
            raise AcpError(
                INVALID_PARAMS,
                f"prompt[{index}] is a {kind!r} block; this agent takes text prompts only",
            )
        text = block.get("text")
        if not isinstance(text, str):
            raise AcpError(INVALID_PARAMS, f"prompt[{index}] needs a text string")
        texts.append(text)
    return "\n".join(texts)


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
        # What to run once a request's reply has gone out (see ``after_reply``), kept per
        # thread: two requests answer on two workers and their replies are not ours to reorder.
        self._after_reply = threading.local()
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

    def after_reply(self, action: Callable[[], None]) -> None:
        """Run ``action`` once this request's reply has been written.

        ``session/new`` hands back an id the client has not been told yet, and an editor that
        keeps state per session would drop an update naming a session it has never heard of.
        Queuing the work until the reply is out keeps the two in order without the handler
        having to know when that is.
        """
        pending = getattr(self._after_reply, "value", None)
        if pending is None:
            pending = self._after_reply.value = []
        pending.append(action)

    def _drain_after_reply(self) -> None:
        pending = getattr(self._after_reply, "value", None)
        self._after_reply.value = []
        for action in pending or []:
            try:
                action()
            except Exception:  # a late announcement must not fail the request
                logger.debug("an after-reply action failed", exc_info=True)

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
        except Exception as exc:  # one bad request must not end the connection
            logger.exception("ACP method %s failed", name)
            self._respond(request_id, error=AcpError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))
        else:
            self._respond(request_id, result)
        finally:
            # After the reply, and before this request stops counting as in flight: the
            # announcement belongs to a connection that is still there to receive it.
            self._drain_after_reply()
            with self._lock:
                self._in_flight = max(0, self._in_flight - 1)

    # ── sessions ─────────────────────────────────────────────────────────────────────────

    def new_session(self, **options: Any) -> Any:
        from clite.acp.session import AcpSession

        session = AcpSession(self, client_factory=self.client_factory, **options)
        with self._lock:
            self.sessions[session.id] = session
        return session

    def load_session(self, reference: str, **options: Any) -> Any:
        """Reopen a stored conversation as a live session.

        The id is the store's own — see ``AcpSession`` — which is what makes it outlive the
        process that handed it out. A session that is already open here is refused rather than
        opened twice: two live agents on one stored conversation would write over each other.
        """
        from clite.acp.session import AcpSession

        session = AcpSession(self, resume=reference, client_factory=self.client_factory, **options)
        with self._lock:
            if session.id in self.sessions:
                raise AcpError(INVALID_REQUEST, f"session {session.id!r} is already open")
            self.sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Any:
        session = self.find_session(session_id)
        if session is None:
            raise AcpError(SESSION_NOT_FOUND, f"no session {session_id!r}; call session/new first")
        return session

    def find_session(self, session_id: str) -> Any | None:
        """The session with that id, or ``None``. Callers that can do without one use this."""
        with self._lock:
            return self.sessions.get(session_id)

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
            except Exception:
                logger.debug("closing an ACP session failed", exc_info=True)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.transport.close()


# ── methods ──────────────────────────────────────────────────────────────────────────────


def session_cwd(params: dict[str, Any], method: str) -> str:
    """The absolute working directory a session carries.

    Both ``session/new`` and ``session/load`` take one, and a relative path would build an
    agent somewhere the client did not mean.
    """
    cwd = required_text(params, "cwd", f"{method} needs an absolute cwd")
    if not Path(cwd).is_absolute():
        raise AcpError(INVALID_PARAMS, f"{method} needs an absolute cwd, got {cwd!r}")
    return cwd


def note_mcp_servers(params: dict[str, Any]) -> None:
    """Record the MCP servers a client offered, since c-lite will not use them.

    The list is accepted without an error — refusing would fail a session over something the
    client cannot help — but it is logged, because silently dropping a server a user configured
    is the kind of thing that is impossible to debug later.
    """
    servers = params.get("mcpServers") or []
    if servers:
        logger.warning(
            "the client offered %d MCP server(s); c-lite takes its MCP servers from its own config, "
            "so these are ignored",
            len(servers) if isinstance(servers, list) else 1,
        )


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
    if not server.initialized:
        raise AcpError(INVALID_REQUEST, "initialize first: the session needs the negotiated capabilities")
    cwd = session_cwd(params, "session/new")
    note_mcp_servers(params)
    session = server.new_session(cwd=cwd)
    # The id means nothing to the client until this reply arrives, so the list of commands it
    # may type follows the reply rather than racing it.
    server.after_reply(session.announce_commands)
    return {"sessionId": session.id}


@acp_method("session/load")
def handle_session_load(server: AcpServer, params: dict[str, Any]) -> dict[str, Any]:
    """Reopen a stored conversation: its history is replayed, then the result is empty.

    The replay comes first because the protocol asks for it that way: the client is rebuilding
    the transcript on its side, and this reply is the end of that replay, not a separate step.
    """
    if not server.initialized:
        raise AcpError(INVALID_REQUEST, "initialize first: the session needs the negotiated capabilities")
    session_id = required_text(params, "sessionId", "session/load needs a sessionId")
    cwd = session_cwd(params, "session/load")
    note_mcp_servers(params)
    session = server.load_session(session_id, cwd=cwd)
    session.replay()
    server.after_reply(session.announce_commands)
    return {}


@acp_method("session/prompt")
def handle_session_prompt(server: AcpServer, params: dict[str, Any]) -> dict[str, Any]:
    """Run one turn and answer with its ``stopReason``.

    The text streams ahead as ``session/update`` notifications; this reply is the end of the
    turn. It runs on a worker, so ``session/cancel`` is read while the turn is still going.
    """
    session = server.get_session(required_text(params, "sessionId", "session/prompt needs a sessionId"))
    return {"stopReason": session.prompt(prompt_text(params.get("prompt")))}


@acp_method("session/cancel", inline=True)
def handle_session_cancel(server: AcpServer, params: dict[str, Any]) -> dict[str, Any]:
    """Stop the running turn. A notification, so the answer is the prompt's ``cancelled``.

    Cancelling a session that is gone — or that was never running anything — is not an error:
    the client may have raced ahead of its own prompt.
    """
    session_id = params.get("sessionId")
    session = server.find_session(session_id) if isinstance(session_id, str) else None
    if session is None:
        logger.debug("session/cancel for unknown session %r", session_id)
    else:
        session.cancel()
    return {}
