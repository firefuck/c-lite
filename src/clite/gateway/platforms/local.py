"""An in-process platform: messages go in through ``inject`` and replies land in ``outbox``.

It is how the gateway is tested and demonstrated without any chat service, and a minimal
example of an adapter: everything a real one needs is here, minus the network.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from clite.gateway.event import CHAT_DM, MessageEvent, SendResult, SessionSource
from clite.gateway.platforms.base import BasePlatformAdapter, register_platform


class LocalAdapter(BasePlatformAdapter):
    name = "local"
    max_message_length = 2000

    def __init__(self, config: dict[str, Any], runner: Any) -> None:
        super().__init__(config, runner)
        self.outbox: list[dict[str, Any]] = []
        self.typing: list[str] = []
        self.connected = False
        self._condition = threading.Condition()

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def send(self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None) -> SendResult:
        if not self.connected:
            return SendResult(False, error="not connected")
        with self._condition:
            self.outbox.append({"chat_id": chat_id, "text": text, "reply_to": reply_to, "thread_id": thread_id})
            self._condition.notify_all()
            return SendResult(True, message_id=str(len(self.outbox)))

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        self.typing.append(chat_id)

    # ── test and demo helpers ────────────────────────────────────────────────────────────

    def inject(self, text: str, *, user_id: str = "user-1", chat_id: str | None = None, chat_type: str = CHAT_DM,
               thread_id: str | None = None, user_name: str = "Test User") -> None:
        source = SessionSource(platform=self.name, chat_id=chat_id or user_id, user_id=user_id, user_name=user_name,
                               chat_type=chat_type, thread_id=thread_id)
        self.handle_message(MessageEvent(text=text, source=source, message_id=str(time.time_ns())))

    def wait_for_messages(self, count: int, timeout: float = 5.0) -> list[str]:
        """Block until ``count`` messages have been sent; return all their texts."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self.outbox) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"expected {count} messages, got {[m['text'] for m in self.outbox]}")
                self._condition.wait(remaining)
            return [message["text"] for message in self.outbox]


register_platform("local", LocalAdapter)
