"""File logging under ``<home>/logs``: ``agent.log`` (INFO+) and ``errors.log`` (WARNING+).

Logs go to files, never to stdout. On the stdio RPC transport stdout IS the wire, and one
stray line corrupts the protocol.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from clite.core.brand import APP_NAME
from clite.core.constants import ensure_dir, get_logs_dir, home_key

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured_for: str | None = None


def setup_logging(
    level: str | None = None,
    *,
    max_size_mb: int = 5,
    backup_count: int = 3,
    stderr: bool = False,
) -> None:
    """Attach rotating file handlers for the active home. Safe to call repeatedly."""
    global _configured_for
    logs_dir = get_logs_dir()
    key = home_key(logs_dir)
    root = logging.getLogger(APP_NAME)
    if _configured_for == key:
        if level:
            root.setLevel(_coerce_level(level))
        return
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(_coerce_level(level))
    root.propagate = False
    try:
        ensure_dir(logs_dir)
        size = max(1, int(max_size_mb)) * 1024 * 1024
        formatter = logging.Formatter(_FORMAT)
        for filename, threshold in (("agent.log", logging.INFO), ("errors.log", logging.WARNING)):
            handler = RotatingFileHandler(
                logs_dir / filename, maxBytes=size, backupCount=backup_count, encoding="utf-8"
            )
            handler.setLevel(threshold)
            handler.setFormatter(formatter)
            root.addHandler(handler)
    except OSError:
        # A read-only home must not stop the agent from running; fall back to stderr.
        stderr = True
    if stderr:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    _configured_for = key


def reset_logging() -> None:
    """Detach every handler (tests switch homes between cases)."""
    global _configured_for
    root = logging.getLogger(APP_NAME)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    _configured_for = None


def _coerce_level(level: str | None) -> int:
    resolved = logging.getLevelName(str(level or "INFO").upper())
    return resolved if isinstance(resolved, int) else logging.INFO
