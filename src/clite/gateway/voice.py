"""Voice in a chat: the words in a voice message, and a spoken copy of the answer to one.

The providers come from ``tools/speech.py``. Neither direction can fail a turn: a voice message
that cannot be transcribed becomes a note to the model, and a spoken answer that cannot be made
or sent is dropped, since the text answer is already in the chat.
"""

from __future__ import annotations

import logging
import time

from clite.gateway import media
from clite.gateway.event import SessionSource
from clite.gateway.platforms.base import BasePlatformAdapter
from clite.tools import speech

logger = logging.getLogger("clite.gateway")


def transcribe(attachment: media.Attachment, stored: media.StoredFile) -> tuple[str, str]:
    """The words in one voice message, or the note explaining why there are none.

    Nothing here fails the turn. Without a provider, over the length or size ceiling, or
    with a provider that errors, the model still gets the file and the user is told what
    happened -- a voice message that ends in silence is worse than one that ends in text.
    """
    limits = speech.speech_limits()
    try:
        size = stored.path.stat().st_size
    except OSError as exc:
        return "", f"{attachment.describe()} could not be read back: {exc}"
    # A recording this large is not worth paying a transcription API for. Only a
    # ``speech.max_bytes`` set below ``attachments.max_bytes`` can bite: the larger file is
    # already refused, and the user told so, before it ever reaches this point.
    if limits["max_bytes"] and size > limits["max_bytes"]:
        return "", (
            f"{attachment.describe()} is larger than the "
            f"{limits['max_bytes']:,.0f} byte limit for transcription, so it was not "
            f"transcribed; it is saved at {stored.path}."
        )
    seconds = speech.audio_seconds(stored.path)
    if limits["max_seconds"] and seconds is not None and seconds > limits["max_seconds"]:
        return "", (
            f"The user sent a voice message of {seconds:.0f} seconds, longer than the "
            f"{limits['max_seconds']:.0f} second limit, so it was not transcribed; it is "
            f"saved at {stored.path}."
        )
    provider = speech.get_transcription_provider()
    if provider is None:
        return "", (
            f"The user attached {attachment.describe()}, saved at {stored.path}. "
            "No speech-to-text provider is configured, so it was not transcribed; read it "
            "with the file tools if it is relevant."
        )
    settings = speech.transcription_settings()
    try:
        # A provider that answers anything but a string is as broken as one that raises, and
        # the turn has to survive both the same way.
        words = provider.transcribe(
            stored.path, model=settings["model"], language=settings["language"]
        ).strip()
    except Exception as exc:  # a broken provider is reported, not fatal
        logger.warning("transcription failed for %s", stored.path, exc_info=True)
        return "", (
            f"The user's voice message could not be transcribed "
            f"({type(exc).__name__}: {exc}); it is saved at {stored.path}."
        )
    if not words:
        return "", (
            f"The user's voice message held no speech that could be transcribed; it is "
            f"saved at {stored.path}."
        )
    return words, ""


def speak_reply(
    source: SessionSource,
    session_key: str,
    adapter: BasePlatformAdapter | None,
    text: str,
    *,
    voice: bool,
) -> None:
    """Answer a voice message with a voice message, on the platforms that asked for that.

    The text answer is already in the chat, so this is a second, listenable copy, and nothing
    depends on it: no provider, no policy for this platform, an answer too long to speak, or a
    provider that fails all leave the turn exactly as it was. A long answer is left as text
    rather than spoken in part, because half an answer read aloud is worse than one read.
    """
    if not voice or adapter is None or not text.strip():
        return
    if not speech.speaks_on(source.platform):
        return
    provider = speech.get_speech_provider()
    if provider is None:
        return
    max_chars = speech.speech_limits()["max_chars"]
    if max_chars and len(text) > max_chars:
        logger.info("session %s: a %d character answer is too long to speak", session_key, len(text))
        return
    settings = speech.speech_settings()
    directory = media.media_dir(session_key) / "spoken"
    target = directory / f"reply-{int(time.time() * 1000)}.{provider.output_format}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        provider.synthesize(text, target, voice=settings["voice"], model=settings["model"])
        sent = adapter.send_file(source.chat_id, str(target), thread_id=source.thread_id)
    except Exception:  # the text answer already landed; the voice copy is a bonus
        logger.warning("session %s: could not speak the reply", session_key, exc_info=True)
        try:  # a half-written file is worse than none, but failing to remove it is not a turn
            target.unlink()
        except OSError:
            pass
        return
    if not sent.success:
        # ``send_file`` reports a refusal rather than raising, so it is checked here too.
        logger.warning(
            "session %s: %s refused the spoken reply: %s",
            session_key,
            source.platform,
            sent.error or "no reason given",
        )
        try:
            target.unlink()
        except OSError:
            pass
