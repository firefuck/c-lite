"""Housekeeping a surface runs when it starts.

Maintenance never raises and never blocks a chat: every step is best effort. It runs at most
once per process and home, and steps that are expensive keep their own "last run" timestamp
in the database so several processes do not repeat the work.

Three steps today: pruning old sessions (``sessions.auto_prune``), pruning the file-checkpoint
store that goes with them (see ``clite.runtime.maintenance.prune_checkpoints``), and the skill
curator, which archives agent-created skills nobody uses (``curator.*``).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

from clite.core.config import get_path, load_config
from clite.core.constants import home_key
from clite.state.db import get_session_db
from clite.tools.checkpoints import prune_checkpoints as _prune_checkpoint_store

logger = logging.getLogger("clite.runtime.maintenance")

AUTO_PRUNE_INTERVAL_SECONDS = 24 * 3600
LAST_AUTO_PRUNE_KEY = "last_auto_prune"
LAST_CURATOR_KEY = "last_curator_run"

_DONE: set[str] = set()
_LOCK = threading.Lock()


def reset_maintenance_state() -> None:
    with _LOCK:
        _DONE.clear()


def auto_prune_sessions(
    config: dict[str, Any], *, keep: Iterable[str] = (), now: float | None = None
) -> int | None:
    """Apply ``sessions.auto_prune``. Returns the number of sessions deleted, or ``None``
    when pruning is off or already ran within the last day."""
    if not get_path(config, "sessions.auto_prune", False):
        return None
    retention_days = float(get_path(config, "sessions.retention_days", 90) or 0)
    if retention_days <= 0:
        return None
    db = get_session_db()
    moment = time.time() if now is None else now
    last = float(db.get_meta(LAST_AUTO_PRUNE_KEY, "0") or 0)
    if moment - last < AUTO_PRUNE_INTERVAL_SECONDS:
        return None
    db.set_meta(LAST_AUTO_PRUNE_KEY, str(moment))  # claimed first, so a concurrent process skips
    deleted = db.prune_sessions(retention_days, keep=keep, now=moment)
    if deleted:
        logger.info("auto-prune removed %d session(s) older than %g days", deleted, retention_days)
    return deleted


def run_startup_maintenance(
    config: dict[str, Any] | None = None, *, keep_sessions: Iterable[str] = ()
) -> None:
    """Run the housekeeping steps once for this process and home."""
    key = home_key()
    with _LOCK:
        if key in _DONE:
            return
        _DONE.add(key)
    try:
        cfg = config if config is not None else load_config()
        auto_prune_sessions(cfg, keep=keep_sessions)
        prune_checkpoints(cfg)
        run_curator_maintenance(cfg)
    except Exception:  # noqa: BLE001 - housekeeping must never stop a session from starting
        logger.warning("startup maintenance failed", exc_info=True)


def _prune_curator_store(config: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Archive agent-created skills nobody uses. Archive only; nothing is ever deleted.

    Kept as its own function so the curator step can be exercised without touching config, and
    so a caller (a test) can stand in for the real archive pass.
    """
    stale_days = int(get_path(config, "curator.stale_days", 30) or 0)
    from clite.skills.curator import run_curator

    return run_curator(stale_days, dry_run=False, now=now)


def run_curator_maintenance(config: dict[str, Any], *, now: float | None = None) -> dict[str, Any] | None:
    """Run the curator at most once per ``curator.interval_hours``, like auto-prune.

    Returns the curator report, or ``None`` when the curator is off or already ran within the
    interval. The last-run timestamp lives in the database so several processes agree. Never
    raises: a broken curator is a logged note, not a failed session.
    """
    if not get_path(config, "curator.enabled", True):
        return None
    interval_seconds = float(get_path(config, "curator.interval_hours", 24 * 7) or 0) * 3600
    if interval_seconds <= 0:
        return None
    db = get_session_db()
    moment = time.time() if now is None else now
    try:
        last = float(db.get_meta(LAST_CURATOR_KEY, "0") or 0)
    except (TypeError, ValueError):
        last = 0.0
    if moment - last < interval_seconds:
        return None
    db.set_meta(LAST_CURATOR_KEY, str(moment))  # claimed first, so a concurrent process skips
    try:
        report = _prune_curator_store(config, now=moment)
    except Exception:  # noqa: BLE001 - the curator must never hold up a surface
        logger.warning("curator maintenance failed", exc_info=True)
        return None
    archived = report.get("archived") if isinstance(report, dict) else None
    if archived:
        logger.info("curator archived %d skill(s)", len(archived))
    return report if isinstance(report, dict) else None


def prune_checkpoints(config: dict[str, Any]) -> list[str]:
    """Drop checkpoint stores whose session is gone, and trim the rest by age and size.

    The session database is the source of truth: a store directory with no session row left
    (the session was pruned or deleted) is removed outright, and the surviving stores follow
    ``sessions.retention_days`` and ``checkpoints.max_bytes``. Best effort, like the rest of
    maintenance.
    """
    db = get_session_db()
    rows = db.list_sessions(limit=1_000_000, include_archived=True, include_children=True)
    alive = [row["id"] for row in rows]
    emptied = _prune_checkpoint_store(config, session_ids=alive)
    emptied += _prune_checkpoint_store(config)
    if emptied:
        logger.info("checkpoint pruning emptied %d store(s)", len(emptied))
    return emptied
