"""web_fetch: text extraction, paging and the private-address guard."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clite.tools.builtin.web import html_to_text, private_address_reason, web_fetch_tool
from clite.tools.context import ToolContext

PAGE = """<html><head><title>Docs &amp; Guides</title><style>body{color:red}</style></head>
<body><script>alert(1)</script><h1>Install</h1><p>Run <code>pip install x</code>.</p>
<p>See <a href="https://example.com/more">more</a>.</p></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        routes = {
            "/page": (200, "text/html; charset=utf-8", PAGE.encode()),
            "/data.json": (200, "application/json", b'{"ok": true}'),
            "/image": (200, "image/png", b"\x89PNG"),
            "/long": (200, "text/plain", ("abcdefghij" * 300).encode()),
        }
        status, content_type, body = routes.get(self.path, (404, "text/plain", b"missing"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(clite_home):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    (clite_home / "config.yaml").write_text("web:\n  allow_private_urls: true\n")
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _fetch(url, **args):
    return json.loads(web_fetch_tool({"url": url, **args}, ToolContext()))


def test_html_becomes_readable_text():
    title, text = html_to_text(PAGE)
    assert title == "Docs & Guides"
    assert text == "Install\n\nRun pip install x.\n\nSee more (https://example.com/more)."


def test_fetch_html_page(server):
    result = _fetch(f"{server}/page")
    assert result["title"] == "Docs & Guides"
    assert "alert(1)" not in result["content"] and "Install" in result["content"]


def test_fetch_json_is_returned_verbatim(server):
    assert _fetch(f"{server}/data.json")["content"] == '{"ok": true}'


def test_long_pages_are_paged(server):
    first = _fetch(f"{server}/long", max_chars=1000)
    assert first["truncated"] is True and first["total_chars"] == 3000
    rest = _fetch(f"{server}/long", max_chars=5000, offset=first["next_offset"])
    assert len(first["content"]) + len(rest["content"]) == 3000


def test_http_errors_and_binary_content_are_reported(server):
    assert _fetch(f"{server}/nope")["error"].startswith("HTTP 404")
    assert "unsupported content type" in _fetch(f"{server}/image")["error"]


def test_only_http_schemes_are_accepted():
    assert "http" in _fetch("file:///etc/passwd")["error"]


def test_private_addresses_are_refused_by_default():
    assert "non-public" in _fetch("http://127.0.0.1:9/")["error"]
    assert private_address_reason("http://169.254.169.254/latest/meta-data") is not None
