"""OpenAI speech: a keyed transcription provider and speech provider over the Audio API.

Requires ``OPENAI_API_KEY``, ``GROQ_API_KEY``, or ``CUSTOM_API_KEY`` in ``.env``.
Keys are registered as credentials so they are stripped from commands the agent runs
and redacted from what the model reads.

This is a backend plugin (``kind: backend``): it is auto-loaded, but ``text_to_speech`` is
offered only while a compatible key is present, and a voice message is transcribed only then.

Endpoints and shapes checked 2026-10-10:

* ``POST https://api.openai.com/v1/audio/transcriptions`` -- ``multipart/form-data`` with the
  audio under ``file``, plus ``model``, ``language`` and ``response_format``. The reply for
  ``response_format=text`` is the transcript itself. Files are capped at 25 MB and the accepted
  containers are mp3, mp4, mpeg, mpga, m4a, wav and webm; ``speech.max_bytes`` is the ceiling
  that actually applies here. The guide names ``gpt-transcribe`` as the current model but wants
  it given ``languages[]`` rather than ``language``, so the default is ``whisper-1``, which takes
  the singular field the configuration holds.
* ``POST https://api.openai.com/v1/audio/speech`` -- JSON with ``model``, ``input`` and
  ``voice``; optional ``response_format`` (mp3, opus, aac, flac, wav, pcm) and ``speed``
  (0.25-4.0). ``input`` is capped at 4096 characters, and ``speech.max_chars`` defaults to 4000,
  just under it. Voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer,
  verse, marin, cedar. The guide recommends ``marin`` or ``cedar`` for quality with the default
  model; ``alloy`` is used here because every model accepts it.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.tools.speech import SpeechProvider, TranscriptionProvider

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
COMPATIBLE_API_KEY_ENVS = ("OPENAI_API_KEY", "GROQ_API_KEY", "CUSTOM_API_KEY")

TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

SPEECH_URL = "https://api.openai.com/v1/audio/speech"

GEMINI_API_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_GENERATE_CONTENT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

DEFAULT_TRANSCRIPTION_MODEL = "whisper-1"
DEFAULT_GROQ_TRANSCRIPTION_MODEL = "whisper-large-v3"
DEFAULT_SPEECH_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "alloy"
#: What the API accepts for ``speed``; a request outside it is refused, not rounded.
SPEED_RANGE = (0.25, 4.0)
_USER_AGENT = "clite (+text_to_speech, transcription; openai)"

for _env_name in COMPATIBLE_API_KEY_ENVS:
    register_secret(
        SecretSpec(
            _env_name,
            f"{_env_name} API key: speech and transcription",
            category="tool",
            url="https://platform.openai.com/api-keys",
        )
    )

for _env_name in GEMINI_API_KEY_ENVS:
    register_secret(
        SecretSpec(
            _env_name,
            f"{_env_name} API key: Gemini transcription",
            category="tool",
            url="https://aistudio.google.com/apikey",
        )
    )


def _key(own: str) -> str:
    if own:
        return own
    for env in COMPATIBLE_API_KEY_ENVS:
        val = get_secret(env)
        if val:
            return val
    raise RuntimeError(
        "No compatible speech API key set; add OPENAI_API_KEY, GROQ_API_KEY, or CUSTOM_API_KEY to .env"
    )


def _resolve_transcription_endpoint_and_key(
    own_key: str, own_base_url: str, own_model: str
) -> tuple[str, str, str]:
    """Resolve (url, key, model) for transcription based on available configuration/keys."""
    if own_base_url:
        key = own_key or _key("")
        return own_base_url.rstrip("/"), key, own_model or DEFAULT_TRANSCRIPTION_MODEL

    # If an explicit key was provided:
    if own_key:
        return TRANSCRIPTIONS_URL, own_key, own_model or DEFAULT_TRANSCRIPTION_MODEL

    # Check available keys in order: OPENAI, then GROQ, then CUSTOM
    openai_key = get_secret("OPENAI_API_KEY")
    if openai_key:
        return TRANSCRIPTIONS_URL, openai_key, own_model or DEFAULT_TRANSCRIPTION_MODEL
    groq_key = get_secret("GROQ_API_KEY")
    if groq_key:
        return GROQ_TRANSCRIPTIONS_URL, groq_key, own_model or DEFAULT_GROQ_TRANSCRIPTION_MODEL
    custom_key = get_secret("CUSTOM_API_KEY")
    if custom_key:
        custom_base = get_secret("CUSTOM_BASE_URL") or "https://api.openai.com/v1"
        url = custom_base.rstrip("/") + "/audio/transcriptions"
        return url, custom_key, own_model or DEFAULT_TRANSCRIPTION_MODEL

    return TRANSCRIPTIONS_URL, _key(""), own_model or DEFAULT_TRANSCRIPTION_MODEL


def _resolve_speech_endpoint_and_key(own_key: str, own_base_url: str, own_model: str) -> tuple[str, str, str]:
    """Resolve (url, key, model) for speech synthesis based on available configuration/keys."""
    if own_base_url:
        key = own_key or _key("")
        return own_base_url.rstrip("/"), key, own_model or DEFAULT_SPEECH_MODEL

    if own_key:
        return SPEECH_URL, own_key, own_model or DEFAULT_SPEECH_MODEL

    openai_key = get_secret("OPENAI_API_KEY")
    if openai_key:
        return SPEECH_URL, openai_key, own_model or DEFAULT_SPEECH_MODEL
    custom_key = get_secret("CUSTOM_API_KEY")
    if custom_key:
        custom_base = get_secret("CUSTOM_BASE_URL") or "https://api.openai.com/v1"
        url = custom_base.rstrip("/") + "/audio/speech"
        return url, custom_key, own_model or DEFAULT_SPEECH_MODEL
    groq_key = get_secret("GROQ_API_KEY")
    if groq_key:
        return SPEECH_URL, groq_key, own_model or DEFAULT_SPEECH_MODEL

    return SPEECH_URL, _key(""), own_model or DEFAULT_SPEECH_MODEL


def _failure(exc: urllib.error.HTTPError) -> str:
    """The API's own error text, which says what was wrong with the request."""
    try:
        body = json.loads(exc.read())
        message = str((body.get("error") or {}).get("message") or "").strip()
    except Exception:  # noqa: BLE001 - a body that is not the documented JSON is not worth quoting
        message = ""
    return message or str(exc)


class OpenAITranscriptionProvider(TranscriptionProvider):
    name = "openai-transcribe"
    requires_api_key = True
    api_key_env = OPENAI_API_KEY_ENV
    api_key_envs = COMPATIBLE_API_KEY_ENVS

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

    def transcribe(self, path: Path, *, model: str = "", language: str = "") -> str:
        resolved_url, key, default_model = _resolve_transcription_endpoint_and_key(
            self._api_key, self._base_url, self._model
        )
        audio = Path(path).read_bytes()
        fields = {"model": model or default_model, "response_format": "text"}
        if language:
            fields["language"] = language
        body, content_type = _multipart(Path(path).name, audio, fields)
        request = urllib.request.Request(  # noqa: S310 - https is enforced
            resolved_url,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": content_type,
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 - https
                body_bytes = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenAI transcription failed: {_failure(exc)}") from exc
        text = body_bytes.strip()
        if text.startswith("{"):  # a model that answered JSON despite response_format=text
            try:
                text = str(json.loads(text).get("text") or "").strip()
            except json.JSONDecodeError:
                pass
        return text


class OpenAISpeechProvider(SpeechProvider):
    name = "openai-speech"
    requires_api_key = True
    api_key_env = OPENAI_API_KEY_ENV
    api_key_envs = COMPATIBLE_API_KEY_ENVS
    output_format = "mp3"

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

    def synthesize(
        self, text: str, path: Path, *, voice: str = "", model: str = "", speed: float = 0.0
    ) -> Path:
        low, high = SPEED_RANGE
        if speed and not low <= speed <= high:
            raise ValueError(f"OpenAI accepts speed between {low} and {high}, not {speed}")
        resolved_url, key, default_model = _resolve_speech_endpoint_and_key(
            self._api_key, self._base_url, self._model
        )
        payload: dict[str, object] = {
            "model": model or default_model,
            "input": text,
            "voice": voice or DEFAULT_VOICE,
            "response_format": self.output_format,
        }
        if speed:
            payload["speed"] = speed
        request = urllib.request.Request(  # noqa: S310 - https is enforced
            resolved_url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - https
                audio = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenAI speech synthesis failed: {_failure(exc)}") from exc
        if not audio:
            raise RuntimeError("OpenAI returned no audio")
        Path(path).write_bytes(audio)
        return Path(path)


def _gemini_key(own: str) -> str:
    if own:
        return own
    for env in GEMINI_API_KEY_ENVS:
        val = get_secret(env)
        if val:
            return val
    raise RuntimeError("No Gemini API key set; add GEMINI_API_KEY or GOOGLE_API_KEY to .env")


class GeminiTranscriptionProvider(TranscriptionProvider):
    name = "gemini-transcribe"
    requires_api_key = True
    api_key_env = "GEMINI_API_KEY"
    api_key_envs = GEMINI_API_KEY_ENVS

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "") -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_GEMINI_MODEL
        self._base_url = base_url

    def transcribe(self, path: Path, *, model: str = "", language: str = "") -> str:
        key = _gemini_key(self._api_key)
        target_model = model or self._model
        audio_data = Path(path).read_bytes()
        mime_type, _ = mimetypes.guess_type(Path(path).name)
        if not mime_type:
            suffix = Path(path).suffix.lower()
            if suffix in (".ogg", ".opus"):
                mime_type = "audio/ogg"
            elif suffix == ".wav":
                mime_type = "audio/wav"
            elif suffix == ".mp3":
                mime_type = "audio/mp3"
            else:
                mime_type = "audio/ogg"

        prompt = "Generate a transcript of the speech."
        if language:
            prompt += f" The language is {language}."

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(audio_data).decode("ascii"),
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ]
        }

        if self._base_url:
            base = self._base_url.rstrip("/")
            if "{model}" in base:
                url = base.format(model=target_model)
            else:
                url = f"{base}/v1beta/models/{target_model}:generateContent"
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={urllib.parse.quote(key)}"
        else:
            endpoint = GEMINI_GENERATE_CONTENT_URL.format(model=target_model)
            url = f"{endpoint}?key={urllib.parse.quote(key)}"

        request = urllib.request.Request(  # noqa: S310 - https is enforced
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 - https
                resp_bytes = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Gemini transcription failed: {_failure(exc)}") from exc

        try:
            resp_json = json.loads(resp_bytes)
            candidates = resp_json.get("candidates") or []
            if candidates:
                content = candidates[0].get("content") or {}
                parts = content.get("parts") or []
                return "".join(part.get("text", "") for part in parts).strip()
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            raise RuntimeError(f"Gemini returned unexpected response format: {exc}") from exc

        return ""


def _multipart(filename: str, data: bytes, fields: dict[str, str]) -> tuple[bytes, str]:
    """One ``multipart/form-data`` body: the plain fields, then the file."""
    boundary = "----clite-openai-audio-7f3a1c"
    body = bytearray()
    for name, value in fields.items():
        body.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
    )
    body.extend(data)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def register(ctx) -> None:
    ctx.register_transcription_provider("openai-transcribe", OpenAITranscriptionProvider)
    ctx.register_transcription_provider("gemini-transcribe", GeminiTranscriptionProvider)
    ctx.register_speech_provider("openai-speech", OpenAISpeechProvider)
