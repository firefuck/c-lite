"""Session keys: which conversation a message belongs to.

A direct message thread is one session per chat. A group is one session per chat and thread,
and by default per user as well, so two people talking to the agent in the same group do not
share (and trample) one context.

The mapping from key to stored session id is persisted, so a gateway restart continues every
conversation where it left off.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from clite.core.constants import get_home
from clite.core.io import atomic_write_json, read_json
from clite.gateway.event import CHAT_DM, SessionSource
from clite.runtime.home_channel import HomeChannels


def build_session_key(source: SessionSource, *, group_sessions_per_user: bool = True) -> str:
    if source.chat_type == CHAT_DM:
        return f"{source.platform}:dm:{source.chat_id}"
    parts = [source.platform, source.chat_type, source.chat_id]
    if source.thread_id:
        parts.append(f"thread:{source.thread_id}")
    if group_sessions_per_user and source.user_id:
        parts.append(f"user:{source.user_id}")
    return ":".join(parts)


class SessionMap:
    """``session key -> stored session id``, in ``<home>/gateway/sessions.json``."""

    def __init__(self) -> None:
        self.path = get_home() / "gateway" / "sessions.json"
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        data = read_json(self.path, {})
        return data if isinstance(data, dict) else {}

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._load().get(key)
        return entry.get("session_id") if isinstance(entry, dict) else None

    def get_entry(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._load().get(key)
        return entry if isinstance(entry, dict) else None

    def set(
        self, key: str, session_id: str, source: SessionSource, *, last_activity: float | None = None
    ) -> None:
        with self._lock:
            data = self._load()
            act = last_activity if last_activity is not None else time.time()
            data[key] = {
                "session_id": session_id,
                "source": source.to_dict(),
                "last_activity": act,
            }
            atomic_write_json(self.path, data)

    def update_activity(self, key: str, timestamp: float | None = None) -> None:
        with self._lock:
            data = self._load()
            entry = data.get(key)
            if isinstance(entry, dict):
                entry["last_activity"] = timestamp if timestamp is not None else time.time()
                atomic_write_json(self.path, data)

    def reset(self, key: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(key, None) is not None:
                atomic_write_json(self.path, data)


__all__ = ["HomeChannels", "SessionMap", "build_session_key"]
