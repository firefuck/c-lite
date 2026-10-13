"""What a message's attachments become in a turn: image parts, transcripts, or notes on saved files.

``media.py`` stores and classifies one file; this module decides, per file, what the model gets.
It fetches through the adapter when the platform delivered only a reference, and tells the user
about a file it refused rather than dropping it in silence.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from clite.core.config import get_path
from clite.gateway import media
from clite.gateway.event import MessageEvent, SessionSource
from clite.gateway.media import MediaError
from clite.gateway.media import store as media_store
from clite.gateway.platforms.base import BasePlatformAdapter
from clite.gateway.voice import transcribe

logger = logging.getLogger("clite.gateway")


def collect_attachments(
    event: MessageEvent,
    session_key: str,
    *,
    adapter: BasePlatformAdapter | None,
    config: dict[str, Any],
    reply: Callable[[SessionSource, str], None],
) -> tuple[list[str], str, str]:
    """Store the message's files and say what the model gets.

    An image becomes a content part; a voice message becomes the words the transcription
    provider heard; anything else is announced as a path the model can read with its file
    tools. A file over the size limit is refused with a message to the user -- it is never
    written, so nothing large lands on disk.

    Returns the stored image paths, the notes for the model, and the transcripts.
    """
    if not event.attachments:
        return [], "", ""
    max_bytes = int(get_path(config, "attachments.max_bytes", 5_000_000) or 5_000_000)
    images: list[str] = []
    notes: list[str] = []
    spoken: list[str] = []
    for attachment in event.attachments:
        try:
            if attachment.data is None:
                fetch = getattr(adapter, "fetch_attachment", None)
                if fetch is None:
                    raise MediaError(
                        f"{attachment.describe()} cannot be downloaded by the {event.source.platform} adapter"
                    )
                attachment.data = fetch(attachment, max_bytes=max_bytes)
            stored = media_store(attachment, session_key, max_bytes=max_bytes)
        except MediaError as exc:
            reply(event.source, f"I could not take that file: {exc}")
            continue
        if stored.kind == media.IMAGE:
            images.append(str(stored.path))
        elif stored.kind == media.AUDIO:
            words, note = transcribe(attachment, stored)
            if words:
                spoken.append(words)
            else:
                notes.append(note)
        else:
            notes.append(
                f"The user attached {attachment.describe()}, saved at {stored.path}. "
                "Read it with the file tools if it is relevant."
            )
    logger.info(
        "session %s took %d attachment(s): %d image(s), %d voice note(s)",
        session_key,
        len(event.attachments),
        len(images),
        len(spoken),
    )
    return images, "\n".join(notes), "\n\n".join(spoken)
