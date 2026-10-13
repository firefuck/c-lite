"""WhatsApp Cloud API gateway adapter using an incoming webhook.

Configuration (``gateway.platforms.whatsapp``)::

    enabled: true
    allowed_users: ["15550001111"]
    # base_url: https://graph.facebook.com  # optional for a local protocol fake

``WHATSAPP_ACCESS_TOKEN``, ``WHATSAPP_APP_SECRET``, and ``WHATSAPP_VERIFY_TOKEN`` are read
from ``.env``. Configure the WhatsApp application webhook URL to the server route registered
by the surrounding application, then send subscription verification and signed POST bodies to
:meth:`WhatsAppAdapter.handle_webhook_verification` and
:meth:`WhatsAppAdapter.handle_webhook`. Only text messages from ``allowed_users`` become
Gateway events. The adapter sends text replies through the official Graph API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.request
from typing import Any

from clite.core.env import SecretSpec, get_secret, register_secret

logger = logging.getLogger("clite.plugin.whatsapp")

ACCESS_TOKEN_ENV = "WHATSAPP_ACCESS_TOKEN"
APP_SECRET_ENV = "WHATSAPP_APP_SECRET"
VERIFY_TOKEN_ENV = "WHATSAPP_VERIFY_TOKEN"
DEFAULT_BASE_URL = "https://graph.facebook.com"
API_VERSION = "v21.0"
for _secret in (
    SecretSpec(ACCESS_TOKEN_ENV, "WhatsApp Cloud API access token", category="messaging"),
    SecretSpec(APP_SECRET_ENV, "WhatsApp Cloud API app secret", category="messaging"),
    SecretSpec(VERIFY_TOKEN_ENV, "WhatsApp Cloud API webhook verify token", category="messaging"),
):
    register_secret(_secret)


class WhatsAppAdapter:
    """Translate verified WhatsApp webhooks to gateway events and send text replies."""

    name = "whatsapp"
    max_message_length = 4096

    def __init__(self, config: dict[str, Any], runner: Any, ctx: Any) -> None:
        self.config = config
        self.runner = runner
        self.ctx = ctx
        self.access_token = get_secret(ACCESS_TOKEN_ENV) or ""
        self.app_secret = get_secret(APP_SECRET_ENV) or ""
        self.verify_token = get_secret(VERIFY_TOKEN_ENV) or ""
        self.base_url = str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")

    def connect(self) -> None:
        if not self.access_token:
            raise RuntimeError(f"{ACCESS_TOKEN_ENV} is not set; add it to .env")
        if not self.app_secret:
            raise RuntimeError(f"{APP_SECRET_ENV} is not set; add it to .env")
        if not self.verify_token:
            raise RuntimeError(f"{VERIFY_TOKEN_ENV} is not set; add it to .env")

    def disconnect(self) -> None:
        return None

    def allowed_users(self) -> set[str]:
        return {str(user) for user in self.config.get("allowed_users") or []}

    def handle_webhook_verification(self, query: dict[str, str]) -> str | None:
        """Return Meta's challenge only for this adapter's configured verification token."""
        if query.get("hub.mode") == "subscribe" and hmac.compare_digest(
            query.get("hub.verify_token", ""), self.verify_token
        ):
            return query.get("hub.challenge", "")
        return None

    def handle_webhook(self, raw: bytes, signature: str) -> bool:
        """Verify and translate a Cloud API POST body without letting invalid data reach runner."""
        expected = "sha256=" + hmac.new(self.app_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
            return False
        for message in self._messages(payload):
            event = self.to_event(message)
            if event is not None:
                try:
                    self.handle_message(event)
                except Exception:  # noqa: BLE001 - a single webhook message must not reject the batch
                    logger.exception("WhatsApp message dispatch failed")
        return True

    @staticmethod
    def _messages(payload: dict[str, Any]):
        for entry in payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if not isinstance(change, dict) or change.get("field") != "messages":
                    continue
                value = change.get("value")
                if not isinstance(value, dict):
                    continue
                names = {
                    str(contact.get("wa_id") or ""): str((contact.get("profile") or {}).get("name") or "")
                    for contact in value.get("contacts") or []
                    if isinstance(contact, dict)
                }
                phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
                for item in value.get("messages") or []:
                    if isinstance(item, dict):
                        yield phone_number_id, names, item

    def to_event(self, item):
        """Make a gateway event from one WhatsApp text message."""
        phone_number_id, names, message = item
        sender = str(message.get("from") or "")
        text = str((message.get("text") or {}).get("body") or "").strip()
        if (
            not phone_number_id
            or message.get("type") != "text"
            or not sender
            or sender not in self.allowed_users()
            or not text
        ):
            return None
        return self.ctx.gateway_message_event(
            text=text,
            source=self.ctx.gateway_session_source(
                platform=self.name,
                chat_id=sender,
                user_id=sender,
                user_name=names.get(sender) or sender,
                chat_type="dm",
                thread_id=None,
                chat_name=names.get(sender) or sender,
            ),
            message_id=str(message.get("id") or ""),
            raw=message,
        )

    def handle_message(self, event) -> None:
        self.runner.dispatch(event)

    def send(self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None):
        del thread_id
        phone_number_id = str(self.config.get("phone_number_id") or "")
        if not phone_number_id:
            return self.ctx.gateway_send_result(False, error="whatsapp requires phone_number_id")
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "text",
            "text": {"body": text},
        }
        if reply_to:
            body["context"] = {"message_id": reply_to}
        request = urllib.request.Request(  # noqa: S310 - Graph endpoint may be a local test fake
            f"{self.base_url}/{API_VERSION}/{phone_number_id}/messages",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=float(self.config.get("request_timeout", 30))
            ) as response:  # noqa: S310
                result = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001 - runner receives a result rather than an adapter exception
            return self.ctx.gateway_send_result(False, error=f"WhatsApp send failed: {exc}")
        messages = result.get("messages") if isinstance(result, dict) else None
        message_id = (
            str(messages[0].get("id") or "")
            if isinstance(messages, list) and messages and isinstance(messages[0], dict)
            else ""
        )
        return self.ctx.gateway_send_result(True, message_id=message_id)

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        return None

    def can_edit(self) -> bool:
        return False


def register(ctx) -> None:
    ctx.register_platform("whatsapp", lambda config, runner: WhatsAppAdapter(config, runner, ctx))
