"""Email gateway adapter using IMAP polling and SMTP from the standard library.

Configuration (``gateway.platforms.email``)::

    enabled: true
    imap_host: mail.example.com
    smtp_host: smtp.example.com
    from_address: bot@example.com
    allowed_users: [owner@example.com]

Passwords are read from ``EMAIL_IMAP_PASSWORD`` and ``EMAIL_SMTP_PASSWORD`` in ``.env``.
Inbound mail is polled from IMAP, and the ``References`` header identifies one gateway session
per email thread. Only configured ``allowed_users`` receive replies; email never uses pairing.
"""

from __future__ import annotations

import email
import imaplib
import logging
import smtplib
import ssl
import threading
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.threads import start_thread

logger = logging.getLogger("clite.plugin.email")

IMAP_PASSWORD_ENV = "EMAIL_IMAP_PASSWORD"
SMTP_PASSWORD_ENV = "EMAIL_SMTP_PASSWORD"
register_secret(SecretSpec(IMAP_PASSWORD_ENV, "Email IMAP password", category="messaging"))
register_secret(SecretSpec(SMTP_PASSWORD_ENV, "Email SMTP password", category="messaging"))


class EmailAdapter:
    """Translate IMAP messages to gateway events and SMTP replies without platform policy."""

    name = "email"
    max_message_length = 20_000

    def __init__(self, config: dict[str, Any], runner: Any, ctx: Any) -> None:
        self.config = config
        self.runner = runner
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def allowed_users(self) -> set[str]:
        return {str(user).casefold() for user in self.config.get("allowed_users") or []}

    def connect(self) -> None:
        if (
            not self.config.get("imap_host")
            or not self.config.get("smtp_host")
            or not self.config.get("from_address")
        ):
            raise RuntimeError("email requires imap_host, smtp_host, and from_address")
        if not get_secret(IMAP_PASSWORD_ENV):
            raise RuntimeError(f"{IMAP_PASSWORD_ENV} is not set; add it to .env")
        if not get_secret(SMTP_PASSWORD_ENV):
            raise RuntimeError(f"{SMTP_PASSWORD_ENV} is not set; add it to .env")
        self._stop.clear()
        self._thread = start_thread(self._poll, name="clite-email")

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=float(self.config.get("poll_interval", 30)) + 5)

    def _imap(self):
        host = str(self.config["imap_host"])
        port = int(self.config.get("imap_port") or (993 if self.config.get("imap_ssl", True) else 143))
        if self.config.get("imap_ssl", True):
            return imaplib.IMAP4_SSL(host, port)
        return imaplib.IMAP4(host, port)

    def _poll(self) -> None:
        interval = max(float(self.config.get("poll_interval", 30)), 0.01)
        while not self._stop.is_set():
            try:
                self._receive_once()
            except Exception as exc:  # noqa: BLE001 - a broken mail server must not kill the loop
                logger.warning("email polling failed: %s", exc)
            self._stop.wait(interval)

    def _receive_once(self) -> None:
        client = self._imap()
        try:
            client.login(
                str(self.config.get("imap_username") or self.config["from_address"]),
                get_secret(IMAP_PASSWORD_ENV) or "",
            )
            client.select(str(self.config.get("imap_mailbox") or "INBOX"))
            status, data = client.search(None, "UNSEEN")
            if status != "OK":
                return
            for number in (data[0] or b"").split():
                number_text = number.decode() if isinstance(number, bytes) else str(number)
                status, parts = client.fetch(number_text, "(RFC822)")
                if status != "OK":
                    continue
                raw = next(
                    (part[1] for part in parts if isinstance(part, tuple) and isinstance(part[1], bytes)),
                    None,
                )
                if raw is None:
                    continue
                event = self.to_event(raw)
                if event is not None:
                    self.handle_message(event)
                client.store(number_text, "+FLAGS", "\\Seen")
        finally:
            try:
                client.logout()
            except Exception:  # noqa: BLE001 - connection may already be gone
                pass

    def to_event(self, raw: bytes):
        """Make a MessageEvent lazily, keeping this bundled plugin on the public plugin API."""
        message = email.message_from_bytes(raw, policy=policy.default)
        sender_name, sender = parseaddr(message.get("From", ""))
        sender = sender.casefold()
        if not sender or sender not in self.allowed_users():
            return None
        text = _text_body(message)
        if not text:
            return None
        references = message.get("References", "").split()
        thread_id = (
            references[0] if references else message.get("In-Reply-To") or message.get("Message-ID") or ""
        )
        return self.ctx.gateway_message_event(
            text=text,
            source=self.ctx.gateway_session_source(
                platform=self.name,
                chat_id=sender,
                user_id=sender,
                user_name=sender_name or sender,
                chat_type="dm",
                thread_id=thread_id,
                chat_name=message.get("Subject", ""),
            ),
            message_id=message.get("Message-ID", ""),
            raw=raw,
        )

    def handle_message(self, event) -> None:
        self.runner.dispatch(event)

    def send(self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None):
        message = EmailMessage()
        message["From"] = str(self.config["from_address"])
        message["To"] = chat_id
        message["Subject"] = str(self.config.get("subject_prefix") or "C-lite reply")
        if reply_to:
            message["In-Reply-To"] = reply_to
        if thread_id:
            message["References"] = thread_id
        message.set_content(text)
        host = str(self.config["smtp_host"])
        port = int(self.config.get("smtp_port") or (465 if self.config.get("smtp_ssl") else 587))
        try:
            if self.config.get("smtp_ssl"):
                client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())
            else:
                client = smtplib.SMTP(host, port)
            with client:
                client.ehlo()
                if self.config.get("smtp_starttls", True):
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if self.config.get("smtp_auth", True):
                    client.login(
                        str(self.config.get("smtp_username") or self.config["from_address"]),
                        get_secret(SMTP_PASSWORD_ENV) or "",
                    )
                client.send_message(message)
        except Exception as exc:  # noqa: BLE001 - failures are reported to the runner, never raised
            return self.ctx.gateway_send_result(False, error=str(exc))
        return self.ctx.gateway_send_result(True, message_id=message.get("Message-ID", ""))

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        return None

    def can_edit(self) -> bool:
        return False


def _text_body(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_content_disposition():
                return part.get_content().strip()
        return ""
    if message.get_content_type() != "text/plain":
        return ""
    return message.get_content().strip()


def register(ctx) -> None:
    ctx.register_platform("email", lambda config, runner: EmailAdapter(config, runner, ctx))
