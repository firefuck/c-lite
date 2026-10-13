"""Images a user attaches to a message: load, validate, shrink, and place into content.

A user message stays a string when it carries no image. With one or more images its content
becomes a list of parts, the shape every transport already understands (``text`` and
``image_url``), so nothing downstream needs to know where the picture came from.

Two limits protect the model's context window and the session database: a per-image byte
ceiling and a per-message count ceiling. An image larger than the ceiling is downscaled in
memory when Pillow is installed (the ``images`` extra); without it the attachment is refused
with a message that says how to shrink the file, rather than sending a base64 blob that
would blow the context window.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clite.core.errors import CliteError

logger = logging.getLogger("clite.agent.attachments")

MAX_IMAGE_BYTES = 5_000_000  # about 6.7M base64 characters; a hard ceiling on one image
MAX_IMAGES_PER_MESSAGE = 8
# Downscale target: the longest edge in pixels. Models sample images well below this; a
# smaller edge cuts the payload without hurting legibility of ordinary screenshots.
MAX_IMAGE_EDGE = 1568
DEFAULT_MEDIA_TYPE = "image/png"

# Magic bytes to media type. The extension is a hint, never trusted on its own: a mislabelled
# file sent with the wrong media type is rejected by providers with an opaque error.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP; the WEBP tag is checked separately below
    (b"BM", "image/bmp"),
)
_EXTENSION_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@dataclass
class AttachmentError(CliteError):
    """An image could not be attached. ``message`` addresses the user, not the developer."""

    message: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def detect_media_type(data: bytes, path: Path) -> str | None:
    """The media type implied by the leading bytes, or ``None`` when it is not an image."""
    for magic, media_type in _MAGIC:
        if data.startswith(magic):
            if media_type == "image/webp" and data[8:12] != b"WEBP":
                continue
            return media_type
    return _EXTENSION_MEDIA.get(path.suffix.lower())


def image_part(media_type: str, data: bytes) -> dict[str, Any]:
    """One content part in the internal OpenAI-style shape, as base64 inline data."""
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}}


def load_image(
    path: str | Path, *, max_bytes: int = MAX_IMAGE_BYTES, max_edge: int = MAX_IMAGE_EDGE
) -> dict[str, Any]:
    """Read one image file into a content part, downscaling it when it is over the ceiling."""
    target = Path(path).expanduser()
    if not target.exists():
        raise AttachmentError(f"no file at {target}")
    if not target.is_file():
        raise AttachmentError(f"{target} is not a file")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise AttachmentError(f"cannot read {target}: {exc.strerror or exc}") from exc
    if not raw:
        raise AttachmentError(f"{target} is empty")
    media_type = detect_media_type(raw, target)
    if media_type is None:
        raise AttachmentError(
            f"{target} does not look like an image (PNG, JPEG, GIF, WebP or BMP); attach an image file"
        )
    data, resized = _fit(raw, media_type, max_bytes=max_bytes, max_edge=max_edge)
    if len(data) > max_bytes:
        raise AttachmentError(
            f"{target} is still {len(data):,} bytes after shrinking, over the {max_bytes:,}-byte "
            "limit; resize it yourself (e.g. `magick input.png -resize 1568x1568 output.png`)"
        )
    if resized:
        logger.info("attachment %s downscaled to %d bytes", target, len(data))
    return image_part(media_type, data)


def _fit(raw: bytes, media_type: str, *, max_bytes: int, max_edge: int) -> tuple[bytes, bool]:
    """``(data, resized)``: ``raw`` when it already fits, else a smaller re-encode.

    Returns the input unchanged when Pillow is not installed; the caller then rejects the
    attachment by size. Never raises for a file that Pillow cannot decode.
    """
    if len(raw) <= max_bytes and _within_edge(raw, max_edge):
        return raw, False
    try:
        from io import BytesIO

        from PIL import Image  # optional `images` extra
    except ImportError:
        return raw, False
    try:
        with Image.open(BytesIO(raw)) as opened:
            image = opened.convert("RGB") if opened.mode not in ("RGB", "RGBA", "L") else opened
            image.thumbnail((max_edge, max_edge))
            buffer = BytesIO()
            out_format = "JPEG" if media_type == "image/jpeg" else "PNG"
            image.save(buffer, format=out_format, optimize=True)
            return buffer.getvalue(), True
    except Exception:  # a decode failure is a refusal, not a crash
        logger.warning("could not downscale an image attachment", exc_info=True)
        return raw, False


def _within_edge(raw: bytes, max_edge: int) -> bool:
    """True when the image's pixel dimensions are unknown or already within ``max_edge``."""
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return True  # cannot tell; the byte ceiling still applies
    try:
        with Image.open(BytesIO(raw)) as opened:
            return max(opened.size) <= max_edge
    except Exception:  # noqa: BLE001
        return True


def load_images(
    paths: list[str],
    *,
    max_count: int = MAX_IMAGES_PER_MESSAGE,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_edge: int = MAX_IMAGE_EDGE,
) -> list[dict[str, Any]]:
    """Load every path, refusing the whole set when it is over ``max_count``."""
    if len(paths) > max_count:
        raise AttachmentError(f"at most {max_count} images per message; {len(paths)} were given")
    return [load_image(path, max_bytes=max_bytes, max_edge=max_edge) for path in paths]


def build_content(text: str, images: list[dict[str, Any]] | None) -> Any:
    """The user message content: the plain string, or text followed by the image parts."""
    if not images:
        return text
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    parts.extend(images)
    return parts


def image_parts(content: Any) -> list[dict[str, Any]]:
    """Every ``image_url`` part of a message's content, in order."""
    if not isinstance(content, list):
        return []
    return [part for part in content if isinstance(part, dict) and part.get("type") == "image_url"]


def has_images(content: Any) -> bool:
    return bool(image_parts(content))


def attachment_note(count: int) -> str:
    """A line telling a model without vision that images were attached and are not visible."""
    noun = "image was" if count == 1 else f"{count} images were"
    return (
        f"[{noun} attached to this message, but the current model cannot see images; only the text is shown.]"
    )
