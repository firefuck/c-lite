"""OpenAI speech: a keyed transcription provider and speech provider over the Audio API.

Requires ``OPENAI_API_KEY`` in ``.env``; get one at https://platform.openai.com/api-keys. The
key is registered as a credential so it is stripped from commands the agent runs and redacted
from what the model reads.

This is a backend plugin (``kind: backend``): it is auto-loaded, but ``text_to_speech`` is
offered only while a key is present, and a voice message is transcribed only then.

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

import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.tools.speech import SpeechProvider, TranscriptionProvider

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
SPEECH_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_TRANSCRIPTION_MODEL = "whisper-1"
DEFAULT_SPEECH_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "alloy"
#: What the API accepts for ``speed``; a request outside it is refused, not rounded.
SPEED_RANGE = (0.25, 4.0)
_USER_AGENT = "clite (+text_to_speech, transcription; openai)"

register_secret(
    SecretSpec(
        OPENAI_API_KEY_ENV,
        "OpenAI API key: speech and transcription",
        category="tool",
        url="https://platform.openai.com/api-keys",
    )
)


def _key(own: str) -> str:
    key = own or get_secret(OPENAI_API_KEY_ENV) or ""
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set; add it to .env to use speech")
    return key


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

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "") -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_TRANSCRIPTION_MODEL
        self._base_url = (base_url or TRANSCRIPTIONS_URL).rstrip("/")

    def transcribe(self, path: Path, *, model: str = "", language: str = "") -> str:
        audio = Path(path).read_bytes()
        fields = {"model": model or self._model, "response_format": "text"}
        if language:
            fields["language"] = language
        body, content_type = _multipart(Path(path).name, audio, fields)
        request = urllib.request.Request(  # noqa: S310 - https is enforced
            self._base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {_key(self._api_key)}",
                "Content-Type": content_type,
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 - https
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenAI transcription failed: {_failure(exc)}") from exc
        text = body.strip()
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
    output_format = "mp3"

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "") -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_SPEECH_MODEL
        self._base_url = (base_url or SPEECH_URL).rstrip("/")

    def synthesize(
        self, text: str, path: Path, *, voice: str = "", model: str = "", speed: float = 0.0
    ) -> Path:
        low, high = SPEED_RANGE
        if speed and not low <= speed <= high:
            raise ValueError(f"OpenAI accepts speed between {low} and {high}, not {speed}")
        payload: dict[str, object] = {
            "model": model or self._model,
            "input": text,
            "voice": voice or DEFAULT_VOICE,
            "response_format": self.output_format,
        }
        if speed:
            payload["speed"] = speed
        request = urllib.request.Request(  # noqa: S310 - https is enforced
            self._base_url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {_key(self._api_key)}",
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
    ctx.register_speech_provider("openai-speech", OpenAISpeechProvider)
