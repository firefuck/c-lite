"""Housekeeping a surface runs when it starts.

Maintenance never raises and never blocks a chat: every step is best effort. It runs at most
once per process and home, and steps that are expensive keep their own "last run" timestamp
in the database so several processes do not repeat the work.
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

logger = logging.getLogger("clite.runtime.maintenance")

AUTO_PRUNE_INTERVAL_SECONDS = 24 * 3600
LAST_AUTO_PRUNE_KEY = "last_auto_prune"

_DONE: set[str] = set()
_LOCK = threading.Lock()


def reset_maintenance_state() -> None:
    with _LOCK:
        _DONE.clear()


def auto_prune_sessions(config: dict[str, Any], *, keep: Iterable[str] = (), now: float | None = None) -> int | None:
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


def run_startup_maintenance(config: dict[str, Any] | None = None, *, keep_sessions: Iterable[str] = ()) -> None:
    """Run the housekeeping steps once for this process and home."""
    key = home_key()
    with _LOCK:
        if key in _DONE:
            return
        _DONE.add(key)
    try:
        auto_prune_sessions(config if config is not None else load_config(), keep=keep_sessions)
    except Exception:  # noqa: BLE001 - housekeeping must never stop a session from starting
        logger.warning("startup maintenance failed", exc_info=True)
