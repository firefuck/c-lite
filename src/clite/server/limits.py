"""Limits that keep a reachable server from being an easy target.

Two things live here:

* :class:`TokenThrottle` counts wrong tokens per client address and slows that address down.
  The count is in memory on purpose: a restart forgets it, which is the honest trade for never
  writing failed attempts (and the addresses behind them) to disk.
* :func:`too_large` is the size cap for an incoming RPC line. The ASGI server refuses an
  oversized WebSocket frame before this ever runs (see ``ws_max_size`` in
  ``clite.server.run``); this is the second check, so the JSON parser never sees a huge string
  even if the frame limit is raised.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Ten wrong tokens from one address inside a minute is a person guessing, not a client that
# mistyped once. The delay grows with each further failure, up to a minute.
DEFAULT_MAX_FAILURES = 10
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_DELAY_SECONDS = 5.0
MAX_DELAY_SECONDS = 60.0


@dataclass
class _Attempts:
    failures: int = 0
    window_started: float = 0.0
    blocked_until: float = 0.0


class TokenThrottle:
    """Wrong-token accounting, per client address."""

    def __init__(
        self,
        *,
        max_failures: int = DEFAULT_MAX_FAILURES,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
    ) -> None:
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = max(1.0, float(window_seconds))
        self.delay_seconds = max(0.0, float(delay_seconds))
        self._lock = threading.Lock()
        self._attempts: dict[str, _Attempts] = {}

    def blocked_for(self, address: str, now: float | None = None) -> float:
        """Seconds this address must wait before its next attempt; 0.0 when it may try now."""
        current = now if now is not None else time.time()
        with self._lock:
            state = self._attempts.get(address)
            if state is None:
                return 0.0
            return max(0.0, state.blocked_until - current)

    def record_failure(self, address: str, now: float | None = None) -> float:
        """Count one wrong token and return how long this address is now held off for."""
        current = now if now is not None else time.time()
        with self._lock:
            state = self._attempts.get(address)
            if state is None or current - state.window_started > self.window_seconds:
                state = self._attempts[address] = _Attempts(window_started=current)
            state.failures += 1
            if state.failures < self.max_failures:
                return 0.0
            # Each failure past the threshold doubles the wait, up to a minute.
            over = state.failures - self.max_failures
            delay = min(self.delay_seconds * (2**over), MAX_DELAY_SECONDS)
            state.blocked_until = current + delay
            return delay

    def record_success(self, address: str) -> None:
        with self._lock:
            self._attempts.pop(address, None)

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()


def too_large(raw: str, limit: int) -> bool:
    """True when a received RPC line is over ``limit`` bytes."""
    if limit <= 0:
        return False
    return len(raw.encode("utf-8", errors="replace")) > limit


def client_address(connection: object) -> str:
    """The address a connection came from, or ``"unknown"`` when the transport hides it."""
    client = getattr(connection, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return str(host) if host else "unknown"
