"""Private writes restrict the temporary file before any secret bytes are written."""

import os

import pytest

from clite.core import io


def test_private_write_applies_permissions_before_writing(monkeypatch, tmp_path):
    seen = []
    original = io._restrict_private_file if hasattr(io, "_restrict_private_file") else None

    def restrict(path):
        seen.append(path)
        assert os.path.getsize(path) == 0
        if original:
            original(path)

    monkeypatch.setattr(io, "_restrict_private_file", restrict, raising=False)
    target = tmp_path / ".env"
    io.atomic_write_text(target, "TOKEN=test-only\n", mode=0o600)
    assert len(seen) == 1
    assert target.read_text() == "TOKEN=test-only\n"


def test_a_permission_failure_does_not_replace_or_leave_secret_bytes(monkeypatch, tmp_path):
    def refuse(path):
        raise OSError("permission setup failed")

    directory = tmp_path / "private"
    directory.mkdir()
    target = directory / ".env"
    target.write_text("old")
    monkeypatch.setattr(io, "_restrict_private_file", refuse, raising=False)
    with pytest.raises(OSError, match="permission setup failed"):
        io.atomic_write_text(target, "new-secret", mode=0o600)
    assert target.read_text() == "old"
    assert list(directory.iterdir()) == [target]
