"""``vision_analyze``: the image goes to the ``auxiliary.vision`` route, never to a model that
cannot see.

The provider end is a real local HTTP server, so the request that leaves the process is the one
the test inspects: the last user message must carry an ``image_url`` part, addressed to the
auxiliary model. The main conversation model is a ``ScriptedClient`` that records what it was
sent, proving the picture never reaches it.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from clite.providers.auxiliary import resolve_auxiliary_route
from clite.providers.base import ProviderProfile
from clite.providers.client import LLMClient
from clite.providers.runtime import RuntimeRoute, resolve_runtime_provider
from clite.providers.testing import ScriptedClient, mock_route, text_response
from clite.tools.builtin import vision  # noqa: F401 - importing registers vision_analyze
from clite.tools.context import ToolContext
from clite.tools.dispatch import handle_function_call

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
PNG_BODY = PNG_HEADER + b"fake-image-payload"


class _ChatHandler(BaseHTTPRequestHandler):
    """A minimal OpenAI-compatible ``/v1/chat/completions`` echo server."""

    protocol_version = "HTTP/1.1"
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else {}
        self.requests.append({"path": self.path, "body": body})
        reply = {
            "id": "chatcmpl-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "a red square"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        }
        payload = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def chat_server():
    _ChatHandler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1", _ChatHandler
    finally:
        httpd.shutdown()
        httpd.server_close()


def _write_image(tmp_path: Path) -> Path:
    path = tmp_path / "picture.png"
    path.write_bytes(PNG_BODY)
    return path


def _vision_config(base_url: str) -> dict:
    """Config whose auxiliary vision route is a ``custom`` endpoint at ``base_url``."""
    return {
        "model": {"provider": "custom", "base_url": base_url, "api_mode": "chat_completions"},
        "auxiliary": {"vision": {"provider": "custom", "model": "vision-model"}},
    }


# ── the image is routed to the auxiliary model ─────────────────────────────────────────────


def test_vision_analyze_sends_the_image_to_the_auxiliary_route(tmp_path, chat_server, clite_home, monkeypatch):
    base_url, handler = chat_server
    monkeypatch.setenv("CUSTOM_API_KEY", "synthetic-key")
    image = _write_image(tmp_path)

    main_route = resolve_runtime_provider("custom", "main-model", base_url=base_url, api_key="k")
    ctx = ToolContext(
        agent=SimpleNamespace(route=main_route, client=LLMClient()),
        config=_vision_config(base_url),
    )

    result = json.loads(handle_function_call(
        "vision_analyze", {"path": str(image), "prompt": "what is in this picture?"}, ctx,
    ))
    assert "analysis" in result, result
    assert result["analysis"] == "a red square"
    assert result["model"] == "vision-model"

    assert len(handler.requests) == 1
    body = handler.requests[0]["body"]
    assert body["model"] == "vision-model", "the auxiliary.vision model must serve the request"
    parts = body["messages"][-1]["content"]
    assert isinstance(parts, list)
    image_parts = [part for part in parts if part.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    sent = base64.b64decode(image_parts[0]["image_url"]["url"].split(",", 1)[1])
    assert sent == PNG_BODY
    assert any(part.get("type") == "text" and "what is in this picture?" in part["text"] for part in parts)


def test_the_main_model_never_receives_the_image_parts(tmp_path, chat_server, clite_home, monkeypatch):
    """The conversation model only ever sees the helper's text answer, as a tool result."""
    base_url, handler = chat_server
    monkeypatch.setenv("CUSTOM_API_KEY", "synthetic-key")
    image = _write_image(tmp_path)

    main_route = resolve_runtime_provider("custom", "main-model", base_url=base_url, api_key="k")
    main_client = ScriptedClient([text_response("The picture shows a cat.")])
    ctx = ToolContext(
        agent=SimpleNamespace(route=main_route, client=LLMClient()),
        config=_vision_config(base_url),
    )
    handle_function_call("vision_analyze", {"path": str(image)}, ctx)

    assert handler.requests[0]["body"]["model"] == "vision-model"
    assert main_client.calls == [], "the main model must not be asked to look at anything"


# ── a route that cannot see is refused, with a way forward ─────────────────────────────────


def test_a_vision_route_whose_model_cannot_see_is_refused_before_any_call(tmp_path, chat_server, clite_home, monkeypatch):
    base_url, handler = chat_server
    monkeypatch.setenv("CUSTOM_API_KEY", "synthetic-key")
    image = _write_image(tmp_path)
    # A profile whose model ids are declared blind: images must never be sent to it.
    blind_profile = ProviderProfile(
        name="blind", base_url=base_url, vision_models=(), no_vision_prefixes=("main-model",),
    )
    blind = RuntimeRoute(provider="blind", model="main-model", api_mode="chat_completions",
                         base_url=base_url, profile=blind_profile, source="test")
    ctx = ToolContext(agent=SimpleNamespace(route=blind, client=LLMClient()),
                      config={"auxiliary": {"vision": {"provider": "main", "model": ""}}})

    result = json.loads(handle_function_call("vision_analyze", {"path": str(image)}, ctx))
    assert "accept images" in result.get("error", "")
    assert handler.requests == [], "no image may be sent to a model that cannot see"


def test_vision_analyze_requires_a_session_route(tmp_path, clite_home):
    image = _write_image(tmp_path)
    result = json.loads(handle_function_call("vision_analyze", {"path": str(image)}, ToolContext()))
    assert "running session" in result.get("error", "")


def test_vision_analyze_reports_a_missing_file_to_the_model(tmp_path, clite_home):
    ctx = ToolContext(agent=SimpleNamespace(route=mock_route(), client=ScriptedClient([])), config={})
    result = json.loads(handle_function_call("vision_analyze", {"path": str(tmp_path / "nope.png")}, ctx))
    assert "no file at" in result.get("error", "")


# ── route resolution ───────────────────────────────────────────────────────────────────────


def test_vision_route_defaults_to_the_main_route(clite_home):
    main = mock_route()
    assert resolve_auxiliary_route("vision", main) is main


def test_vision_route_is_configured_per_task(clite_home):
    (clite_home / "config.yaml").write_text(
        "auxiliary:\n  vision: {provider: main, model: sees-things}\n"
    )
    from clite.core.config import reset_config_cache

    reset_config_cache()
    route = resolve_auxiliary_route("vision", mock_route())
    assert route.model == "sees-things"


def test_a_profile_names_the_models_that_accept_images(clite_home):
    """A provider whose vision model is a separate id declares it, so a text-only model of the
    same provider is treated as blind and ``vision_analyze`` refuses it instead of sending the
    picture to a model that would reject it."""
    from clite.providers.registry import get_provider

    deepseek = get_provider("deepseek")
    assert deepseek is not None
    assert deepseek.supports_vision("deepseek-chat") is False
    assert deepseek.supports_vision("deepseek-v4-flash-vision-exp") is True


