"""``image_generate``: the tool is absent without a provider, present with one, and routes
through the ``ImageProvider`` registry.

A bundled plugin (``image-gen-openai``) registers a real provider; the tests here register a
fake one so the tool's own behaviour — provider selection, saving files, size checks — is what
is under test, not the vendor.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

from clite.tools.builtin import image_gen as image_gen_tool  # noqa: F401 - importing registers the tool
from clite.tools.context import ToolContext
from clite.tools.dispatch import get_tool_definitions, handle_function_call
from clite.tools.image_gen import (
    GeneratedImage,
    ImageProvider,
    get_image_provider,
    has_image_provider,
    provider_names,
    register_image_provider,
    reset_image_providers,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"generated-bytes"


class _FakeProvider(ImageProvider):
    """An in-memory provider: it records prompts and returns raw bytes, no network."""

    name = "fake"
    requires_api_key = False
    supported_sizes = ("256x256", "512x512")

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def generate(self, prompt: str, *, size: str = "", count: int = 1) -> list[GeneratedImage]:
        self.calls.append((prompt, size, count))
        return [GeneratedImage("image/png", PNG + str(index).encode()) for index in range(count)]


@pytest.fixture
def provider():
    provider = _FakeProvider()
    register_image_provider("fake", lambda: provider)
    try:
        yield provider
    finally:
        reset_image_providers()


# ── check_fn gates the tool ────────────────────────────────────────────────────────────────


def test_image_generate_is_absent_from_tool_definitions_without_a_provider(clite_home):
    reset_image_providers()
    names = [d["function"]["name"] for d in get_tool_definitions(["vision"])]
    assert "image_generate" not in names
    assert "vision_analyze" in names, "the reading tool stays; it needs no backend"


def test_image_generate_is_present_in_tool_definitions_when_a_provider_is_registered(clite_home, provider):
    names = [d["function"]["name"] for d in get_tool_definitions(["vision"])]
    assert "image_generate" in names


def test_check_fn_reflects_provider_availability(clite_home, provider):
    assert has_image_provider() is True
    reset_image_providers()
    assert has_image_provider() is False


# ── the tool routes through the registry and saves the bytes ───────────────────────────────


def test_image_generate_writes_the_provider_bytes_to_a_file(tmp_path, clite_home, provider):
    ctx = ToolContext(cwd=str(tmp_path))
    result = json.loads(handle_function_call("image_generate", {"prompt": "a blue circle"}, ctx))
    assert result["provider"] == "fake"
    assert len(result["images"]) == 1
    saved = Path(result["images"][0]["path"])
    assert saved.exists() and saved.read_bytes() == PNG + b"0"
    assert result["images"][0]["media_type"] == "image/png"
    assert provider.calls == [("a blue circle", "", 1)]


def test_image_generate_asks_for_the_requested_size_and_count(tmp_path, clite_home, provider):
    ctx = ToolContext(cwd=str(tmp_path))
    result = json.loads(
        handle_function_call("image_generate", {"prompt": "three cats", "size": "512x512", "count": 3}, ctx)
    )
    assert len(result["images"]) == 3
    assert provider.calls == [("three cats", "512x512", 3)]
    assert len({image["path"] for image in result["images"]}) == 3  # distinct file names


def test_image_generate_refuses_a_size_the_provider_does_not_support(tmp_path, clite_home, provider):
    ctx = ToolContext(cwd=str(tmp_path))
    result = json.loads(handle_function_call("image_generate", {"prompt": "x", "size": "4096x4096"}, ctx))
    assert "not supported" in result["error"] and "512x512" in result["error"]
    assert provider.calls == [], "the provider must not be called with a size it rejects"


def test_image_generate_reports_a_missing_prompt(tmp_path, clite_home, provider):
    result = json.loads(handle_function_call("image_generate", {}, ToolContext(cwd=str(tmp_path))))
    assert "prompt is required" in result["error"]


def test_image_generate_without_a_provider_tells_the_model_what_to_do(tmp_path, clite_home):
    reset_image_providers()
    result = json.loads(
        handle_function_call("image_generate", {"prompt": "x"}, ToolContext(cwd=str(tmp_path)))
    )
    assert "no image generation provider" in result["error"]


def test_image_generate_consults_the_file_safety_guard_before_writing(
    tmp_path, clite_home, provider, monkeypatch
):
    """A generated image is a file write like any other: the safety list is consulted first."""
    import clite.tools.builtin.image_gen as module

    monkeypatch.setattr(module, "write_denied_reason", lambda path: "it holds this agent's own settings")
    result = json.loads(
        handle_function_call("image_generate", {"prompt": "x"}, ToolContext(cwd=str(tmp_path)))
    )
    assert "Refused to write" in result["error"]
    assert not list(tmp_path.glob("generated-images/*")), "nothing may be written when refused"


# ── the bundled plugin ─────────────────────────────────────────────────────────────────────


def test_the_bundled_openai_plugin_registers_a_provider(clite_home, monkeypatch):
    """Loading the bundled plugin makes the openai-images provider available via the registry."""
    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    reset_image_providers()
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    # Load through the path production uses: the bundled plugin directory and its manager.
    manager = plugins_manager.ensure_plugins_loaded()
    assert manager.plugins["image-gen-openai"].status == "loaded"
    try:
        assert "openai-images" in provider_names()
        assert has_image_provider() is True
        assert get_image_provider().name == "openai-images"
        assert f"{PLUGIN_NAMESPACE}.image_gen_openai" in sys.modules
    finally:
        reset_image_providers()


def test_the_openai_provider_posts_the_documented_images_request(clite_home, monkeypatch):
    """The bundled provider sends ``model``/``prompt``/``size``/``n`` and decodes ``b64_json``."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    plugins_manager.ensure_plugins_loaded()
    provider_class = sys.modules[f"{PLUGIN_NAMESPACE}.image_gen_openai"].OpenAIImageProvider

    recorded: list[dict] = []
    png = b"\x89PNG\r\n\x1a\n" + b"openai-image"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length") or 0)
            recorded.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(length)) if length else {},
                }
            )
            reply = {
                "data": [{"b64_json": base64.b64encode(png).decode(), "revised_prompt": "a tidy version"}]
            }
            payload = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/v1/images/generations"
        images = provider_class(base_url=url).generate("a tidy robot", size="1024x1024", count=2)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert recorded[0]["body"]["model"] == "gpt-image-1"
    assert recorded[0]["body"]["prompt"] == "a tidy robot"
    assert recorded[0]["body"]["size"] == "1024x1024"
    assert recorded[0]["body"]["n"] == 2
    assert recorded[0]["auth"] == "Bearer synthetic-key"
    assert images[0].data == png and images[0].metadata["revised_prompt"] == "a tidy version"
