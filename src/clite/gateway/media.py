"""Chat attachments: bring them into the session's directory and check them before use.

An inbound file is untrusted: its name lies easily, and a platform will happily hand over
megabytes. So the size is checked before anything is written, the kind is decided from the file's
first bytes rather than its name, and everything lands under ``<home>/gateway/media/<session>``
where the session's teardown can remove it.

Nothing here talks to a chat platform: the adapter fetches the bytes (it knows its own API) and
this module stores and classifies them.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from clite.core.constants import ensure_dir, get_home

# The kinds a message can carry. ``other`` is anything the agent should be told about but that
# the model cannot look at directly.
IMAGE = "image"
DOCUMENT = "document"
AUDIO = "audio"
VIDEO = "video"
OTHER = "other"

# Magic bytes we trust over any file name: enough to tell an image from a document, which is the
# decision that changes what the model receives.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", IMAGE, ".png"),
    (b"\xff\xd8\xff", IMAGE, ".jpg"),
    (b"GIF87a", IMAGE, ".gif"),
    (b"GIF89a", IMAGE, ".gif"),
    (b"%PDF-", DOCUMENT, ".pdf"),
    (b"PK\x03\x04", DOCUMENT, ".zip"),
    (b"\x1f\x8b", DOCUMENT, ".gz"),
    (b"OggS", AUDIO, ".ogg"),
    (b"\x1aE\xdf\xa3", VIDEO, ".webm"),
)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_TEXT_SUFFIXES = (".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".py", ".log")


class MediaError(Exception):
    """A file could not be brought in: too large, empty, or unreadable."""


@dataclass
class Attachment:
    """One file attached to an inbound message.

    ``data`` is set by an in-process platform (the ``local`` adapter) so tests never need a
    network; a real adapter leaves it empty and fills ``url`` for the runner to fetch.
    """

    kind: str = DOCUMENT
    name: str = ""
    size: int = -1  # -1 when the platform does not say
    url: str = ""
    file_id: str = ""
    data: bytes | None = field(default=None, repr=False)

    def describe(self) -> str:
        """A one-line description for the model, without leaking a local path."""
        size = f"{self.size} bytes" if self.size >= 0 else "unknown size"
        return f"{self.kind}: {self.name or 'unnamed'} ({size})"


def media_dir(session_key: str) -> Path:
    """The directory that holds one session's inbound files."""
    safe = "".join(
        character if character.isalnum() or character in "-_." else "_" for character in session_key
    )
    return get_home() / "gateway" / "media" / (safe or "session")


def cleanup_media(session_key: str) -> None:
    """Remove a session's files. Called when the session is closed."""
    target = media_dir(session_key)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def classify(data: bytes, name: str = "") -> tuple[str, str]:
    """``(kind, extension)`` from the file's first bytes, falling back to the name's suffix."""
    for magic, kind, extension in _MAGIC:
        if data.startswith(magic):
            return kind, extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return IMAGE, ".webp"
    suffix = Path(name).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return IMAGE, suffix
    if suffix in _TEXT_SUFFIXES:
        return DOCUMENT, suffix
    if data[:1] in (b"\x7b", b"\x5b"):  # a JSON object or array
        return DOCUMENT, ".json"
    return OTHER, suffix or ".bin"


@dataclass
class StoredFile:
    """An attachment that landed on disk, with the kind decided from its bytes."""

    path: Path
    kind: str


def store(attachment: Attachment, session_key: str, *, max_bytes: int) -> StoredFile:
    """Write one attachment into the session's media directory and return its path and kind.

    The size is refused before anything is written, so an oversized file never lands on disk and
    is never loaded past the bytes the adapter already fetched.
    """
    data = attachment.data
    if data is None:
        raise MediaError(
            f"{attachment.describe()} has no bytes; the platform adapter must fetch it before storing"
        )
    if not data:
        raise MediaError(f"{attachment.describe()} is empty")
    if len(data) > max_bytes:
        raise MediaError(f"{attachment.describe()} is larger than the {max_bytes} byte limit")
    kind, extension = classify(data, attachment.name)
    directory = ensure_dir(media_dir(session_key))
    path = directory / f"attachment-{len(list(directory.iterdir())) + 1}{extension}"
    path.write_bytes(data)
    return StoredFile(path=path, kind=kind)
