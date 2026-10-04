"""A real HTTP server that plays the part of a model provider.

Provider tests go through the actual HTTP client, SSE parser and transports; only the remote
end is fake. Each test registers the responses it wants with ``fake_api.on(...)``.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def sse(*events, done: bool = False) -> bytes:
    """Encode events as an SSE body. An event is a dict (data only) or ``(name, dict)``."""
    out = []
    for event in events:
        if isinstance(event, tuple):
            out.append(f"event: {event[0]}\ndata: {json.dumps(event[1])}\n\n")
        else:
            out.append(f"data: {json.dumps(event)}\n\n")
    if done:
        out.append("data: [DONE]\n\n")
    return "".join(out).encode()


class FakeAPI:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list] = {}
        self.requests: list[dict] = []
        self.httpd: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def on(self, method: str, path: str, *responses) -> None:
        """Queue responses for ``method path``. The last one repeats.

        A response is ``(status, body)`` or ``(status, body, headers)``; ``body`` may be a
        dict (sent as JSON), bytes (sent as an SSE stream), or a callable
        ``(handler) -> None`` that writes the response itself.
        """
        self.routes[(method, path)] = list(responses)

    # Helpers exposed on the fixture so tests need no import from this file.
    sse = staticmethod(sse)

    @staticmethod
    def slow_stream(chunks: list[bytes], delay: float):
        return slow_stream(chunks, delay)

    def bodies(self, path: str | None = None) -> list[dict]:
        return [r["body"] for r in self.requests if path is None or r["path"] == path]

    def _next(self, method: str, path: str):
        queue = self.routes.get((method, path))
        if not queue:
            return (404, {"error": {"message": f"no route for {method} {path}"}})
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
def fake_api():
    api = FakeAPI()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            api.requests.append({
                "method": method, "path": self.path, "headers": dict(self.headers),
                "body": json.loads(raw) if raw else None,
            })
            response = api._next(method, self.path)
            status, body = response[0], response[1]
            headers = response[2] if len(response) > 2 else {}
            if callable(body):
                body(self)
                return
            if isinstance(body, bytes):
                payload, content_type = body, "text/event-stream"
            else:
                payload, content_type = json.dumps(body).encode(), "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):  # noqa: N802
            self._handle("POST")

        def do_GET(self):  # noqa: N802
            self._handle("GET")

        def log_message(self, *args):
            pass

    api.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    api.httpd.daemon_threads = True
    threading.Thread(target=api.httpd.serve_forever, daemon=True).start()
    yield api
    api.httpd.shutdown()
    api.httpd.server_close()


def slow_stream(chunks: list[bytes], delay: float):
    """A response callable that sends ``chunks`` with ``delay`` seconds between them."""

    def write(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Connection", "close")
        handler.end_headers()
        try:
            for chunk in chunks:
                handler.wfile.write(chunk)
                handler.wfile.flush()
                time.sleep(delay)
        except OSError:
            pass  # the client hung up: exactly what a cancel looks like from here
        handler.close_connection = True

    return write
