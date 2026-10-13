"""Named session tokens for ``clite serve``, stored as hashes.

A token is shown once, when it is created, and never stored: the file keeps a SHA-256 digest,
so a copy of the home directory does not hand anyone a working credential. Each token has a
name (so it can be revoked without touching the others), an optional expiry, and a note of when
it was last used.

The one-off token in ``CLITE_SESSION_TOKEN`` is not in here. It is what a parent process hands
a child, and it lives only as long as that process; this file is for tokens a person creates to
let another device in, which outlive the server that made them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clite.core.constants import get_home
from clite.core.io import atomic_write_text

# Long enough that guessing is hopeless; the file only ever holds its hash.
TOKEN_BYTES = 32


class TokenError(ValueError):
    """A token name is unusable, or no token matches."""


def tokens_path() -> Path:
    return get_home() / "tokens.json"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenRecord:
    name: str
    digest: str
    created_at: float
    expires_at: float | None = None
    last_used_at: float | None = None

    def expired(self, now: float | None = None) -> bool:
        return self.expires_at is not None and self.expires_at <= (now if now is not None else time.time())

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used_at": self.last_used_at,
            "expired": self.expired(),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> TokenRecord:
        return cls(
            name=str(raw.get("name", "")),
            digest=str(raw.get("digest", "")),
            created_at=float(raw.get("created_at", 0.0)),
            expires_at=None if raw.get("expires_at") is None else float(raw["expires_at"]),
            last_used_at=None if raw.get("last_used_at") is None else float(raw["last_used_at"]),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "digest": self.digest,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used_at": self.last_used_at,
        }


class TokenStore:
    """The named tokens for one home. Safe to use from several threads."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else tokens_path()
        self._lock = threading.Lock()

    # ── reading ──────────────────────────────────────────────────────────────────────────

    def _load(self) -> list[TokenRecord]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        try:
            document = json.loads(text)
        except ValueError:
            return []
        records = document.get("tokens") if isinstance(document, dict) else None
        if not isinstance(records, list):
            return []
        return [TokenRecord.from_json(entry) for entry in records if isinstance(entry, dict)]

    def _save(self, records: list[TokenRecord]) -> None:
        atomic_write_text(
            self.path,
            json.dumps({"tokens": [record.to_json() for record in records]}, indent=2) + "\n",
            mode=0o600,
        )

    def list(self) -> list[TokenRecord]:
        with self._lock:
            return self._load()

    def get(self, name: str) -> TokenRecord | None:
        wanted = name.strip()
        return next((record for record in self.list() if record.name == wanted), None)

    # ── writing ──────────────────────────────────────────────────────────────────────────

    def create(
        self, name: str, *, ttl_days: float | None = None, now: float | None = None
    ) -> tuple[TokenRecord, str]:
        """Make a token and return ``(record, plaintext)``. The plaintext is not stored."""
        clean = _check_name(name)
        current = now if now is not None else time.time()
        with self._lock:
            records = self._load()
            if any(record.name == clean for record in records):
                raise TokenError(f"a token named {clean!r} already exists; revoke it first")
            secret = secrets.token_urlsafe(TOKEN_BYTES)
            record = TokenRecord(
                name=clean,
                digest=token_digest(secret),
                created_at=current,
                expires_at=None if ttl_days is None else current + float(ttl_days) * 86_400,
            )
            self._save([*records, record])
        return record, secret

    def revoke(self, name: str) -> bool:
        clean = name.strip()
        with self._lock:
            records = self._load()
            kept = [record for record in records if record.name != clean]
            if len(kept) == len(records):
                return False
            self._save(kept)
        return True

    def verify(self, token: str) -> TokenRecord | None:
        """The record a presented token belongs to, or None. Compares digests, not plaintext."""
        if not token:
            return None
        wanted = token_digest(token)
        match: TokenRecord | None = None
        # Every record is compared, in constant time, so timing says nothing about which name
        # (if any) the token belongs to.
        for record in self.list():
            if hmac.compare_digest(record.digest, wanted):
                match = record
        if match is None or match.expired():
            return None
        return match

    def touch(self, name: str, now: float | None = None) -> None:
        current = now if now is not None else time.time()
        with self._lock:
            records = self._load()
            updated = [
                TokenRecord(
                    name=record.name,
                    digest=record.digest,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                    last_used_at=current if record.name == name else record.last_used_at,
                )
                for record in records
            ]
            self._save(updated)


def _check_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise TokenError("a token needs a name")
    if len(clean) > 64:
        raise TokenError("a token name is at most 64 characters")
    if not all(character.isalnum() or character in "-_. " for character in clean):
        raise TokenError("a token name may hold letters, digits, spaces, dashes, dots and underscores")
    return clean


_STORES: dict[str, TokenStore] = {}
_STORES_LOCK = threading.Lock()


def get_token_store() -> TokenStore:
    """The token store for the active home (each profile has its own tokens)."""
    from clite.core.constants import home_key

    key = home_key()
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            store = _STORES[key] = TokenStore()
        return store


def reset_token_stores() -> None:
    with _STORES_LOCK:
        _STORES.clear()
