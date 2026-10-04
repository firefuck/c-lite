"""Atomic file writes. A crash mid-write must never leave a half-written state file."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | Path, text: str, *, mode: int | None = None) -> None:
    """Write ``text`` to ``path`` through a temp file in the same directory and ``os.replace``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: str | Path, data: Any, *, indent: int | None = 2) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n")


def read_json(path: str | Path, default: Any = None) -> Any:
    """Parsed JSON, or ``default`` when the file is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default
