"""``TranscriptionProvider`` and ``SpeechProvider``: the two pluggable backends behind voice.

Voice runs in two directions, so there are two registries. A plugin registers a factory with
:func:`register_transcription_provider` or :func:`register_speech_provider` -- from a plugin,
``ctx.register_transcription_provider(name, factory)`` -- and each is selected by the
``speech`` section of ``config.yaml``. Both sides are offered only when a provider is actually
configured, so the ``text_to_speech`` tool is never advertised on a machine that cannot speak,
and a voice note is never promised a transcript that nothing will write.

A provider raises on failure. Turning that into something the user or the model reads is the
caller's job: the tool reports it as a tool error, the gateway as a notice in the chat.
"""

from __future__ import annotations

import os
import threading
import wave
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

from clite.core.config import get_path, load_config


class TranscriptionProvider(ABC):
    """A speech-to-text backend. Implementations live in plugins (``kind: backend``)."""

    name: str = ""
    #: When True, the provider only activates if its API key is present in ``.env``.
    requires_api_key: bool = False
    #: The environment variable that holds the API key (for single-key providers).
    api_key_env: str = ""
    #: Environment variables that hold compatible API keys (checked in order).
    api_key_envs: tuple[str, ...] = ()

    def is_available(self) -> bool:
        """Whether this provider has the credentials or environment it needs."""
        from clite.core.env import get_secret

        if not self.requires_api_key:
            return True
        keys = (
            tuple(self.api_key_envs)
            if self.api_key_envs
            else ((self.api_key_env,) if self.api_key_env else ())
        )
        if not keys:
            return True
        return any(bool(get_secret(k)) for k in keys)

    @abstractmethod
    def transcribe(self, path: Path, *, model: str = "", language: str = "") -> str:
        """Return the transcript of the audio at ``path``. Raises on failure.

        ``model`` and ``language`` are empty when the configuration named neither, and the
        provider then uses its own default. An empty string is a valid answer for audio that
        carries no speech; the caller decides what to tell the user.
        """


class SpeechProvider(ABC):
    """A text-to-speech backend. Implementations live in plugins (``kind: backend``)."""

    name: str = ""
    #: When True, the provider only activates if its API key is present in ``.env``.
    requires_api_key: bool = False
    #: The environment variable that holds the API key (for single-key providers).
    api_key_env: str = ""
    #: Environment variables that hold compatible API keys (checked in order).
    api_key_envs: tuple[str, ...] = ()
    #: The container the provider writes, which decides the extension of the file the user gets.
    output_format: str = "mp3"

    def is_available(self) -> bool:
        """Whether this provider has the credentials or environment it needs."""
        from clite.core.env import get_secret

        if not self.requires_api_key:
            return True
        keys = (
            tuple(self.api_key_envs)
            if self.api_key_envs
            else ((self.api_key_env,) if self.api_key_env else ())
        )
        if not keys:
            return True
        return any(bool(get_secret(k)) for k in keys)

    @abstractmethod
    def synthesize(
        self, text: str, path: Path, *, voice: str = "", model: str = "", speed: float = 0.0
    ) -> Path:
        """Write ``text`` as audio to ``path`` and return it. Raises on failure.

        The parent directory already exists. ``voice``, ``model`` and ``speed`` are empty or
        zero when the caller asked for none, and a provider that cannot honour one raises rather
        than quietly speaking in another voice.
        """


# ── registries ─────────────────────────────────────────────────────────────────────────


class _Registry:
    """One provider table: registration, teardown, and the config-driven lookup.

    Selection is deliberately forgiving: a preferred name that is not registered, or whose
    factory is broken, or whose key is missing, falls through to the next provider instead of
    leaving the user with no voice at all.
    """

    def __init__(self, kind: str, config_key: str) -> None:
        self.kind = kind
        self.config_key = config_key
        self._factories: dict[str, Callable[[], Any]] = {}
        self._lock = threading.RLock()

    def register(self, name: str, factory: Callable[[], Any]) -> None:
        """Register a factory. The last registration of a name wins."""
        with self._lock:
            self._factories[name] = factory

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._factories.pop(name, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._factories.clear()

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._factories)

    def get(self) -> Any | None:
        """The active provider, or None when nothing is registered and usable."""
        from clite.core.env import get_secret

        preferred = str(get_path(load_config(), self.config_key, "") or "").strip()
        names = self.names()
        ordered = [preferred, *(name for name in names if name != preferred)] if preferred else names
        with self._lock:
            factories = [(name, self._factories[name]) for name in ordered if name in self._factories]
        for _name, factory in factories:
            try:
                provider = factory()
            except Exception:  # noqa: BLE001 - a broken factory is skipped, not fatal
                continue
            if hasattr(provider, "is_available"):
                try:
                    if not provider.is_available():
                        continue
                except Exception:  # noqa: BLE001
                    continue
            elif provider.requires_api_key:
                keys = getattr(provider, "api_key_envs", ()) or (
                    (provider.api_key_env,) if getattr(provider, "api_key_env", "") else ()
                )
                if keys and not any(get_secret(k) for k in keys):
                    continue
            return provider
        return None


_TRANSCRIPTION = _Registry("transcription", "speech.transcription.provider")
_SPEECH = _Registry("speech", "speech.speech.provider")


def register_transcription_provider(name: str, factory: Callable[[], TranscriptionProvider]) -> None:
    _TRANSCRIPTION.register(name, factory)


def unregister_transcription_provider(name: str) -> bool:
    return _TRANSCRIPTION.unregister(name)


def transcription_provider_names() -> list[str]:
    return _TRANSCRIPTION.names()


def get_transcription_provider() -> TranscriptionProvider | None:
    """The configured speech-to-text backend, or None when the machine has none."""
    return _TRANSCRIPTION.get()


def has_transcription_provider() -> bool:
    return get_transcription_provider() is not None


def register_speech_provider(name: str, factory: Callable[[], SpeechProvider]) -> None:
    _SPEECH.register(name, factory)


def unregister_speech_provider(name: str) -> bool:
    return _SPEECH.unregister(name)


def speech_provider_names() -> list[str]:
    return _SPEECH.names()


def get_speech_provider() -> SpeechProvider | None:
    """The configured text-to-speech backend, or None when the machine has none."""
    return _SPEECH.get()


def has_speech_provider() -> bool:
    return get_speech_provider() is not None


def reset_speech_registries() -> None:
    """Drop every registration. Called between tests by ``conftest._reset_process_state``."""
    _TRANSCRIPTION.clear()
    _SPEECH.clear()


# ── what the configuration says ─────────────────────────────────────────────────────────


def transcription_settings() -> dict[str, str]:
    """The configured model and language hint for transcription.

    Both are empty when the configuration named neither; a provider then uses its own default
    rather than being handed an empty string it has to interpret.
    """
    config = load_config()
    return {
        "model": str(get_path(config, "speech.transcription.model", "") or ""),
        "language": str(get_path(config, "speech.transcription.language", "") or ""),
    }


def speech_settings() -> dict[str, str]:
    """The configured voice and model for speaking, empty when the configuration named none."""
    config = load_config()
    return {
        "voice": str(get_path(config, "speech.speech.voice", "") or ""),
        "model": str(get_path(config, "speech.speech.model", "") or ""),
    }


def speech_limits() -> dict[str, float]:
    """The ceilings one voice message is held to.

    ``max_seconds`` and ``max_bytes`` bound an inbound recording before it is sent anywhere for
    transcription; ``max_chars`` bounds the text one reply may speak. Zero means no ceiling.
    """
    config = load_config()
    return {
        "max_seconds": float(get_path(config, "speech.max_seconds", 300) or 0),
        "max_bytes": float(get_path(config, "speech.max_bytes", 10_000_000) or 0),
        "max_chars": float(get_path(config, "speech.max_chars", 4000) or 0),
    }


def speaks_on(platform: str) -> bool:
    """Whether this platform's answer to a voice message should come back as audio."""
    configured = get_path(load_config(), "speech.reply_with_voice", []) or []
    return platform in {str(name) for name in configured}


# ── how long a recording is ─────────────────────────────────────────────────────────────


def audio_seconds(path: Path) -> float | None:
    """How long the audio at ``path`` plays, or None when its container does not say.

    Nothing is decoded: the duration comes from the file's own header, so reading it costs one
    seek. Only the containers a chat platform actually hands over are read -- WAV and Ogg Opus
    (what Telegram sends) -- and anything else is left to the size ceiling rather than guessed
    at, because a wrong duration would refuse a recording the user is allowed to send.
    """
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return None
    if magic == b"RIFF":
        return _wav_seconds(path)
    if magic == b"OggS":
        return _opus_seconds(path)
    return None


def _wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            return handle.getnframes() / rate if rate else None
    except (wave.Error, OSError, EOFError):
        return None


#: Opus counts its granule clock at 48 kHz whatever the sample rate on the wire.
_OPUS_GRANULE_HZ = 48_000
_NO_GRANULE = (1 << 64) - 1
_OGG_TAIL_BYTES = 64 * 1024


def _opus_seconds(path: Path) -> float | None:
    """Duration from the last Ogg page's granule position, for Opus only.

    Ogg carries any codec, and the granule clock of the others is not fixed, so a stream that
    does not identify itself as Opus is left alone. Pages are read from the end, and a claim to
    be one has to hold up: the segment table must describe exactly the bytes up to the end it is
    read from, which a stray ``OggS`` inside compressed audio cannot do. The last pages of a
    stream can carry no completed packet and then say ``2**64 - 1``; those are skipped for the
    one before them.
    """
    try:
        with path.open("rb") as handle:
            if b"OpusHead" not in handle.read(64):
                return None
            size = handle.seek(0, os.SEEK_END)
            window = min(size, _OGG_TAIL_BYTES)
            handle.seek(size - window)
            tail = handle.read(window)
    except OSError:
        return None
    end = len(tail)
    for _ in range(4):  # a stream should not end with more than a page or two of padding
        page = _page_ending_at(tail, end)
        if page is None:
            return None
        granule, start = page
        if granule != _NO_GRANULE:
            return granule / _OPUS_GRANULE_HZ if granule else None
        end = start
    return None


def _page_ending_at(tail: bytes, end: int) -> tuple[int, int] | None:
    """The granule position and start offset of the Ogg page that ends exactly at ``end``."""
    search = end
    while True:
        index = tail.rfind(b"OggS", 0, search)
        if index < 0 or index + 27 > end:
            return None
        search = index  # if this candidate is not a page, the next one is before it
        if tail[index + 4] != 0:  # the version byte of every Ogg page is 0
            continue
        segments = tail[index + 26]
        table = index + 27
        if table + segments > end:
            continue
        if table + segments + sum(tail[table : table + segments]) != end:
            continue
        return int.from_bytes(tail[index + 6 : index + 14], "little"), index
