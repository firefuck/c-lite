"""``text_to_speech`` and the two provider registries behind voice.

The tool is absent without a provider and present with one, a reply too long for the ceiling is
refused before anything is written, and the duration read off a container is the duration the
limits are applied to. Bundled plugins register real providers (``speech-openai``); the fakes
here keep the test on the tool and the registry rather than on a vendor.
"""

from __future__ import annotations

import json
import struct
import sys
import wave
from pathlib import Path

import pytest

from clite.tools.builtin import speech as speech_tool  # noqa: F401 - importing registers the tool
from clite.tools.context import ToolContext
from clite.tools.dispatch import handle_function_call
from clite.tools.registry import registry
from clite.tools.speech import (
    SpeechProvider,
    TranscriptionProvider,
    audio_seconds,
    get_speech_provider,
    get_transcription_provider,
    has_speech_provider,
    register_speech_provider,
    register_transcription_provider,
    reset_speech_registries,
    speaks_on,
    speech_limits,
)

MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 32


class _FakeSpeech(SpeechProvider):
    """An in-memory text-to-speech backend: it records the text and writes a fixed container."""

    name = "fake-speech"
    requires_api_key = False
    output_format = "mp3"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, float]] = []

    def synthesize(
        self, text: str, path: Path, *, voice: str = "", model: str = "", speed: float = 0.0
    ) -> Path:
        self.calls.append((text, voice, model, speed))
        Path(path).write_bytes(MP3)
        return Path(path)


class _FakeTranscriber(TranscriptionProvider):
    name = "fake-stt"
    requires_api_key = False

    def __init__(self, words: str = "the words that were spoken") -> None:
        self.words = words
        self.calls: list[Path] = []

    def transcribe(self, path: Path, *, model: str = "", language: str = "") -> str:
        self.calls.append(Path(path))
        return self.words


@pytest.fixture
def speaker():
    provider = _FakeSpeech()
    register_speech_provider("fake-speech", lambda: provider)
    try:
        yield provider
    finally:
        reset_speech_registries()


# ── check_fn gates the tool ────────────────────────────────────────────────────────────────


def test_text_to_speech_is_absent_without_a_provider(clite_home):
    reset_speech_registries()
    assert registry.is_available("text_to_speech") is False
    assert "text_to_speech" in registry.tools_in_toolset("messaging")


def test_text_to_speech_becomes_available_once_a_provider_is_registered(clite_home, speaker):
    assert registry.is_available("text_to_speech") is True
    assert has_speech_provider() is True


def test_the_tool_without_a_provider_tells_the_model_what_to_do(tmp_path, clite_home):
    reset_speech_registries()
    result = json.loads(
        handle_function_call("text_to_speech", {"text": "hello"}, ToolContext(cwd=str(tmp_path)))
    )
    assert "no speech provider is configured" in result["error"]
    assert not (tmp_path / "spoken").exists()


# ── the tool writes the audio ──────────────────────────────────────────────────────────────


def test_text_to_speech_writes_the_provider_bytes(tmp_path, clite_home, speaker):
    ctx = ToolContext(cwd=str(tmp_path))
    result = json.loads(handle_function_call("text_to_speech", {"text": "Good morning."}, ctx))
    assert result["provider"] == "fake-speech"
    saved = Path(result["path"])
    assert saved.exists() and saved.read_bytes() == MP3
    assert saved.suffix == ".mp3" and result["bytes"] == len(MP3)
    assert "send_file" in result["hint"]
    assert speaker.calls == [("Good morning.", "", "", 0.0)]


def test_text_to_speech_uses_the_configured_voice_and_names_the_file(tmp_path, clite_home, speaker):
    (clite_home / "config.yaml").write_text("speech:\n  speech:\n    voice: nova\n")
    ctx = ToolContext(cwd=str(tmp_path))
    result = json.loads(
        handle_function_call("text_to_speech", {"text": "Hi.", "output_name": "Greeting One"}, ctx)
    )
    assert Path(result["path"]).name == "greeting-one.mp3"
    assert speaker.calls[0][1] == "nova"


def test_text_to_speech_names_the_file_after_the_text_it_speaks(tmp_path, clite_home, speaker):
    """The schema promises a slug of the text when no name is given."""
    result = json.loads(
        handle_function_call("text_to_speech", {"text": "Water the plants."}, ToolContext(cwd=str(tmp_path)))
    )
    assert Path(result["path"]).name == "water-the-plants.mp3"


def test_text_to_speech_refuses_text_over_the_ceiling(tmp_path, clite_home, speaker):
    (clite_home / "config.yaml").write_text("speech:\n  max_chars: 10\n")
    result = json.loads(
        handle_function_call("text_to_speech", {"text": "x" * 11}, ToolContext(cwd=str(tmp_path)))
    )
    assert "keep it under 10" in result["error"]
    assert speaker.calls == [], "nothing may be paid for and thrown away"


def test_a_ceiling_of_zero_means_no_ceiling_on_both_voice_paths(tmp_path, clite_home, speaker):
    """``speech_limits`` documents zero as "no ceiling"; the tool has to agree."""
    (clite_home / "config.yaml").write_text("speech:\n  max_chars: 0\n")
    assert speech_limits()["max_chars"] == 0.0
    result = json.loads(
        handle_function_call("text_to_speech", {"text": "x" * 20_000}, ToolContext(cwd=str(tmp_path)))
    )
    assert "error" not in result and Path(result["path"]).exists()
    assert len(speaker.calls) == 1


def test_text_to_speech_reports_a_failing_provider(tmp_path, clite_home):
    class _Broken(SpeechProvider):
        name = "broken"

        def synthesize(self, text, path, *, voice="", model="", speed=0.0):
            raise RuntimeError("the vendor said no")

    register_speech_provider("broken", _Broken)
    try:
        result = json.loads(
            handle_function_call("text_to_speech", {"text": "hi"}, ToolContext(cwd=str(tmp_path)))
        )
        assert "speech synthesis failed" in result["error"] and "the vendor said no" in result["error"]
    finally:
        reset_speech_registries()


# ── the registry chooses the provider the configuration names ──────────────────────────────


def test_the_configured_provider_wins_over_the_first_registered(clite_home):
    (clite_home / "config.yaml").write_text("speech:\n  speech:\n    provider: zzz\n")

    def named(name: str) -> type[SpeechProvider]:
        return type(name, (_FakeSpeech,), {"name": name})

    register_speech_provider("aaa", named("aaa"))
    register_speech_provider("zzz", named("zzz"))
    try:
        assert get_speech_provider().name == "zzz"
    finally:
        reset_speech_registries()


def test_a_keyed_provider_without_its_key_is_skipped(clite_home):
    class _Keyed(_FakeTranscriber):
        name = "keyed"
        requires_api_key = True
        api_key_env = "CLITE_TEST_SPEECH_KEY"

    (clite_home / "config.yaml").write_text("speech:\n  transcription:\n    provider: keyed\n")
    register_transcription_provider("keyed", _Keyed)
    try:
        assert get_transcription_provider() is None, "an unusable provider leaves no voice at all"
    finally:
        reset_speech_registries()


def test_a_multi_keyed_provider_checks_any_available_key(clite_home, monkeypatch):
    class _MultiKeyed(_FakeTranscriber):
        name = "multi-keyed"
        requires_api_key = True
        api_key_envs = ("CLITE_SPEECH_KEY_1", "CLITE_SPEECH_KEY_2")

    (clite_home / "config.yaml").write_text("speech:\n  transcription:\n    provider: multi-keyed\n")
    register_transcription_provider("multi-keyed", _MultiKeyed)
    try:
        assert get_transcription_provider() is None
        monkeypatch.setenv("CLITE_SPEECH_KEY_2", "some-key")
        provider = get_transcription_provider()
        assert provider is not None
        assert provider.name == "multi-keyed"
    finally:
        reset_speech_registries()


def test_a_broken_factory_does_not_take_the_registry_down(clite_home):
    def broken():
        raise RuntimeError("this factory is broken")

    register_transcription_provider("broken", broken)
    register_transcription_provider("fine", _FakeTranscriber)
    try:
        provider = get_transcription_provider()
        assert provider is not None and provider.name == "fake-stt"
    finally:
        reset_speech_registries()


# ── limits and configuration ───────────────────────────────────────────────────────────────


def test_speech_limits_come_from_the_configuration(clite_home):
    (clite_home / "config.yaml").write_text(
        "speech:\n  max_seconds: 30\n  max_bytes: 1000\n  max_chars: 50\n"
    )
    assert speech_limits() == {"max_seconds": 30.0, "max_bytes": 1000.0, "max_chars": 50.0}


def test_reply_with_voice_names_the_platforms(clite_home):
    (clite_home / "config.yaml").write_text("speech:\n  reply_with_voice: [telegram]\n")
    assert speaks_on("telegram") is True
    assert speaks_on("local") is False


# ── how long a recording is ────────────────────────────────────────────────────────────────


def _wav(path: Path, seconds: float, rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _ogg_page(header_type: int, granule: int, serial: int, payload: bytes) -> bytes:
    """One Ogg page, structurally valid: a one-entry segment table, then the payload."""
    return (
        b"OggS"
        + bytes([0, header_type])
        + struct.pack("<Q", granule)
        + struct.pack("<I", serial)
        + struct.pack("<I", 0)  # page sequence
        + struct.pack("<I", 0)  # CRC, which nothing here checks
        + bytes([1, len(payload)])  # one segment, so long
        + payload
    )


def _ogg_opus(path: Path, granule: int) -> Path:
    """Enough of an Ogg Opus stream for the duration read: a head page naming Opus, then a final
    page whose granule position is the one that counts."""
    head = _ogg_page(2, 0, 1, b"OpusHead" + bytes(19 - len("OpusHead")))
    tail = _ogg_page(4, granule, 1, b"payload")
    path.write_bytes(head + tail)
    return path


def test_a_wav_reports_its_own_duration(tmp_path):
    seconds = audio_seconds(_wav(tmp_path / "note.wav", 2.5))
    assert seconds == pytest.approx(2.5, abs=0.01)


def test_an_ogg_opus_reports_its_duration_from_the_granule_position(tmp_path):
    # 96 000 granules at 48 kHz is two seconds.
    assert audio_seconds(_ogg_opus(tmp_path / "note.ogg", 96_000)) == pytest.approx(2.0)


def test_a_stray_oggs_inside_a_payload_is_not_read_as_a_page(tmp_path):
    """Compressed audio carries whatever bytes it likes, ``OggS`` included.

    A real page has to account for every byte up to the end it is read from, which a marker
    inside a packet cannot do; taking the marker at face value would report no duration at all
    (its granule field reads as zero) and refuse a recording the user is allowed to send.
    """
    head = _ogg_page(2, 0, 1, b"OpusHead" + bytes(19 - len("OpusHead")))
    fake = b"OggS" + b"\x00" * 40  # the marker, in the middle of a packet
    tail = _ogg_page(4, 96_000, 1, fake + b"x" * 8)
    path = tmp_path / "note.ogg"
    path.write_bytes(head + tail)
    assert audio_seconds(path) == pytest.approx(2.0)


def test_an_unreadable_container_is_reported_as_unknown(tmp_path):
    assert audio_seconds(tmp_path / "note.m4a") is None
    (tmp_path / "note.m4a").write_bytes(b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 16)
    assert audio_seconds(tmp_path / "note.m4a") is None


def test_a_broken_wav_is_unknown_rather_than_an_error(tmp_path):
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunk")
    assert audio_seconds(broken) is None


# ── the bundled plugin against a local stand-in for the API ────────────────────────────────


def _write_voice_note(tmp_path) -> Path:
    """A file the classifier reads as audio: an Ogg container, which is what Telegram sends."""
    note = tmp_path / "note.ogg"
    note.write_bytes(b"OggS" + b"\x00" * 40)
    return note


def _serve(handler_body):
    """A one-shot local HTTP server; returns (url_base, recorded requests)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    recorded: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            recorded.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "content_type": self.headers.get("Content-Type"),
                    "body": body,
                }
            )
            status, content_type, payload = handler_body(body)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", recorded, httpd


def test_the_bundled_openai_plugin_registers_both_providers(clite_home, monkeypatch):
    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    reset_speech_registries()
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    manager = plugins_manager.ensure_plugins_loaded()
    assert manager.plugins["speech-openai"].status == "loaded"
    try:
        assert get_transcription_provider().name == "openai-transcribe"
        assert get_speech_provider().name == "openai-speech"
        assert f"{PLUGIN_NAMESPACE}.speech_openai" in sys.modules
    finally:
        reset_speech_registries()


def test_the_openai_provider_posts_the_documented_transcription_request(tmp_path, clite_home, monkeypatch):
    """Multipart with the audio under ``file``, plus the model and the language hint."""
    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    plugins_manager.ensure_plugins_loaded()
    provider_class = sys.modules[f"{PLUGIN_NAMESPACE}.speech_openai"].OpenAITranscriptionProvider

    def respond(_body):
        return 200, "text/plain", b"water the plants"

    base, recorded, httpd = _serve(respond)
    try:
        words = provider_class(base_url=f"{base}/v1/audio/transcriptions").transcribe(
            _write_voice_note(tmp_path), language="en"
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert words == "water the plants"  # response_format=text comes back as the transcript
    request = recorded[0]
    assert request["path"] == "/v1/audio/transcriptions"
    assert request["auth"] == "Bearer synthetic-key"
    assert request["content_type"].startswith("multipart/form-data; boundary=")
    body = request["body"]
    assert b'name="model"' in body and b"whisper-1" in body
    assert b'name="language"' in body and b"\r\n\r\nen\r\n" in body
    assert b'name="response_format"' in body and b"text" in body
    assert b'name="file"; filename="note.ogg"' in body and b"OggS" in body


def test_the_openai_provider_posts_the_documented_speech_request(tmp_path, clite_home, monkeypatch):
    """JSON with ``input``, ``voice`` and ``response_format``; the reply is the audio itself."""

    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    plugins_manager.ensure_plugins_loaded()
    provider_class = sys.modules[f"{PLUGIN_NAMESPACE}.speech_openai"].OpenAISpeechProvider

    audio = b"\xff\xfb" + b"spoken-bytes"

    def respond(_body):
        return 200, "audio/mpeg", audio

    base, recorded, httpd = _serve(respond)
    target = tmp_path / "reply.mp3"
    try:
        written = provider_class(base_url=f"{base}/v1/audio/speech").synthesize(
            "Everything is fine.", target, voice="nova", speed=1.5
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert written == target and target.read_bytes() == audio
    request = recorded[0]
    assert request["path"] == "/v1/audio/speech"
    assert request["auth"] == "Bearer synthetic-key"
    body = json.loads(request["body"])
    assert body["model"] == "gpt-4o-mini-tts"
    assert body["input"] == "Everything is fine."
    assert body["voice"] == "nova" and body["speed"] == 1.5
    assert body["response_format"] == "mp3"


def test_the_openai_speech_provider_refuses_a_speed_the_api_does_not_accept(tmp_path, clite_home):
    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    plugins_manager.ensure_plugins_loaded()
    provider_class = sys.modules[f"{PLUGIN_NAMESPACE}.speech_openai"].OpenAISpeechProvider
    with pytest.raises(ValueError, match="0.25"):
        provider_class(api_key="synthetic-key").synthesize("hi", tmp_path / "x.mp3", speed=9.0)


def test_a_provider_error_message_is_carried_through(tmp_path, clite_home, monkeypatch):
    """The API's own sentence reaches the caller, not just a status code."""
    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    plugins_manager.ensure_plugins_loaded()
    provider_class = sys.modules[f"{PLUGIN_NAMESPACE}.speech_openai"].OpenAISpeechProvider

    def respond(_body):
        return 400, "application/json", json.dumps({"error": {"message": "voice not found"}}).encode()

    base, _recorded, httpd = _serve(respond)
    try:
        with pytest.raises(RuntimeError, match="voice not found"):
            provider_class(base_url=f"{base}/v1/audio/speech").synthesize("hi", tmp_path / "x.mp3")
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── multi-key discovery, fallback endpoints, and Gemini STT ───────────────────────────────


def test_groq_key_enables_transcription_and_routes_to_groq_endpoint(tmp_path, clite_home, monkeypatch):
    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    reset_speech_registries()
    monkeypatch.setenv("GROQ_API_KEY", "gsk-synthetic-key")
    manager = plugins_manager.ensure_plugins_loaded()
    assert manager.plugins["speech-openai"].status == "loaded"

    provider = get_transcription_provider()
    assert provider is not None
    assert provider.name == "openai-transcribe"

    def respond(_body):
        return 200, "text/plain", b"groq transcript text"

    base, recorded, httpd = _serve(respond)
    try:
        # Patch GROQ_TRANSCRIPTIONS_URL in speech_openai module to route to our test server
        mod = sys.modules[f"{PLUGIN_NAMESPACE}.speech_openai"]
        monkeypatch.setattr(mod, "GROQ_TRANSCRIPTIONS_URL", f"{base}/openai/v1/audio/transcriptions")
        text = provider.transcribe(_write_voice_note(tmp_path))
    finally:
        httpd.shutdown()
        httpd.server_close()
        reset_speech_registries()

    assert text == "groq transcript text"
    req = recorded[0]
    assert req["path"] == "/openai/v1/audio/transcriptions"
    assert req["auth"] == "Bearer gsk-synthetic-key"
    assert b'name="model"' in req["body"] and b"whisper-large-v3" in req["body"]


def test_custom_key_enables_speech_and_transcription(tmp_path, clite_home, monkeypatch):
    from clite.plugins import manager as plugins_manager

    reset_speech_registries()
    monkeypatch.setenv("CUSTOM_API_KEY", "custom-secret-key")
    plugins_manager.ensure_plugins_loaded()

    stt_provider = get_transcription_provider()
    tts_provider = get_speech_provider()
    assert stt_provider is not None
    assert tts_provider is not None

    def respond_stt(_body):
        return 200, "text/plain", b"custom transcribed"

    base, recorded_stt, httpd_stt = _serve(respond_stt)
    try:
        monkeypatch.setenv("CUSTOM_BASE_URL", base)
        text = stt_provider.transcribe(_write_voice_note(tmp_path))
    finally:
        httpd_stt.shutdown()
        httpd_stt.server_close()

    assert text == "custom transcribed"
    assert recorded_stt[0]["path"] == "/audio/transcriptions"
    assert recorded_stt[0]["auth"] == "Bearer custom-secret-key"

    def respond_tts(_body):
        return 200, "audio/mpeg", MP3

    base_tts, recorded_tts, httpd_tts = _serve(respond_tts)
    out_file = tmp_path / "custom_out.mp3"
    try:
        monkeypatch.setenv("CUSTOM_BASE_URL", base_tts)
        written = tts_provider.synthesize("Custom hello", out_file)
    finally:
        httpd_tts.shutdown()
        httpd_tts.server_close()
        reset_speech_registries()

    assert written.exists() and written.read_bytes() == MP3
    assert recorded_tts[0]["path"] == "/audio/speech"
    assert recorded_tts[0]["auth"] == "Bearer custom-secret-key"


def test_gemini_key_enables_gemini_transcription(tmp_path, clite_home, monkeypatch):
    from clite.core.brand import PLUGIN_NAMESPACE
    from clite.plugins import manager as plugins_manager

    reset_speech_registries()
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-synthetic-key")
    (clite_home / "config.yaml").write_text("speech:\n  transcription:\n    provider: gemini-transcribe\n")
    plugins_manager.ensure_plugins_loaded()

    provider = get_transcription_provider()
    assert provider is not None
    assert provider.name == "gemini-transcribe"

    gemini_reply = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Hello from Gemini speech transcription!"}],
                    "role": "model",
                }
            }
        ]
    }

    def respond(_body):
        return 200, "application/json", json.dumps(gemini_reply).encode("utf-8")

    base, recorded, httpd = _serve(respond)
    try:
        mod = sys.modules[f"{PLUGIN_NAMESPACE}.speech_openai"]
        gemini_class = mod.GeminiTranscriptionProvider
        inst = gemini_class(base_url=f"{base}/v1beta/models/{{model}}:generateContent")
        text = inst.transcribe(_write_voice_note(tmp_path), language="en")
    finally:
        httpd.shutdown()
        httpd.server_close()
        reset_speech_registries()

    assert text == "Hello from Gemini speech transcription!"
    assert len(recorded) == 1
    req = recorded[0]
    assert req["path"].startswith("/v1beta/models/gemini-2.0-flash:generateContent?key=gemini-synthetic-key")
    assert req["content_type"] == "application/json"
    body = json.loads(req["body"])
    parts = body["contents"][0]["parts"]
    assert any("inlineData" in p and p["inlineData"]["mimeType"] == "audio/ogg" for p in parts)
    assert any("Generate a transcript of the speech." in p.get("text", "") for p in parts)


def test_google_api_key_also_activates_gemini_transcription(clite_home, monkeypatch):
    from clite.plugins import manager as plugins_manager

    reset_speech_registries()
    monkeypatch.setenv("GOOGLE_API_KEY", "google-synthetic-key")
    (clite_home / "config.yaml").write_text("speech:\n  transcription:\n    provider: gemini-transcribe\n")
    plugins_manager.ensure_plugins_loaded()

    provider = get_transcription_provider()
    assert provider is not None
    assert provider.name == "gemini-transcribe"
    reset_speech_registries()
