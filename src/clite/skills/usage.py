"""Skill usage sidecar: who created a skill and how often it is used.

Kept in ``<home>/skills/.usage.json``, outside every SKILL.md, so recording a view never
rewrites a skill file. The curator reads it to find agent-created skills nobody uses.
"""

from __future__ import annotations

import time
from typing import Any

from clite.core.constants import get_skills_dir
from clite.core.io import atomic_write_json, read_json


def _path():
    return get_skills_dir() / ".usage.json"


def load_usage() -> dict[str, dict[str, Any]]:
    data = read_json(_path(), {})
    return data if isinstance(data, dict) else {}


def _update(name: str, **fields: Any) -> None:
    usage = load_usage()
    entry = usage.setdefault(name, {"use_count": 0, "created_by": "user", "created_at": time.time(), "last_used_at": None})
    entry.update(fields)
    try:
        atomic_write_json(_path(), usage)
    except OSError:
        pass  # bookkeeping must never break a skill view


def record_created(name: str, origin: str) -> None:
    _update(name, created_by=origin, created_at=time.time())


def record_use(name: str) -> None:
    usage = load_usage()
    count = int((usage.get(name) or {}).get("use_count") or 0)
    _update(name, use_count=count + 1, last_used_at=time.time())
