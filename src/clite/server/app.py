"""The ASGI app behind ``clite serve`` and ``clite dashboard``.

Surface area, deliberately small:

``GET  /api/health``                   liveness; the only route that needs no token
``GET  /api/status``                   version, profile, configured model
``GET  /api/sessions``                 stored sessions
``GET  /api/sessions/{id}/messages``   a stored transcript
``WS   /api/ws``                       JSON-RPC, the same protocol the TUI speaks over stdio
``GET  /``                             the bundled dashboard (static files)

Everything a client can *do* goes through the WebSocket. The REST routes exist for simple
read-only integrations and health checks.

Auth: one session token, required on every ``/api`` route except health. It is compared in
constant time. The static files carry no secrets and are served without it.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import HTTPConnection, Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from clite import __version__
from clite.agent.messages import content_text, is_internal
from clite.rpc.server import RpcServer
from clite.rpc.transport import WebSocketTransport
from clite.state.db import get_session_db

logger = logging.getLogger("clite.server")

STATIC_DIR = Path(__file__).resolve().parent / "static"
WS_UNAUTHORIZED = 4401
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


def presented_token(connection: HTTPConnection) -> str:
    header = connection.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return connection.headers.get("x-clite-token", "") or connection.query_params.get("token", "")


def origin_allowed(connection: HTTPConnection) -> bool:
    """Reject cross-site WebSocket connections from a browser.

    A page on another origin can open a socket to localhost. The token already stops it; this
    is the second lock, and it costs nothing. Non-browser clients send no Origin header.
    """
    origin = connection.headers.get("origin")
    if not origin or origin == "null" or origin.startswith(("file://", "app://")):
        return True
    host = origin.split("://", 1)[-1].split("/", 1)[0]
    return host == connection.headers.get("host", "") or host.rsplit(":", 1)[0] in _LOOPBACK_HOSTS


def create_app(token: str, *, client_factory: Callable[[], Any] | None = None, platform: str = "desktop") -> Starlette:
    if not token:
        raise ValueError("the server needs a session token")

    def authorized(connection: HTTPConnection) -> bool:
        return hmac.compare_digest(presented_token(connection).encode(), token.encode())

    def guarded(handler: Callable[[Request], Any]) -> Callable[[Request], Any]:
        async def wrapper(request: Request) -> Response:
            if not authorized(request):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await asyncio.get_running_loop().run_in_executor(None, handler, request)

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

    def session_messages(request: Request) -> Response:
        db = get_session_db()
        row = db.find_session(request.path_params["session_id"])
        if row is None:
            return JSONResponse({"error": "no such session"}, status_code=404)
        messages = [
            {"role": m["role"], "text": content_text(m.get("content")), "tool_name": m.get("name") or "",
             "tool_calls": [call["function"]["name"] for call in m.get("tool_calls") or []], "timestamp": m.get("timestamp")}
            for m in db.get_messages(row["id"]) if not is_internal(m)
        ]
        return JSONResponse({"session_id": row["id"], "title": row.get("title") or "", "messages": messages})

    async def websocket_endpoint(websocket: WebSocket) -> None:
        if not authorized(websocket) or not origin_allowed(websocket):
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        await websocket.accept()
        loop = asyncio.get_running_loop()
        server = RpcServer(WebSocketTransport(websocket, loop), platform=platform, client_factory=client_factory)
        server.announce()
        try:
            while True:
                server.handle_line(await websocket.receive_text())
        except WebSocketDisconnect:
            pass
        finally:
            # Closing interrupts running turns and joins their threads; keep it off the loop.
            await loop.run_in_executor(None, server.close)

    async def index(request: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    return Starlette(routes=[
        Route("/api/health", health),
        Route("/api/status", guarded(status)),
        Route("/api/sessions", guarded(sessions)),
        Route("/api/sessions/{session_id}/messages", guarded(session_messages)),
        WebSocketRoute("/api/ws", websocket_endpoint),
        Route("/", index),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ])
