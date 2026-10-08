"""The ASGI app behind ``clite serve`` and ``clite dashboard``.

Surface area, deliberately small:

``GET  /api/health``                   liveness; the only route that needs no token
``GET  /api/status``                   version, profile, configured model
``GET  /api/sessions``                 stored sessions
``GET  /api/sessions/{id}/messages``   a stored transcript
``GET  /api/plugin-pages``             dashboard pages plugins ship, with their own-origin URL
``WS   /api/ws``                       JSON-RPC, the same protocol the TUI speaks over stdio
``GET  /``                             the bundled dashboard (static files)

Everything a client can *do* goes through the WebSocket. The REST routes exist for simple
read-only integrations and health checks.

Auth: one session token, required on every ``/api`` route except health. It is compared in
constant time. The static files carry no secrets and are served without it.

Two more locks sit behind the token, both aimed at a web page in the user's browser:

* a server bound to loopback only answers ``/api`` requests addressed to a loopback name, so a
  site whose name was re-pointed at 127.0.0.1 (DNS rebinding) gets nothing;
* a WebSocket from a browser must come from the dashboard's own origin.

``create_plugin_pages_app`` is the other half of that second lock: the pages plugins ship run
on a listener of their own, so their origin is not the dashboard's (see ``clite.plugins.pages``).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import HTTPConnection, Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from clite import __version__
from clite.agent.messages import content_text, is_internal
from clite.core.config import config_get
from clite.plugins.pages import dashboard_pages, find_page, resolve_asset
from clite.rpc.server import RpcServer
from clite.rpc.transport import WebSocketTransport
from clite.server.audit import audit
from clite.server.limits import TokenThrottle, client_address, too_large
from clite.server.tokens import get_token_store
from clite.state.db import get_session_db

logger = logging.getLogger("clite.server")

STATIC_DIR = Path(__file__).resolve().parent / "static"
WS_UNAUTHORIZED = 4401
WS_MESSAGE_TOO_BIG = 1009  # RFC 6455 "message too big"
WS_TOKEN_REVOKED = 4403
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def max_message_bytes() -> int:
    """Cap on one incoming RPC line, from ``server.max_message_bytes``."""
    try:
        return max(0, int(config_get("server.max_message_bytes", 1_000_000) or 0))
    except (TypeError, ValueError):
        return 1_000_000


def allowed_hosts() -> list[str]:
    value = config_get("server.allowed_hosts", []) or []
    return [str(name) for name in value] if isinstance(value, (list, tuple)) else []


def _credential_still_valid(name: str, session_token: str) -> bool:
    """True while the credential that opened a socket is still usable.

    The one-off session token lives exactly as long as this process, so it stays valid. A named
    token is re-checked against the store, which is what makes ``revoke`` take effect on a
    socket that is already open.
    """
    if name == "session" and session_token:
        return True
    record = get_token_store().get(name)
    return record is not None and not record.expired()


def presented_token(connection: HTTPConnection) -> str:
    header = connection.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return connection.headers.get("x-clite-token", "") or connection.query_params.get("token", "")


def _authority(value: str) -> tuple[str, int | None]:
    """``(host, port)`` of a Host header or of an origin. The host is lower-case and an IPv6
    literal loses its brackets; ``("", None)`` when there is nothing usable."""
    try:
        parts = urlsplit(value if "://" in value else f"//{value}")
        return (parts.hostname or "").lower(), parts.port
    except ValueError:
        return "", None


def host_allowed(connection: HTTPConnection, bind_host: str, allowed_hosts: Sequence[str] = ()) -> bool:
    """With the server bound to loopback, only requests addressed to a loopback name count.

    A browser that was told ``evil.example`` now resolves to 127.0.0.1 still sends
    ``Host: evil.example``. Refusing that name is what makes the rebinding useless. A server
    the user deliberately bound to another address answers the names in
    ``server.allowed_hosts`` and the bind address itself, and nothing else.
    """
    host = _authority(connection.headers.get("host", ""))[0]
    if bind_host.strip("[]").lower() in _LOOPBACK_HOSTS:
        return host in _LOOPBACK_HOSTS
    accepted = {name.strip().lower() for name in allowed_hosts if name and name.strip()}
    accepted.add(bind_host.strip("[]").lower())
    accepted.update(_LOOPBACK_HOSTS)  # a health check from the machine itself still works
    return host in accepted


def origin_allowed(connection: HTTPConnection) -> bool:
    """Reject cross-site WebSocket connections from a browser.

    A page on another origin can open a socket to localhost. The token already stops it; this
    is the second lock. Only the dashboard's own origin passes: the same host and port the
    request was addressed to (``localhost`` and ``127.0.0.1`` count as the same host). A page
    served from another port, a ``file://`` page and a sandboxed frame (``Origin: null``) do
    not. Non-browser clients send no Origin header at all.
    """
    origin = connection.headers.get("origin")
    if not origin:
        return True
    origin_host, origin_port = _authority(origin)
    host, port = _authority(connection.headers.get("host", ""))
    if not origin_host or origin_port != port:
        return False
    return origin_host == host or {origin_host, host} <= _LOOPBACK_HOSTS


def create_app(
    token: str,
    *,
    client_factory: Callable[[], Any] | None = None,
    platform: str = "desktop",
    bind_host: str = "127.0.0.1",
    throttle: TokenThrottle | None = None,
) -> Starlette:
    if not token:
        raise ValueError("the server needs a session token")
    limiter = throttle or TokenThrottle(
        max_failures=int(config_get("server.rate_limit.max_failures", 10) or 10),
        window_seconds=float(config_get("server.rate_limit.window_seconds", 60) or 60),
        delay_seconds=float(config_get("server.rate_limit.delay_seconds", 5) or 5),
    )
    hosts = allowed_hosts()

    def credential_name(connection: HTTPConnection) -> str:
        """Which credential this connection presented: "session", a named token, or ""."""
        presented = presented_token(connection)
        if not presented:
            return ""
        if hmac.compare_digest(presented.encode(), token.encode()):
            return "session"  # the one-off token a parent process handed us
        record = get_token_store().verify(presented)
        return record.name if record is not None else ""

    def authorize(connection: HTTPConnection) -> tuple[bool, str, float]:
        """``(allowed, credential name, seconds to wait before answering)``."""
        address = client_address(connection)
        if not host_allowed(connection, bind_host, hosts):
            audit("host_rejected", address=address, host=connection.headers.get("host", ""))
            return False, "", 0.0
        name = credential_name(connection)
        if name:
            limiter.record_success(address)
            return True, name, 0.0
        delay = limiter.record_failure(address)
        audit("token_rejected", address=address, delay=f"{delay:.2f}s")
        return False, "", delay

    def guarded(handler: Callable[[Request], Any]) -> Callable[[Request], Any]:
        async def wrapper(request: Request) -> Response:
            allowed, _name, delay = authorize(request)
            if not allowed:
                if delay:
                    await asyncio.sleep(delay)  # the throttle is a wait, not just a count
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await asyncio.to_thread(handler, request)

        return wrapper

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True, "version": __version__})

    def status(request: Request) -> Response:
        from clite.rpc.methods import system_info

        return JSONResponse(system_info(None, None).model_dump(mode="json"))  # type: ignore[arg-type]

    def sessions(request: Request) -> Response:
        try:
            limit = max(1, min(int(request.query_params.get("limit", "30")), 200))
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        rows = get_session_db().list_sessions(limit=limit)
        keys = ("id", "title", "source", "model", "message_count", "started_at", "last_activity_at")
        return JSONResponse({"sessions": [{key: row.get(key) for key in keys} for row in rows]})

    def plugin_pages(request: Request) -> Response:
        return JSONResponse(
            {
                "plugins": [
                    {"name": page.plugin, "title": page.title, "url": page.url()}
                    for page in dashboard_pages()
                ]
            }
        )

    def session_messages(request: Request) -> Response:
        db = get_session_db()
        row = db.find_session(request.path_params["session_id"])
        if row is None:
            return JSONResponse({"error": "no such session"}, status_code=404)
        messages = [
            {
                "role": m["role"],
                "text": content_text(m.get("content")),
                "tool_name": m.get("name") or "",
                "tool_calls": [call["function"]["name"] for call in m.get("tool_calls") or []],
                "timestamp": m.get("timestamp"),
            }
            for m in db.get_messages(row["id"])
            if not is_internal(m)
        ]
        return JSONResponse({"session_id": row["id"], "title": row.get("title") or "", "messages": messages})

    async def websocket_endpoint(websocket: WebSocket) -> None:
        allowed, name, delay = authorize(websocket)
        if not allowed or not origin_allowed(websocket):
            if delay:
                await asyncio.sleep(delay)
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        await websocket.accept()
        address = client_address(websocket)
        audit("connected", token=name, address=address, platform=platform)

        def record_answer(request_name: str, params: dict[str, Any], answer: dict[str, Any] | None) -> None:
            # An approval is the one decision worth keeping: it is what let a dangerous command
            # run. A clarification is the user's own words and is not recorded here.
            if request_name == "approval.request":
                audit(
                    "approval_answered",
                    token=name,
                    address=address,
                    choice=(answer or {}).get("choice", "none"),
                    command=str(params.get("command", ""))[:200],
                )

        loop = asyncio.get_running_loop()
        server = RpcServer(
            WebSocketTransport(websocket, loop),
            platform=platform,
            client_factory=client_factory,
            on_server_answer=record_answer,
        )
        server.announce()
        limit = max_message_bytes()
        try:
            while True:
                raw = await websocket.receive_text()
                if too_large(raw, limit):
                    audit("message_rejected", token=name, address=address, limit=limit)
                    await websocket.close(code=WS_MESSAGE_TOO_BIG)
                    return
                if not _credential_still_valid(name, token):
                    # Revoked (or expired) while this socket was open: cut it off now.
                    audit("token_revoked", token=name, address=address)
                    await websocket.close(code=WS_TOKEN_REVOKED)
                    return
                server.handle_line(raw)
        except WebSocketDisconnect:
            pass
        finally:
            audit("disconnected", token=name, address=address)
            # Closing interrupts running turns and joins their threads; keep it off the loop.
            await asyncio.to_thread(server.close)

    async def index(request: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    return Starlette(
        routes=[
            Route("/api/health", health),
            Route("/api/status", guarded(status)),
            Route("/api/sessions", guarded(sessions)),
            Route("/api/sessions/{session_id}/messages", guarded(session_messages)),
            Route("/api/plugin-pages", guarded(plugin_pages)),
            WebSocketRoute("/api/ws", websocket_endpoint),
            Route("/", index),
            Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
        ]
    )


def _content_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".woff2": "font/woff2",
    }.get(path.suffix.lower(), "application/octet-stream")


def create_plugin_pages_app(*, bind_host: str = "127.0.0.1") -> Starlette:
    """The listener that serves plugin dashboard pages, on its own origin.

    It answers only ``GET /<plugin>/<file>`` for plugins that are loaded and only for files
    inside the plugin's own directory. No token: the page is the plugin's own file, carries no
    secret of the backend, and is readable on disk by whoever is running the agent anyway. What
    it cannot do is reach the dashboard: it is another origin, so the WebSocket refuses it and
    it never sees the session token.

    Everything unknown is a 404 with the same body, so the listener says nothing about which
    plugins exist or which files a page tried to read.
    """

    async def page(request: Request) -> Response:
        if not host_allowed(request, bind_host):
            return _not_found()
        target = find_page(request.path_params["plugin"])
        if target is None:
            return _not_found()
        asset = resolve_asset(target, request.path_params.get("asset") or "")
        if asset is None:
            return _not_found()
        return FileResponse(asset, media_type=_content_type(asset), headers={"Cache-Control": "no-store"})

    return Starlette(
        routes=[
            Route("/{plugin}/{asset:path}", page),
            Route("/{plugin}", page),
            Route("/{path:path}", lambda request: _not_found()),
        ]
    )


def _not_found() -> Response:
    return JSONResponse({"error": "no such page"}, status_code=404)
