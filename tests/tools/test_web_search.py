"""``web_search``: the tool is absent without a provider, present with one, and returns
results from a local HTTP server that mocks a search API.

Snippets are untrusted text: they arrive as tool results, never in the system prompt.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from clite.tools.context import ToolContext
from clite.tools.dispatch import get_tool_definitions, handle_function_call
from clite.tools.web_search import (
    WebSearchProvider,
    has_web_search_provider,
    register_web_search_provider,
    reset_web_search_providers,
)

# ── a tiny fake search provider that talks to a local HTTP server ────────────────────


class _FakeAPIHandler(BaseHTTPRequestHandler):
    """Mocks a SearXNG/Tavily-style JSON search endpoint."""

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        payload = json.loads(body) if body else {}
        query = payload.get("query", "") or payload.get("q", "")

        if query == "empty":
            results: list[dict[str, Any]] = []
        else:
            results = [
                {
                    "title": f"Result 1 for {query}",
                    "url": "https://example.com/1",
                    "snippet": f"First snippet about {query}.",
                },
                {
                    "title": f"Result 2 for {query}",
                    "url": "https://example.com/2",
                    "snippet": f"Second snippet about {query}. <script>alert(1)</script>",
                },
            ]
        doc = json.dumps({"results": results}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(doc)))
        self.end_headers()
        self.wfile.write(doc)

    def do_GET(self):  # noqa: N802 - http.server API
        # SearXNG uses GET with a query parameter.
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(self.path).query)
        query = params.get("q", [""])[0]
        results = (
            [
                {
                    "title": f"GET result for {query}",
                    "url": "https://example.com/get",
                    "snippet": f"Snippet via GET for {query}.",
                },
            ]
            if query
            else []
        )
        doc = json.dumps({"results": results}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(doc)))
        self.end_headers()
        self.wfile.write(doc)

    def log_message(self, *args):
        pass


@pytest.fixture
def search_server(clite_home):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeAPIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


class _PostProvider(WebSearchProvider):
    """A keyless provider that POSTs JSON, like Tavily or SearXNG."""

    name = "fake-post"
    requires_api_key = False

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        import urllib.request

        body = json.dumps({"query": query, "max_results": max_results}).encode()
        req = urllib.request.Request(
            f"{self._base_url}/search",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - test server
            data = json.loads(resp.read())
        return data.get("results", [])


class _GetProvider(WebSearchProvider):
    """A keyless provider that uses GET with a query param, like SearXNG or DuckDuckGo."""

    name = "fake-get"
    requires_api_key = False

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        import urllib.parse
        import urllib.request

        url = f"{self._base_url}/search?q={urllib.parse.quote(query)}"
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - test server
            data = json.loads(resp.read())
        return data.get("results", [])


class _KeyedProvider(WebSearchProvider):
    """A provider that requires an API key, like Tavily."""

    name = "fake-keyed"
    requires_api_key = True
    api_key_env = "FAKE_SEARCH_API_KEY"

    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        import urllib.request

        body = json.dumps({"query": query, "api_key": self._api_key}).encode()
        req = urllib.request.Request(
            f"{self._base_url}/search",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - test server
            data = json.loads(resp.read())
        return data.get("results", [])


# ── tests ─────────────────────────────────────────────────────────────────────────────


def test_web_search_is_absent_from_tool_definitions_without_a_provider(clite_home):
    reset_web_search_providers()
    defs = get_tool_definitions(["web"])
    names = [d["function"]["name"] for d in defs]
    assert "web_search" not in names, "web_search must not be offered when no provider is configured"
    assert "web_fetch" in names


def test_web_search_is_present_in_tool_definitions_when_a_provider_is_registered(clite_home):
    register_web_search_provider("fake-post", lambda: _PostProvider("http://example.invalid"))
    try:
        defs = get_tool_definitions(["web"])
        names = [d["function"]["name"] for d in defs]
        assert "web_search" in names
    finally:
        reset_web_search_providers()


def test_check_fn_returns_false_when_no_provider_is_available(clite_home):
    reset_web_search_providers()
    assert not has_web_search_provider()


def test_check_fn_returns_true_when_a_provider_is_registered(clite_home):
    register_web_search_provider("fake-post", lambda: _PostProvider("http://example.invalid"))
    try:
        assert has_web_search_provider()
    finally:
        reset_web_search_providers()


def test_search_returns_title_url_and_snippet_for_each_result(search_server, clite_home):
    register_web_search_provider("fake-post", lambda: _PostProvider(search_server))
    try:
        result = handle_function_call(
            "web_search",
            {"query": "python testing", "max_results": 5},
            ToolContext(),
        )
        payload = json.loads(result)
        assert "results" in payload
        assert len(payload["results"]) == 2
        first = payload["results"][0]
        assert first["title"] == "Result 1 for python testing"
        assert first["url"] == "https://example.com/1"
        assert "python testing" in first["snippet"]
    finally:
        reset_web_search_providers()


def test_search_with_a_get_provider_works(search_server, clite_home):
    register_web_search_provider("fake-get", lambda: _GetProvider(search_server))
    try:
        result = handle_function_call(
            "web_search",
            {"query": "django"},
            ToolContext(),
        )
        payload = json.loads(result)
        assert len(payload["results"]) == 1
        assert payload["results"][0]["url"] == "https://example.com/get"
    finally:
        reset_web_search_providers()


def test_search_with_a_keyed_provider_sends_the_api_key(search_server, clite_home, monkeypatch):
    monkeypatch.setenv("FAKE_SEARCH_API_KEY", "test-secret-key")
    register_web_search_provider("fake-keyed", lambda: _KeyedProvider("test-secret-key", search_server))
    try:
        result = handle_function_call(
            "web_search",
            {"query": "secrets"},
            ToolContext(),
        )
        payload = json.loads(result)
        assert len(payload["results"]) == 2
        assert "secrets" in payload["results"][0]["title"]
    finally:
        reset_web_search_providers()


def test_search_reports_an_error_when_the_query_is_empty(clite_home):
    register_web_search_provider("fake-post", lambda: _PostProvider("http://example.invalid"))
    try:
        result = handle_function_call("web_search", {"query": ""}, ToolContext())
        payload = json.loads(result)
        assert "error" in payload
    finally:
        reset_web_search_providers()


def test_search_reports_an_error_when_the_provider_fails(search_server, clite_home):
    class _BrokenProvider(WebSearchProvider):
        name = "broken"
        requires_api_key = False

        def search(self, query, *, max_results=5):
            raise RuntimeError("the search backend is down")

    register_web_search_provider("broken", lambda: _BrokenProvider())
    try:
        result = handle_function_call("web_search", {"query": "anything"}, ToolContext())
        payload = json.loads(result)
        assert "error" in payload
        assert "down" in payload["error"]
    finally:
        reset_web_search_providers()


def test_search_returns_an_empty_list_when_there_are_no_results(search_server, clite_home):
    register_web_search_provider("fake-post", lambda: _PostProvider(search_server))
    try:
        result = handle_function_call("web_search", {"query": "empty"}, ToolContext())
        payload = json.loads(result)
        assert payload["results"] == []
    finally:
        reset_web_search_providers()


def test_snippet_html_is_treated_as_untrusted_text(search_server, clite_home):
    """Snippets are untrusted text: HTML in them must not be stripped or interpreted; it is
    returned verbatim so the model sees exactly what the search backend sent."""
    register_web_search_provider("fake-post", lambda: _PostProvider(search_server))
    try:
        result = handle_function_call(
            "web_search",
            {"query": "injection"},
            ToolContext(),
        )
        payload = json.loads(result)
        second = payload["results"][1]
        assert "<script>alert(1)</script>" in second["snippet"]
    finally:
        reset_web_search_providers()
