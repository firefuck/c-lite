"""The audit trail for a reachable server.

One line per event, appended to ``<home>/logs/audit.log``: who connected, which named token
they used, and which dangerous command a person approved from the dashboard. It never holds a
token value — only the name it belongs to — because a log that leaks a credential is worse
than no log.

Turned off with ``server.audit_log: false``. When it is off, nothing is written and the calls
are a no-op.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from clite.core.config import config_get
from clite.core.constants import ensure_dir, get_logs_dir

logger = logging.getLogger("clite.audit")

_LOCK = threading.Lock()


def audit_path() -> Path:
    return get_logs_dir() / "audit.log"


def _enabled() -> bool:
    try:
        return bool(config_get("server.audit_log", True))
    except Exception:  # noqa: BLE001 - a broken config must not break a connection
        return True


def audit(event: str, **fields: Any) -> None:
    """Append one audit line. Never raises: a failed audit write must not fail a request."""
    if not _enabled():
        return
    parts = [time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()), event]
    for key, value in fields.items():
        if value in (None, ""):
            continue
        text = str(value).replace("\n", " ").replace("\r", " ")
        parts.append(f"{key}={text}")
    line = " ".join(parts)
    try:
        with _LOCK:
            path = audit_path()
            ensure_dir(path.parent)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError as exc:
        logger.warning("could not write the audit log: %s", exc)
