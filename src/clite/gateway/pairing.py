"""DM pairing: how an unknown user gets access without the owner editing config.

An unknown user who messages the bot receives a one-time code. The owner, on the machine
running the gateway, approves it with ``clite gateway pair approve <platform> <code>``. From
then on that user is allowed.

Abuse limits: a code expires after an hour, each user may request one per ten minutes, only a
few can be pending per platform, and five wrong approval attempts lock approvals for an hour.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from clite.core.constants import get_home
from clite.core.io import atomic_write_json, read_json

# No 0/O or 1/I/L: a code is read aloud or retyped by hand.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_SECONDS = 3600
REQUEST_INTERVAL_SECONDS = 600
MAX_PENDING_PER_PLATFORM = 3
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 3600


class PairingStore:
    def __init__(self) -> None:
        self.path = get_home() / "gateway" / "pairing.json"
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        data = read_json(self.path, {})
        if not isinstance(data, dict):
            data = {}
        for key in ("pending", "approved", "requests", "failures"):
            data.setdefault(key, {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        atomic_write_json(self.path, data)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def is_approved(self, platform: str, user_id: str) -> bool:
        with self._lock:
            return user_id in self._load()["approved"].get(platform, {})

    def request_code(self, platform: str, user_id: str, user_name: str = "", now: float | None = None) -> str | None:
        """A new code for this user, or ``None`` when the request is rate-limited."""
        current = time.time() if now is None else now
        with self._lock:
            data = self._load()
            pending = {code: entry for code, entry in data["pending"].get(platform, {}).items()
                       if entry["expires_at"] > current}
            last = data["requests"].get(f"{platform}:{user_id}", 0)
            if current - last < REQUEST_INTERVAL_SECONDS or len(pending) >= MAX_PENDING_PER_PLATFORM:
                data["pending"][platform] = pending
                self._save(data)
                return None
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            pending[code] = {"user_id": user_id, "user_name": user_name, "expires_at": current + CODE_TTL_SECONDS}
            data["pending"][platform] = pending
            data["requests"][f"{platform}:{user_id}"] = current
            self._save(data)
            return code

    def approve(self, platform: str, code: str, now: float | None = None) -> dict[str, Any] | None:
        """Approve the user holding ``code``. Returns the user, or ``None`` for a bad code."""
        current = time.time() if now is None else now
        normalized = code.strip().upper()
        with self._lock:
            data = self._load()
            failures = data["failures"].get(platform, {"count": 0, "locked_until": 0})
            if failures["locked_until"] > current:
                raise PermissionError("too many wrong codes; approvals for this platform are locked for an hour")
            entry = data["pending"].get(platform, {}).get(normalized)
            if entry is None or entry["expires_at"] <= current:
                failures["count"] += 1
                if failures["count"] >= MAX_FAILED_ATTEMPTS:
                    failures = {"count": 0, "locked_until": current + LOCKOUT_SECONDS}
                data["failures"][platform] = failures
                self._save(data)
                return None
            del data["pending"][platform][normalized]
            data["approved"].setdefault(platform, {})[entry["user_id"]] = {"user_name": entry["user_name"], "approved_at": current}
            data["failures"][platform] = {"count": 0, "locked_until": 0}
            self._save(data)
            return {"user_id": entry["user_id"], "user_name": entry["user_name"]}

    def revoke(self, platform: str, user_id: str) -> bool:
        with self._lock:
            data = self._load()
            removed = data["approved"].get(platform, {}).pop(user_id, None) is not None
            if removed:
                self._save(data)
            return removed

    def list(self, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        with self._lock:
            data = self._load()
        pending = {platform: {code: entry for code, entry in codes.items() if entry["expires_at"] > current}
                   for platform, codes in data["pending"].items()}
        return {"pending": pending, "approved": data["approved"]}
