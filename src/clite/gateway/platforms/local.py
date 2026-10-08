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
        self.edits: list[dict[str, Any]] = []
        self.files: list[dict[str, Any]] = []
        self.fail_edits = False  # a test sets this to simulate a platform edit rate limit
        self.typing: list[str] = []
        self.connected = False
        self._condition = threading.Condition()

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def send(
        self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None
    ) -> SendResult:
        if not self.connected:
            return SendResult(False, error="not connected")
        with self._condition:
            message_id = str(len(self.outbox) + 1)
            self.outbox.append(
                {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "text": text,
                    "reply_to": reply_to,
                    "thread_id": thread_id,
                }
            )
            self._condition.notify_all()
            return SendResult(True, message_id=message_id)

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        self.typing.append(chat_id)

    # ── editing (streaming answers) ───────────────────────────────────────────────────────

    def can_edit(self) -> bool:
        return True

    def edit(self, chat_id: str, message_id: str, text: str) -> bool:
        """Rewrite a sent message in place, recording the edit. ``fail_edits`` simulates a
        platform rate limit so the fallback path is testable."""
        if self.fail_edits:
            return False
        with self._condition:
            for message in self.outbox:
                if str(message["message_id"]) == str(message_id):
                    message["text"] = text
                    self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text})
                    self._condition.notify_all()
                    return True
        return False

    # ── test and demo helpers ────────────────────────────────────────────────────────────

    def inject(
        self,
        text: str,
        *,
        user_id: str = "user-1",
        chat_id: str | None = None,
        chat_type: str = CHAT_DM,
        thread_id: str | None = None,
        user_name: str = "Test User",
        attachments: list[Any] | None = None,
    ) -> None:
        source = SessionSource(
            platform=self.name,
            chat_id=chat_id or user_id,
            user_id=user_id,
            user_name=user_name,
            chat_type=chat_type,
            thread_id=thread_id,
        )
        self.handle_message(
            MessageEvent(
                text=text,
                source=source,
                message_id=str(time.time_ns()),
                attachments=list(attachments or []),
            )
        )

    def send_file(
        self, chat_id: str, path: str, *, caption: str = "", thread_id: str | None = None
    ) -> SendResult:
        """Record an outgoing file. The bytes are not read here; the test asserts on the path."""
        if not self.connected:
            return SendResult(False, error="not connected")
        with self._condition:
            self.files.append({"chat_id": chat_id, "path": path, "caption": caption})
            self._condition.notify_all()
            return SendResult(True, message_id=f"file-{len(self.files)}")

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

    def wait_for_text(self, needle: str, timeout: float = 5.0) -> None:
        """Block until some sent message contains ``needle``.

        A streamed answer arrives in pieces and is edited into place, so a test that asserts on
        the final text has to wait for the edit rather than read the outbox the moment the first
        chunk lands. This also wakes on an edit, not only on a new message.
        """
        deadline = time.monotonic() + timeout
        with self._condition:
            while not any(needle in message["text"] for message in self.outbox):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"no message containing {needle!r}; got {[m['text'] for m in self.outbox]}"
                    )
                self._condition.wait(remaining)


register_platform("local", LocalAdapter)
