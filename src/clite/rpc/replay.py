"""What makes a reconnect cheap: the events a client missed, and the sessions that outlive it.

Two pieces:

* :class:`EventLog` numbers every event the server sends and keeps the last few per session. A
  client that reconnects says how far it got (``seq``) and gets exactly what came after. The
  numbering is process-wide, not per connection, because a client's "last seq" has to mean the
  same thing on the other side of a disconnect.
* :class:`DetachedSessions` holds the runtime sessions of a connection that went away, for a
  grace period, so a turn that was running keeps running and can be picked up again. Without it
  every dropped socket would kill the turn in progress.

The buffer is bounded twice: per session, and by the number of sessions remembered. A client
that fell further behind than that is told to reload history instead of being handed a stream
with a hole in it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger("clite.rpc.replay")

DEFAULT_PER_SESSION = 500
DEFAULT_SESSIONS = 64
DEFAULT_GRACE_SECONDS = 120.0
# Remembering "we dropped everything up to N" for every session that ever existed would grow
# without end; the oldest notes are the least likely to be asked about.
_DROPPED_NOTES = 256


class EventLog:
    """A bounded, per-session record of the events the server has sent."""

    def __init__(self, *, per_session: int = DEFAULT_PER_SESSION, sessions: int = DEFAULT_SESSIONS) -> None:
        self.per_session = max(1, int(per_session))
        self.sessions = max(1, int(sessions))
        # The same lock guards numbering, remembering and reading. `emit` and `session.attach`
        # both take it, so an event is never delivered live *and* reported as missed.
        self.lock = threading.RLock()
        self._seq = 0
        self._buffers: dict[str, deque[dict[str, Any]]] = {}
        self._dropped: dict[str, int] = {}

    @property
    def last_seq(self) -> int:
        with self.lock:
            return self._seq

    def next_seq(self) -> int:
        with self.lock:
            self._seq += 1
            return self._seq

    def remember(self, event: dict[str, Any]) -> None:
        """Keep ``event`` (an event's ``params``) for a later replay."""
        session_id = str(event.get("session_id") or "")
        if not session_id:
            return  # gateway.ready belongs to the connection, not to a conversation
        with self.lock:
            buffer = self._buffers.get(session_id)
            if buffer is None:
                if len(self._buffers) >= self.sessions:
                    self._evict_oldest()
                buffer = self._buffers[session_id] = deque()
            buffer.append(event)
            while len(buffer) > self.per_session:
                self._dropped[session_id] = int(buffer.popleft()["seq"])
            if len(self._dropped) > _DROPPED_NOTES:
                for stale in list(self._dropped)[: len(self._dropped) - _DROPPED_NOTES]:
                    self._dropped.pop(stale, None)

    def missed(self, session_id: str, last_seq: int) -> tuple[list[dict[str, Any]], bool]:
        """``(events after last_seq, complete)``. ``complete`` is False when there is a hole."""
        with self.lock:
            if last_seq >= self._seq:
                return [], True  # nothing has happened since; nothing to replay
            buffer = self._buffers.get(session_id)
            if buffer is None:
                return [], False  # never seen, or dropped entirely
            if last_seq < self._dropped.get(session_id, 0):
                return [], False  # what came next is no longer here
            return [event for event in buffer if int(event["seq"]) > last_seq], True

    def forget(self, session_id: str) -> None:
        with self.lock:
            self._buffers.pop(session_id, None)

    def reset(self) -> None:
        with self.lock:
            self._seq = 0
            self._buffers.clear()
            self._dropped.clear()

    def _evict_oldest(self) -> None:
        oldest = next(iter(self._buffers), None)
        if oldest is None:
            return
        buffer = self._buffers.pop(oldest)
        if buffer:
            self._dropped[oldest] = int(buffer[-1]["seq"])


class DetachedSessions:
    """Runtime sessions kept alive for a grace period after their connection went away."""

    def __init__(self, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> None:
        self.grace_seconds = max(0.0, float(grace_seconds))
        self._lock = threading.RLock()
        self._detached: dict[str, tuple[Any, float]] = {}
        self._stop = threading.Event()
        self._reaper: threading.Thread | None = None

    def detach(self, session: Any) -> bool:
        """Hold on to ``session``. False when there is no grace and it should close now."""
        if self.grace_seconds <= 0:
            return False
        with self._lock:
            self._detached[session.id] = (session, time.monotonic() + self.grace_seconds)
            self._ensure_reaper()
        return True

    def adopt(self, session_id: str) -> Any | None:
        """Take a session back, or None when it was never here or its grace ran out."""
        with self._lock:
            entry = self._detached.pop(session_id, None)
        if entry is None:
            return None
        session, deadline = entry
        if time.monotonic() >= deadline:
            _close_quietly(session)
            return None
        return session

    def reap(self, now: float | None = None) -> int:
        """Close whatever has waited past its grace. Returns how many."""
        current = now if now is not None else time.monotonic()
        with self._lock:
            expired = [
                session_id
                for session_id, (_session, deadline) in self._detached.items()
                if deadline <= current
            ]
            entries = [self._detached.pop(session_id) for session_id in expired]
        for session, _deadline in entries:
            _close_quietly(session)
        return len(entries)

    def count(self) -> int:
        with self._lock:
            return len(self._detached)

    def reset(self) -> None:
        with self._lock:
            self._stop.set()
            entries = list(self._detached.values())
            self._detached.clear()
        for session, _deadline in entries:
            _close_quietly(session)

    def _ensure_reaper(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return
        self._stop.clear()
        self._reaper = threading.Thread(target=self._reap_loop, name="clite-session-reaper", daemon=True)
        self._reaper.start()

    def _reap_loop(self) -> None:
        interval = max(0.5, min(self.grace_seconds / 4, 30.0))
        while not self._stop.wait(interval):
            try:
                self.reap()
            except Exception:  # a reaper that dies stops collecting sessions
                logger.exception("reaping detached sessions failed")


def _close_quietly(session: Any) -> None:
    try:
        session.close()
    except Exception:
        logger.debug("closing a detached session failed", exc_info=True)


_LOG = EventLog()
_DETACHED = DetachedSessions()


def get_event_log() -> EventLog:
    return _LOG


def get_detached_sessions() -> DetachedSessions:
    return _DETACHED


def configure(
    per_session: int | None = None, sessions: int | None = None, grace_seconds: float | None = None
) -> None:
    """Apply ``server.replay_*`` / ``server.resume_grace_seconds`` to the process-wide objects."""
    if per_session is not None:
        _LOG.per_session = max(1, int(per_session))
    if sessions is not None:
        _LOG.sessions = max(1, int(sessions))
    if grace_seconds is not None:
        _DETACHED.grace_seconds = max(0.0, float(grace_seconds))


def reset_replay_state() -> None:
    """Back to the defaults, and let go of every detached session (the test suite's hook)."""
    _LOG.reset()
    _LOG.per_session = DEFAULT_PER_SESSION
    _LOG.sessions = DEFAULT_SESSIONS
    _DETACHED.reset()
    _DETACHED.grace_seconds = DEFAULT_GRACE_SECONDS
