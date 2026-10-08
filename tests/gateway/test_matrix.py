"""Matrix platform plugin tests against a local Client-Server API fake."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

from clite.gateway.platforms.base import PLATFORMS
from clite.plugins.manager import ensure_plugins_loaded


class _MatrixHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, dict[str, Any] | None]] = []
    sync_calls = 0

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _json(self, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self.__class__.sync_calls += 1
        self.__class__.requests.append(("GET", self.path, None))
        if self.path.startswith("/_matrix/client/v3/sync"):
            events = (
                [
                    {
                        "type": "m.room.message",
                        "event_id": "$question",
                        "sender": "@allowed:example.test",
                        "content": {"msgtype": "m.text", "body": "Please reply."},
                    }
                ]
                if self.__class__.sync_calls == 1
                else []
            )
            self._json(
                {
                    "next_batch": "next-token",
                    "rooms": {"join": {"!room:example.test": {"timeline": {"events": events}}}},
                }
            )
            return
        self.send_error(404)

    def do_PUT(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append(("PUT", self.path, body))
        self._json({"event_id": "$answer"})


def _wait_for(predicate, timeout: float = 3) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        threading.Event().wait(0.01)
    return False


def test_matrix_plugin_long_polls_local_sync_and_sends_a_room_message(monkeypatch):
    _MatrixHandler.requests = []
    _MatrixHandler.sync_calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MatrixHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "matrix-secret")

    class Runner:
        def __init__(self) -> None:
            self.events: list[Any] = []

        def dispatch(self, event) -> None:
            self.events.append(event)
            adapter.send(event.source.chat_id, "The answer", reply_to=event.message_id)

    try:
        ensure_plugins_loaded()
        runner = Runner()
        adapter = PLATFORMS["matrix"](
            {
                "base_url": f"http://127.0.0.1:{server.server_address[1]}",
                "allowed_users": ["@allowed:example.test"],
                "poll_timeout": 10,
            },
            runner,
        )
        adapter.connect()
        assert _wait_for(lambda: any(method == "PUT" for method, _path, _body in _MatrixHandler.requests))
        assert len(runner.events) == 1
        event = runner.events[0]
        assert event.text == "Please reply."
        assert event.message_id == "$question"
        assert event.source.chat_id == "!room:example.test"
        assert event.source.user_id == "@allowed:example.test"
        sent = next((entry for entry in _MatrixHandler.requests if entry[0] == "PUT"), None)
        assert sent is not None
        method, path, body = sent
        assert method == "PUT"
        assert unquote(urlparse(path).path).startswith("/_matrix/client/v3/rooms/!room:example.test/send/m.room.message/")
        assert body == {"msgtype": "m.text", "body": "The answer", "m.relates_to": {"m.in_reply_to": {"event_id": "$question"}}}
    finally:
        if "adapter" in locals():
            adapter.disconnect()
        server.shutdown()
        server.server_close()
