"""Curator: keep the agent's own skill library from growing without bound.

Rules it never breaks:

* It only touches skills the agent created (``created_by: agent`` in the usage sidecar).
  Bundled skills and skills the user wrote or installed are never candidates.
* It archives; it never deletes. An archived skill moves to ``<home>/skills/.archive/`` and
  can be restored by moving it back.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from clite.core.constants import ensure_dir, get_skills_dir
from clite.skills.catalog import TIER_LOCAL, discover_skills, get_skill
from clite.skills.usage import load_usage

DEFAULT_STALE_DAYS = 30


def archive_dir() -> Path:
    return get_skills_dir() / ".archive"


def find_stale_skills(stale_days: int = DEFAULT_STALE_DAYS, now: float | None = None) -> list[dict[str, Any]]:
    """Agent-created local skills not used for ``stale_days``."""
    usage = load_usage()
    cutoff = (now or time.time()) - stale_days * 86400
    stale = []
    for skill in discover_skills(include_disabled=True, all_platforms=True):
        entry = usage.get(skill.name) or {}
        if skill.tier != TIER_LOCAL or entry.get("created_by") != "agent":
            continue
        last = entry.get("last_used_at") or entry.get("created_at") or 0
        if last < cutoff:
            stale.append({"name": skill.name, "last_used_at": entry.get("last_used_at"),
                          "use_count": entry.get("use_count", 0)})
    return stale


def archive_skill(name: str) -> Path:
    skill = get_skill(name)
    if skill is None or skill.tier != TIER_LOCAL:
        raise ValueError(f"{name!r} is not a local skill")
    destination = ensure_dir(archive_dir()) / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(skill.directory), str(destination))
    return destination


def restore_skill(archived_name: str) -> Path:
    source = archive_dir() / archived_name
    if not source.is_dir():
        raise ValueError(f"no archived skill named {archived_name!r}")
    name = archived_name.rsplit("-", 2)[0]
    destination = get_skills_dir() / name
    if destination.exists():
        raise ValueError(f"a skill named {name!r} already exists")
    shutil.move(str(source), str(destination))
    return destination


def run_curator(stale_days: int = DEFAULT_STALE_DAYS, *, dry_run: bool = True) -> dict[str, Any]:
    """Archive stale agent-created skills. ``dry_run`` (the default) only reports."""
    stale = find_stale_skills(stale_days)
    archived = []
    if not dry_run:
        for entry in stale:
            archived.append(str(archive_skill(entry["name"])))
    return {"stale": stale, "archived": archived, "dry_run": dry_run}
