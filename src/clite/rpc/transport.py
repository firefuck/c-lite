"""Transports: how JSON-RPC messages leave the server.

The server only ever calls ``write(obj)`` and ``close()``. Stdio (one JSON document per line)
and WebSocket (one per text frame) are the two shipped transports; a test uses the in-memory
one. A transport's ``write`` must be safe to call from any thread.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Protocol, TextIO


class Transport(Protocol):
    def write(self, message: dict[str, Any]) -> bool:
        """Send one message. Returns False when the peer is gone."""

    def close(self) -> None:
        ...


class StdioTransport:
    """Newline-delimited JSON on a text stream."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()
        self._closed = False

    def write(self, message: dict[str, Any]) -> bool:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
        with self._lock:
            if self._closed:
                return False
            try:
                self._stream.write(line + "\n")
                self._stream.flush()
                return True
            except (OSError, ValueError):
                self._closed = True
                return False

    def close(self) -> None:
        with self._lock:
            self._closed = True


class MemoryTransport:
    """Collects messages in a list; for tests and in-process embedding."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._condition = threading.Condition()
        self.closed = False

    def write(self, message: dict[str, Any]) -> bool:
        with self._condition:
            if self.closed:
                return False
            self.messages.append(json.loads(json.dumps(message, default=str)))  # what a real peer would receive
            self._condition.notify_all()
            return True

    def close(self) -> None:
        with self._condition:
            self.closed = True
            self._condition.notify_all()

    def wait_for(self, predicate, timeout: float = 5.0) -> dict[str, Any]:
        """The first message matching ``predicate``; raises ``TimeoutError`` if none arrives."""
        with self._condition:
            seen = 0
            deadline = threading.TIMEOUT_MAX if timeout is None else timeout
            import time

            end = time.monotonic() + deadline
            while True:
                for message in self.messages[seen:]:
                    if predicate(message):
                        return message
                seen = len(self.messages)
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no matching message; saw {[m.get('method') or m.get('id') for m in self.messages]}")
                self._condition.wait(remaining)

    def events(self, event_type: str | None = None) -> list[dict[str, Any]]:
        with self._condition:
            return [m["params"] for m in self.messages
                    if m.get("method") == "event" and (event_type is None or m["params"]["type"] == event_type)]


class WebSocketTransport:
    """Sends through an asyncio WebSocket from any thread."""

    def __init__(self, websocket: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._websocket = websocket
        self._loop = loop
        self._closed = False

    def write(self, message: dict[str, Any]) -> bool:
        if self._closed or self._loop.is_closed():
            return False
        text = json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
        try:
            asyncio.run_coroutine_threadsafe(self._send(text), self._loop)
            return True
        except RuntimeError:
            self._closed = True
            return False

    async def _send(self, text: str) -> None:
        try:
            await self._websocket.send_text(text)
        except Exception:  # noqa: BLE001 - the peer hung up
            self._closed = True

    def close(self) -> None:
        self._closed = True
