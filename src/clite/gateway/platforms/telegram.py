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
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.redact import redact
from clite.core.threads import start_thread
from clite.gateway.controls import APPROVAL_PREFIX, CALLBACK_PREFIXES
from clite.gateway.event import CHAT_CHANNEL, CHAT_DM, CHAT_GROUP, MessageEvent, SendResult, SessionSource
from clite.gateway.media import AUDIO, DOCUMENT, IMAGE, VIDEO, Attachment, MediaError
from clite.gateway.platforms.base import BasePlatformAdapter, register_platform

logger = logging.getLogger("clite.gateway.telegram")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
DEFAULT_BASE_URL = "https://api.telegram.org"
POLL_TIMEOUT_SECONDS = 25
TELEGRAM_MAX_BOT_COMMANDS = 100
TELEGRAM_MAX_COMMAND_NAME_LENGTH = 32
TELEGRAM_MAX_COMMAND_DESCRIPTION_LENGTH = 256
_TELEGRAM_COMMAND_NAME = re.compile(r"[a-z0-9_]{1,32}$")
_MDV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#\+\-=|{}.!\\\\])")
_CHAT_TYPES = {"private": CHAT_DM, "group": CHAT_GROUP, "supergroup": CHAT_GROUP, "channel": CHAT_CHANNEL}


def _escape_markdown_v2(text: str) -> str:
    """Escape text outside Telegram MarkdownV2 entities."""
    return _MDV2_ESCAPE_RE.sub(r"\\\1", text)


def format_telegram_markdown(text: str) -> str:
    """Render ordinary model Markdown as safe Telegram MarkdownV2.

    Telegram recognizes quote blocks only through MarkdownV2's leading ``>`` syntax.  Stashing
    constructs before escaping keeps arbitrary prose parseable while preserving code and links.
    """
    if not text:
        return text

    placeholders: dict[str, str] = {}

    def stash(value: str) -> str:
        key = f"\x00P{len(placeholders)}X\x00"
        placeholders[key] = value
        return key

    def inline(value: str, opener: str, closer: str) -> str:
        return stash(f"{opener}{_escape_markdown_v2(value)}{closer}")

    def fenced(match: re.Match[str]) -> str:
        opening, body, closing = match.group(1), match.group(2), match.group(3)
        safe_body = body.replace("\\", "\\\\").replace("`", "\\`")
        return stash(f"{opening}{safe_body}{closing}")

    # MarkdownV2 permits only backslash and backtick escaping inside code blocks/spans.
    rendered = re.sub(r"(?ms)^(```[^`\n]*\n)(.*?)(^[ \t]*```)[ \t]*$", fenced, text)

    def code_span(match: re.Match[str]) -> str:
        code = match.group(1).replace("\\", "\\\\")
        return stash(f"`{code}`")

    rendered = re.sub(r"`([^`\n]+)`", code_span, rendered)

    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        safe_url = url.replace("\\", "\\\\").replace(")", "\\)")
        return stash(f"[{_escape_markdown_v2(label)}]({safe_url})")

    rendered = re.sub(r"\[([^\]]+)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)", link, rendered)
    rendered = re.sub(
        r"^#{1,6}\s+(.+)$",
        lambda match: inline(match.group(1).strip(), "*", "*"),
        rendered,
        flags=re.MULTILINE,
    )
    rendered = re.sub(r"\*\*(.+?)\*\*", lambda match: inline(match.group(1), "*", "*"), rendered)
    rendered = re.sub(r"\*([^*\n]+)\*", lambda match: inline(match.group(1), "_", "_"), rendered)
    rendered = re.sub(r"~~(.+?)~~", lambda match: inline(match.group(1), "~", "~"), rendered)
    rendered = re.sub(r"\|\|(.+?)\|\|", lambda match: inline(match.group(1), "||", "||"), rendered)

    # A leading unescaped > is Telegram's documented native blockquote syntax.  Every quote
    # line is preserved, so consecutive Markdown quote lines become one multiline quote block.
    rendered = re.sub(
        r"^> ?(.*)$",
        lambda match: stash(f"> {_escape_markdown_v2(match.group(1))}"),
        rendered,
        flags=re.MULTILINE,
    )
    rendered = _escape_markdown_v2(rendered)
    for key, value in reversed(tuple(placeholders.items())):
        rendered = rendered.replace(key, value)
    return rendered


def _is_markdown_parse_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "parse" in message or "entity" in message or "markdown" in message


def telegram_command_menu() -> list[dict[str, str]]:
    """Telegram-safe rows for the gateway slash commands declared in the shared registry."""
    from clite.runtime.commands import commands_for

    menu: list[dict[str, str]] = []
    seen: set[str] = set()

    for command in commands_for("telegram"):
        names_to_register = [command.name]
        for alias in command.aliases:
            if alias not in names_to_register:
                names_to_register.append(alias)
        description = " ".join(command.description.split())
        if not description:
            logger.warning("Telegram command menu skipped %r because its description is empty", command.name)
            continue
        for name in names_to_register:
            name_lower = name.lower()
            if name_lower in seen:
                continue
            if not _TELEGRAM_COMMAND_NAME.fullmatch(name_lower):
                logger.warning("Telegram command menu skipped unsupported command name %r", name)
                continue
            seen.add(name_lower)
            menu.append(
                {
                    "command": name_lower,
                    "description": description[:TELEGRAM_MAX_COMMAND_DESCRIPTION_LENGTH],
                }
            )
            if len(menu) == TELEGRAM_MAX_BOT_COMMANDS:
                return menu
    return menu


register_secret(
    SecretSpec(
        TOKEN_ENV,
        "Telegram bot token from @BotFather",
        category="messaging",
        url="https://core.telegram.org/bots#how-do-i-create-a-bot",
    )
)


class TelegramAdapter(BasePlatformAdapter):
    name = "telegram"
    max_message_length = 4096
    max_button_label_bytes = 64  # Bot API limit on inline keyboard button text

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
        try:
            request = urllib.request.Request(  # noqa: S310 - the scheme comes from configuration
                f"{self.base_url}/bot{self.token}/{method}",
                data=json.dumps(payload or {}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the Bot API base URL from config
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except ValueError:
                body = {"ok": False, "description": f"HTTP {exc.code}"}
        except (OSError, ValueError) as exc:
            # The request URL carries the token; some network errors quote it back.
            raise RuntimeError(f"Telegram {method} failed: {redact(str(exc))}") from None
        if not body.get("ok"):
            raise RuntimeError(
                f"Telegram {method} failed: {redact(str(body.get('description', 'unknown error')))}"
            )
        return body.get("result")

    def connect(self) -> None:
        if not self.token:
            raise RuntimeError(f"{TOKEN_ENV} is not set; add it to .env")
        self.bot_username = str(self._call("getMe").get("username") or "")
        self._register_command_menu()
        self._stop.clear()
        self._thread = start_thread(self._poll, name="clite-telegram")

    def _register_command_menu(self) -> None:
        """Publish selectable slash commands without allowing a cosmetic API failure to block chat."""
        try:
            self._call("setMyCommands", {"commands": telegram_command_menu()}, timeout=15)
        except Exception as exc:  # noqa: BLE001 - command menu registration is optional UX
            logger.warning("Telegram command menu registration failed: %s", redact(str(exc)))

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_timeout + 5)

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                updates = self._call(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": self.poll_timeout,
                        "allowed_updates": ["message", "callback_query"],
                    },
                    timeout=self.poll_timeout + 10,
                )
            except Exception as exc:  # noqa: BLE001 - keep polling through network trouble
                logger.warning("Telegram polling failed: %s", redact(str(exc)))
                self._stop.wait(5)
                continue
            for update in updates or []:
                self._offset = max(self._offset, int(update["update_id"]) + 1)
                if self._handle_callback(update):
                    continue
                event = self.to_event(update)
                if event is not None:
                    self.handle_message(event)

    def _handle_callback(self, update: dict[str, Any]) -> bool:
        """Translate an inline control callback; its policy stays in the runner."""
        callback = update.get("callback_query")
        if not isinstance(callback, dict):
            return False
        data = str(callback.get("data") or "")
        if not data.startswith(CALLBACK_PREFIXES):
            self.answer_callback(str(callback.get("id") or ""), "Unsupported action.")
            return True
        message = callback.get("message") or {}
        chat, sender = message.get("chat") or {}, callback.get("from") or {}
        if not chat or not sender:
            self.answer_callback(str(callback.get("id") or ""), "Invalid model selection.")
            return True
        thread = message.get("message_thread_id")
        source = SessionSource(
            platform=self.name,
            chat_id=str(chat.get("id", "")),
            user_id=str(sender.get("id", "")),
            user_name=" ".join(part for part in (sender.get("first_name"), sender.get("last_name")) if part)
            or str(sender.get("username") or ""),
            chat_type=_CHAT_TYPES.get(str(chat.get("type") or ""), CHAT_GROUP),
            thread_id=str(thread) if thread else None,
            chat_name=str(chat.get("title") or ""),
        )
        callback_id = str(callback.get("id") or "")
        message_id = str(message.get("message_id") or "")
        if data.startswith(f"{APPROVAL_PREFIX}:"):
            self.runner.handle_approval_callback(source, callback_id, data, message_id)
        else:
            self.runner.handle_model_picker_callback(source, callback_id, data, message_id)
        return True

    def to_event(self, update: dict[str, Any]) -> MessageEvent | None:
        """A Bot API update as a ``MessageEvent``; ``None`` for updates that carry no text or file."""
        message = update.get("message") or {}
        text = message.get("text") or message.get("caption") or ""
        chat, sender = message.get("chat") or {}, message.get("from") or {}
        if not chat or sender.get("is_bot"):
            return None
        attachments = self._attachments(message)
        if not text and not attachments:
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
            replied_to_bot = ((message.get("reply_to_message") or {}).get("from") or {}).get(
                "username"
            ) == self.bot_username
            if mention and mention in text:
                text = text.replace(mention, "").strip()
            elif not (self.bot_username and replied_to_bot):
                return None  # ordinary group chatter is not for the agent
        name = " ".join(
            part for part in (sender.get("first_name"), sender.get("last_name")) if part
        ) or sender.get("username", "")
        thread = message.get("message_thread_id")
        source = SessionSource(
            platform=self.name,
            chat_id=str(chat["id"]),
            user_id=str(sender.get("id", "")),
            user_name=name,
            chat_type=chat_type,
            thread_id=str(thread) if thread else None,
            chat_name=chat.get("title") or "",
        )
        return MessageEvent(
            text=text,
            source=source,
            message_id=str(message.get("message_id", "")),
            reply_to=str(message.get("message_id", "")) or None,
            attachments=attachments,
            raw=update,
        )

    def _attachments(self, message: dict[str, Any]) -> list[Attachment]:
        """Files on a message, as attachments the runner can fetch and store.

        Telegram sends several sizes of a photo; the largest is taken. ``file_id`` is what
        ``fetch_attachment`` turns into bytes, and the declared ``file_size`` lets the runner
        refuse an oversized file before downloading it.
        """
        found: list[Attachment] = []
        photos = message.get("photo") or []
        if photos:
            largest = max(photos, key=lambda size: int(size.get("file_size") or size.get("width") or 0))
            found.append(
                Attachment(
                    kind=IMAGE,
                    name="photo.jpg",
                    size=int(largest.get("file_size") or -1),
                    file_id=str(largest.get("file_id") or ""),
                )
            )
        document = message.get("document")
        if document:
            found.append(
                Attachment(
                    kind=DOCUMENT,
                    name=str(document.get("file_name") or "document"),
                    size=int(document.get("file_size") or -1),
                    file_id=str(document.get("file_id") or ""),
                )
            )
        for key, kind, name in (("voice", AUDIO, "voice.ogg"), ("audio", AUDIO, ""), ("video", VIDEO, "")):
            entry = message.get(key)
            if entry:
                found.append(
                    Attachment(
                        kind=kind,
                        name=str(entry.get("file_name") or name or f"{key}.bin"),
                        size=int(entry.get("file_size") or -1),
                        file_id=str(entry.get("file_id") or ""),
                    )
                )
        return found

    def fetch_attachment(self, attachment: Attachment, *, max_bytes: int) -> bytes:
        """Download one file by ``file_id``. The size is refused before the bytes are pulled."""
        if attachment.data is not None:
            return attachment.data
        if attachment.size >= 0 and attachment.size > max_bytes:
            raise MediaError(f"{attachment.describe()} is larger than the {max_bytes} byte limit")
        if not attachment.file_id:
            raise MediaError(f"{attachment.describe()} has no file id to download")
        info = self._call("getFile", {"file_id": attachment.file_id}, timeout=30)
        file_path = str((info or {}).get("file_path") or "")
        if not file_path:
            raise MediaError(f"Telegram did not return a path for {attachment.describe()}")
        request = urllib.request.Request(f"{self.base_url}/file/bot{self.token}/{file_path}")  # noqa: S310 - the Bot API base URL from config
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - the request built above
                data: bytes = response.read(max_bytes + 1)
        except Exception as exc:  # a failed download is reported, not raised raw
            raise MediaError(f"could not download {attachment.describe()}: {exc}") from exc
        if len(data) > max_bytes:
            raise MediaError(f"{attachment.describe()} is larger than the {max_bytes} byte limit")
        return data

    def send_file(
        self, chat_id: str, path: str, *, caption: str = "", thread_id: str | None = None
    ) -> SendResult:
        """Upload a file with ``sendDocument`` over multipart/form-data."""
        from pathlib import Path

        target = Path(path)
        if not target.is_file():
            return SendResult(False, error=f"no file at {target}")
        boundary = f"----clite{time.time_ns():x}"
        body = bytearray()

        def field(name: str, value: str) -> None:
            body.extend(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )

        field("chat_id", str(chat_id))
        if caption:
            field("caption", caption[:1024])
        if thread_id:
            field("message_thread_id", str(thread_id))
        body.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{target.name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        body.extend(target.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        request = urllib.request.Request(  # noqa: S310 - the scheme comes from configuration
            f"{self.base_url}/bot{self.token}/sendDocument",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - the Bot API base URL from config
                payload = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001 - a failed upload is reported, not raised
            return SendResult(False, error=redact(str(exc)))
        result = payload.get("result") or {}
        return SendResult(True, message_id=str(result.get("message_id", "")))

    def send(
        self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None
    ) -> SendResult:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": format_telegram_markdown(text),
            "parse_mode": "MarkdownV2",
        }
        if reply_to:
            payload["reply_parameters"] = {"message_id": int(reply_to)}
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        try:
            result = self._call("sendMessage", payload)
        except Exception as exc:  # noqa: BLE001 - a failed send is reported, not raised
            if not _is_markdown_parse_error(exc):
                return SendResult(False, error=str(exc))
            # Formatting must never make a reply disappear. Preserve the original text if Telegram
            # rejects an edge case its MarkdownV2 parser does not accept.
            payload.pop("parse_mode")
            payload["text"] = text
            try:
                result = self._call("sendMessage", payload)
            except Exception as fallback_exc:  # noqa: BLE001 - a failed send is reported, not raised
                return SendResult(False, error=str(fallback_exc))
        return SendResult(True, message_id=str(result.get("message_id", "")))

    def can_send_buttons(self) -> bool:
        return True

    def send_model_picker(
        self, chat_id: str, text: str, keyboard: list[list[dict[str, str]]], *, thread_id: str | None = None
    ) -> SendResult:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        try:
            result = self._call("sendMessage", payload)
        except Exception as exc:  # noqa: BLE001 - a failed send is reported, not raised
            return SendResult(False, error=str(exc))
        return SendResult(True, message_id=str(result.get("message_id", "")))

    def edit_model_picker(
        self, chat_id: str, message_id: str, text: str, keyboard: list[list[dict[str, str]]]
    ) -> bool:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id) if message_id.isdigit() else message_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        try:
            self._call("editMessageText", payload, timeout=15)
            return True
        except Exception as exc:  # noqa: BLE001 - a failed edit is cosmetic; the caller sends anew
            logger.debug("telegram model picker edit failed for %s: %s", message_id, exc)
            return False

    def send_approval_prompt(
        self, chat_id: str, text: str, keyboard: list[list[dict[str, str]]], *, thread_id: str | None = None
    ) -> SendResult:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        try:
            result = self._call("sendMessage", payload)
        except Exception as exc:  # noqa: BLE001 - a failed send is reported, not raised
            return SendResult(False, error=str(exc))
        return SendResult(True, message_id=str(result.get("message_id", "")))

    def edit_approval_prompt(
        self, chat_id: str, message_id: str, text: str, keyboard: list[list[dict[str, str]]]
    ) -> bool:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id) if message_id.isdigit() else message_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        try:
            self._call("editMessageText", payload, timeout=15)
            return True
        except Exception as exc:  # noqa: BLE001 - a failed edit is cosmetic; the caller sends anew
            logger.debug("telegram approval prompt edit failed for %s: %s", message_id, exc)
            return False

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        if not callback_id:
            return
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text[:200]
        try:
            self._call("answerCallbackQuery", payload, timeout=10)
        except Exception:  # acknowledging a callback is cosmetic
            logger.debug("telegram callback answer failed", exc_info=True)

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        try:
            self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
        except Exception:  # noqa: BLE001 - cosmetic
            pass

    def can_edit(self) -> bool:
        return True

    def edit(self, chat_id: str, message_id: str, text: str) -> bool:
        """Rewrite a sent message. Telegram rejects edits that change nothing, so an identical
        body counts as success; a rate limit answers ``False`` and the answer is sent whole."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id) if str(message_id).isdigit() else message_id,
            "text": format_telegram_markdown(text),
            "parse_mode": "MarkdownV2",
        }
        try:
            self._call("editMessageText", payload, timeout=15)
            return True
        except Exception as exc:  # noqa: BLE001 - a rejected edit is not a failed turn
            if "message is not modified" in str(exc):
                return True
            if _is_markdown_parse_error(exc):
                payload.pop("parse_mode")
                payload["text"] = text
                try:
                    self._call("editMessageText", payload, timeout=15)
                    return True
                except Exception as fallback_exc:  # noqa: BLE001 - a failed edit is cosmetic; the caller sends anew
                    logger.debug("telegram plain-text edit failed for %s: %s", message_id, fallback_exc)
                    return False
            logger.debug("telegram edit failed for %s: %s", message_id, exc)
            return False


register_platform("telegram", TelegramAdapter)
