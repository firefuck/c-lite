"""Credential pool: several keys for one provider, rotated when one is exhausted.

Keys come from ``.env``. For a provider whose variable is ``OPENROUTER_API_KEY``, the pool
also picks up ``OPENROUTER_API_KEY_2``, ``OPENROUTER_API_KEY_3`` and so on. A key that hits a
rate limit or a billing error is benched for a cooldown, and the next one takes over.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from clite.core.constants import home_key
from clite.core.env import get_secret

MAX_NUMBERED_KEYS = 9
DEFAULT_COOLDOWN_SECONDS = 300.0


@dataclass(frozen=True)
class Credential:
    name: str  # the environment variable it came from
    value: str


class CredentialPool:
    def __init__(self, provider: str, env_vars: tuple[str, ...]) -> None:
        self.provider = provider
        self.env_vars = env_vars
        self._lock = threading.Lock()
        self._benched: dict[str, float] = {}  # variable name -> monotonic time it is usable again

    def candidates(self) -> list[Credential]:
        found: list[Credential] = []
        for base in self.env_vars:
            for name in (base, *(f"{base}_{n}" for n in range(2, MAX_NUMBERED_KEYS + 1))):
                value = get_secret(name)
                if value and all(value != existing.value for existing in found):
                    found.append(Credential(name, value))
        return found

    def current(self) -> Credential | None:
        """The first key that is not benched; if all are benched, the one free soonest."""
        candidates = self.candidates()
        if not candidates:
            return None
        now = time.monotonic()
        with self._lock:
            for credential in candidates:
                if self._benched.get(credential.name, 0.0) <= now:
                    return credential
            return min(candidates, key=lambda credential: self._benched.get(credential.name, 0.0))

    def mark_exhausted(self, credential: Credential, cooldown: float = DEFAULT_COOLDOWN_SECONDS) -> None:
        with self._lock:
            self._benched[credential.name] = time.monotonic() + cooldown

    def rotate(self, exhausted: Credential, cooldown: float = DEFAULT_COOLDOWN_SECONDS) -> Credential | None:
        """Bench ``exhausted`` and return a different usable key, or ``None`` if there is none."""
        self.mark_exhausted(exhausted, cooldown)
        now = time.monotonic()
        with self._lock:
            for credential in self.candidates():
                if credential.name != exhausted.name and self._benched.get(credential.name, 0.0) <= now:
                    return credential
        return None


_POOLS: dict[tuple[str, str], CredentialPool] = {}
_POOLS_LOCK = threading.Lock()


def get_credential_pool(provider: str, env_vars: tuple[str, ...]) -> CredentialPool:
    key = (home_key(), provider)
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is None or pool.env_vars != env_vars:
            pool = _POOLS[key] = CredentialPool(provider, env_vars)
        return pool


def reset_credential_pools() -> None:
    with _POOLS_LOCK:
        _POOLS.clear()
