"""Attachment loading, the per-image and per-count ceilings, and how images enter content.

The messages here are built by hand (a data-URL part), so most of the file needs no image
library. The two downscaling tests skip when Pillow is absent, the way an optional extra
behaves elsewhere in the suite.
"""

from __future__ import annotations

import base64
from io import BytesIO

import pytest

from clite.agent.attachments import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_MESSAGE,
    AttachmentError,
    attachment_note,
    build_content,
    detect_media_type,
    has_images,
    image_part,
    image_parts,
    load_image,
    load_images,
)

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# ── detection and part building ────────────────────────────────────────────────────────────


def test_media_type_comes_from_the_leading_bytes_not_the_extension(tmp_path):
    path = _write(tmp_path, "mislabelled.txt", PNG_HEADER + b"rest")
    assert detect_media_type(path.read_bytes(), path) == "image/png"


def test_a_file_that_is_not_an_image_is_refused_by_name(tmp_path):
    path = _write(tmp_path, "notes.txt", b"just some text")
    with pytest.raises(AttachmentError) as caught:
        load_image(path)
    assert "does not look like an image" in str(caught.value)
    assert "notes.txt" in str(caught.value)


def test_a_missing_file_is_refused_with_the_path(tmp_path):
    with pytest.raises(AttachmentError) as caught:
        load_image(tmp_path / "nope.png")
    assert "no file at" in str(caught.value)


def test_an_image_becomes_a_data_url_part():
    part = image_part("image/png", b"abc")
    assert part == {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}


def test_a_small_image_is_attached_without_shrinking(tmp_path):
    data = PNG_HEADER + b"payload"
    path = _write(tmp_path, "small.png", data)
    part = load_image(path)
    url = part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == data


# ── content building and inspection ─────────────────────────────────────────────────────────


def test_content_is_the_plain_string_when_there_are_no_images():
    assert build_content("hello", []) == "hello"
    assert build_content("hello", None) == "hello"


def test_content_is_text_then_images_when_one_is_attached():
    part = image_part("image/png", b"x")
    content = build_content("what is this?", [part])
    assert content == [{"type": "text", "text": "what is this?"}, part]
    assert has_images(content) is True
    assert image_parts(content) == [part]


def test_content_holds_only_the_image_when_the_caption_is_empty():
    part = image_part("image/png", b"x")
    assert build_content("", [part]) == [part]


def test_the_note_names_how_many_images_were_withheld():
    assert "image was attached" in attachment_note(1)
    assert "3 images were attached" in attachment_note(3)


# ── the ceilings ────────────────────────────────────────────────────────────────────────────


def test_more_images_than_the_ceiling_are_refused_before_any_is_loaded(tmp_path):
    paths = [str(tmp_path / f"{index}.png") for index in range(MAX_IMAGES_PER_MESSAGE + 1)]
    with pytest.raises(AttachmentError) as caught:
        load_images(paths)
    assert f"at most {MAX_IMAGES_PER_MESSAGE} images" in str(caught.value)


def test_an_image_over_the_byte_ceiling_is_refused_when_it_cannot_be_shrunk(tmp_path, monkeypatch):
    # No Pillow in the downscaling helpers: `_fit` returns the input unchanged.
    import clite.agent.attachments as attachments

    monkeypatch.setattr(attachments, "_within_edge", lambda raw, edge: True)
    monkeypatch.setattr(attachments, "_fit", lambda raw, media_type, *, max_bytes, max_edge: (raw, False))
    path = _write(tmp_path, "big.png", PNG_HEADER + b"0" * (MAX_IMAGE_BYTES + 1))
    with pytest.raises(AttachmentError) as caught:
        load_image(path)
    assert "over the" in str(caught.value)


def test_the_byte_ceiling_is_the_configured_one(tmp_path, monkeypatch):
    import clite.agent.attachments as attachments

    monkeypatch.setattr(attachments, "_within_edge", lambda raw, edge: True)
    path = _write(tmp_path, "medium.png", PNG_HEADER + b"0" * 300)
    with pytest.raises(AttachmentError):
        load_image(path, max_bytes=100, max_edge=10_000)


def test_a_large_image_is_downscaled_within_the_ceiling(tmp_path):
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        pytest.skip("Pillow is not installed")
    buffer = BytesIO()
    # Noise defeats PNG compression, so the raw file is comfortably over the ceiling.
    import random

    rng = random.Random(0)
    noise = Image.new("RGB", (700, 700))
    noise.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(700 * 700)])
    noise.save(buffer, format="PNG")
    raw = buffer.getvalue()
    assert len(raw) > 200_000
    path = _write(tmp_path, "noisy.png", raw)

    part = load_image(path, max_bytes=200_000, max_edge=64)
    shrunk = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
    assert len(shrunk) <= 200_000
    with Image.open(BytesIO(shrunk)) as opened:
        assert max(opened.size) <= 64


def test_an_oversized_but_undecodable_image_is_refused_not_crashed(tmp_path):
    path = _write(tmp_path, "broken.png", PNG_HEADER + b"\x00" * 6_000_000)
    with pytest.raises(AttachmentError) as caught:
        load_image(path)
    assert "over the" in str(caught.value) or "does not look like" in str(caught.value)
