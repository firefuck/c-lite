"""Signal platform plugin tests against a local signal-cli REST protocol fake."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

from clite.gateway.platforms.base import PLATFORMS
from clite.plugins.manager import ensure_plugins_loaded


class _SignalHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, dict[str, Any] | None]] = []
    receive_calls = 0

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _json(self, body: Any) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self.__class__.receive_calls += 1
        self.__class__.requests.append(("GET", self.path, None))
        if self.path.startswith("/v1/receive/"):
            messages = (
                [
                    {
                        "envelope": {
                            "source": "+15550001111",
                            "sourceName": "Allowed sender",
                            "timestamp": 1_700_000_000_000,
                            "dataMessage": {"message": "Please reply."},
                        }
                    }
                ]
                if self.__class__.receive_calls == 1
                else []
            )
            self._json(messages)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append(("POST", self.path, body))
        self._json({"timestamp": 1_700_000_000_001})


def _wait_for(predicate, timeout: float = 3) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        threading.Event().wait(0.01)
    return False


def test_signal_plugin_polls_local_signal_cli_rest_and_sends_a_reply():
    _SignalHandler.requests = []
    _SignalHandler.receive_calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SignalHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    class Runner:
        def __init__(self) -> None:
            self.events: list[Any] = []

        def dispatch(self, event) -> None:
            self.events.append(event)
            adapter.send(event.source.chat_id, "The answer", reply_to=event.message_id)

    try:
        ensure_plugins_loaded()
        runner = Runner()
        adapter = PLATFORMS["signal"](
            {
                "base_url": f"http://127.0.0.1:{server.server_address[1]}",
                "account": "+15550002222",
                "allowed_users": ["+15550001111"],
                "poll_interval": 0.01,
            },
            runner,
        )
        adapter.connect()
        assert _wait_for(lambda: any(method == "POST" for method, _path, _body in _SignalHandler.requests))
        assert len(runner.events) == 1
        event = runner.events[0]
        assert event.text == "Please reply."
        assert event.message_id == "1700000000000"
        assert event.source.chat_id == "+15550001111"
        assert event.source.user_id == "+15550001111"
        assert event.source.user_name == "Allowed sender"
        sent = next((entry for entry in _SignalHandler.requests if entry[0] == "POST"), None)
        assert sent is not None
        method, path, body = sent
        assert method == "POST"
        assert unquote(urlparse(path).path) == "/v2/send"
        assert body == {"message": "The answer", "number": "+15550002222", "recipients": ["+15550001111"]}
    finally:
        if "adapter" in locals():
            adapter.disconnect()
        server.shutdown()
        server.server_close()
