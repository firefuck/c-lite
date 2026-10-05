"""Telegram, over the Bot API with long polling. Standard library only.

Configuration (``config.yaml``)::

    gateway:
      platforms:
        telegram:
          enabled: true
          allowed_users: [123456789]     # Telegram user ids; others go through pairing

The bot token is read from ``TELEGRAM_BOT_TOKEN`` in ``.env``. ``base_url`` can point the
adapter at a self-hosted Bot API server (and is how the tests run it against a fake one).
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.threads import start_thread
from clite.gateway.event import CHAT_CHANNEL, CHAT_DM, CHAT_GROUP, MessageEvent, SendResult, SessionSource
from clite.gateway.platforms.base import BasePlatformAdapter, register_platform

logger = logging.getLogger("clite.gateway.telegram")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
DEFAULT_BASE_URL = "https://api.telegram.org"
POLL_TIMEOUT_SECONDS = 25
_CHAT_TYPES = {"private": CHAT_DM, "group": CHAT_GROUP, "supergroup": CHAT_GROUP, "channel": CHAT_CHANNEL}

register_secret(SecretSpec(TOKEN_ENV, "Telegram bot token from @BotFather", category="messaging",
                           url="https://core.telegram.org/bots#how-do-i-create-a-bot"))


class TelegramAdapter(BasePlatformAdapter):
    name = "telegram"
    max_message_length = 4096

    def __init__(self, config: dict[str, Any], runner: Any) -> None:
        super().__init__(config, runner)
        self.token = get_secret(TOKEN_ENV) or ""
        self.base_url = str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.poll_timeout = int(config.get("poll_timeout", POLL_TIMEOUT_SECONDS))
        self.bot_username = ""
        self._offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _call(self, method: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        request = urllib.request.Request(  # noqa: S310 - the scheme comes from configuration
            f"{self.base_url}/bot{self.token}/{method}", data=json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except ValueError:
                body = {"ok": False, "description": f"HTTP {exc.code}"}
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description', 'unknown error')}")
        return body.get("result")

    def connect(self) -> None:
        if not self.token:
            raise RuntimeError(f"{TOKEN_ENV} is not set; add it to .env")
        self.bot_username = str(self._call("getMe").get("username") or "")
        self._stop.clear()
        self._thread = start_thread(self._poll, name="clite-telegram")

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_timeout + 5)

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                updates = self._call("getUpdates", {"offset": self._offset, "timeout": self.poll_timeout,
                                                   "allowed_updates": ["message"]}, timeout=self.poll_timeout + 10)
            except Exception as exc:  # noqa: BLE001 - keep polling through network trouble
                logger.warning("Telegram polling failed: %s", exc)
                self._stop.wait(5)
                continue
            for update in updates or []:
                self._offset = max(self._offset, int(update["update_id"]) + 1)
                event = self.to_event(update)
                if event is not None:
                    self.handle_message(event)

    def to_event(self, update: dict[str, Any]) -> MessageEvent | None:
        """A Bot API update as a ``MessageEvent``; ``None`` for updates that carry no text."""
        message = update.get("message") or {}
        text = message.get("text") or message.get("caption") or ""
        chat, sender = message.get("chat") or {}, message.get("from") or {}
        if not text or not chat or sender.get("is_bot"):
            return None
        chat_type = _CHAT_TYPES.get(str(chat.get("type") or ""), CHAT_GROUP)
        if text.startswith("/"):
            command, _, rest = text.partition(" ")
            name, _, target = command.partition("@")
            if target and self.bot_username and target != self.bot_username:
                return None  # a command addressed to another bot
            text = f"{name} {rest}".strip()
        elif chat_type != CHAT_DM:
            mention = f"@{self.bot_username}" if self.bot_username else ""
            replied_to_bot = ((message.get("reply_to_message") or {}).get("from") or {}).get("username") == self.bot_username
            if mention and mention in text:
                text = text.replace(mention, "").strip()
            elif not (self.bot_username and replied_to_bot):
                return None  # ordinary group chatter is not for the agent
        name = " ".join(part for part in (sender.get("first_name"), sender.get("last_name")) if part) or sender.get("username", "")
        thread = message.get("message_thread_id")
        source = SessionSource(platform=self.name, chat_id=str(chat["id"]), user_id=str(sender.get("id", "")), user_name=name,
                               chat_type=chat_type, thread_id=str(thread) if thread else None, chat_name=chat.get("title") or "")
        return MessageEvent(text=text, source=source, message_id=str(message.get("message_id", "")), raw=update)

    def send(self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None) -> SendResult:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to:
            payload["reply_parameters"] = {"message_id": int(reply_to)}
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        try:
            result = self._call("sendMessage", payload)
        except Exception as exc:  # noqa: BLE001
            return SendResult(False, error=str(exc))
        return SendResult(True, message_id=str(result.get("message_id", "")))

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        try:
            self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
        except Exception:  # noqa: BLE001 - cosmetic
            pass


register_platform("telegram", TelegramAdapter)
