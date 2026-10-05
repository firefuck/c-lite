"""Iteration budget: how many model calls one turn may make."""

from __future__ import annotations

import threading


class IterationBudget:
    """Thread-safe counter. ``limit=None`` means unlimited (the default).

    A parent and its subagents each get their own budget; a child cannot spend the parent's.
    """

    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit if limit and limit > 0 else None
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Take one iteration. False when the budget is spent."""
        with self._lock:
            if self.limit is not None and self._used >= self.limit:
                return False
            self._used += 1
            return True

    def refund(self) -> None:
        """Give one back: an iteration that never reached the model does not count."""
        with self._lock:
            self._used = max(0, self._used - 1)

    def reset(self) -> None:
        with self._lock:
            self._used = 0

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self._used)
