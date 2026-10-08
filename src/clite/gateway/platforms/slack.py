"""Slack platform adapter: Socket Mode + Web API.

Configuration (``config.yaml``)::

    gateway:
      platforms:
        slack:
          enabled: true
          allowed_users: ["U12345678"]    # Slack member IDs; others rejected

Two credentials are required in ``.env``:
- ``SLACK_APP_TOKEN`` (starts with ``xapp-``): for Socket Mode connection.
- ``SLACK_BOT_TOKEN`` (starts with ``xoxb-``): for Web API calls.

``base_url`` can point the adapter at mock servers for tests.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from typing import Any

import websockets

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.errors import CliteError
from clite.core.threads import start_thread
from clite.gateway.event import CHAT_DM, CHAT_GROUP, MessageEvent, SendResult, SessionSource
from clite.gateway.platforms.base import BasePlatformAdapter, register_platform, split_message

logger = logging.getLogger("clite.gateway.slack")

APP_TOKEN_ENV = "SLACK_APP_TOKEN"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
DEFAULT_BASE_URL = "https://slack.com/api"

register_secret(
    SecretSpec(
        APP_TOKEN_ENV,
        "Slack app-level token (xapp-) with connections:write scope",
        category="messaging",
        url="https://api.slack.com/apps",
    )
)
register_secret(
    SecretSpec(
        BOT_TOKEN_ENV,
        "Slack bot token (xoxb-) with chat:write and channels:history scopes",
        category="messaging",
        url="https://api.slack.com/apps",
    )
)


class SlackAdapter(BasePlatformAdapter):
    name = "slack"
    max_message_length = 4000

    def __init__(self, config: dict[str, Any], runner: Any) -> None:
        super().__init__(config, runner)
        self.app_token = get_secret(APP_TOKEN_ENV) or ""
        self.bot_token = get_secret(BOT_TOKEN_ENV) or ""
        self.base_url = str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.bot_user_id = ""

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None
        self._seen_events: collections.deque[str] = collections.deque(maxlen=2000)
        self._seen_lock = threading.Lock()

    def _call_web(self, endpoint: str, payload: dict[str, Any] | None = None, token: str | None = None) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        auth_token = token or self.bot_token
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "User-Agent": "clite (https://github.com/dragovics/clite, 0.1)",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if not body.get("ok"):
                    err = body.get("error", "unknown error")
                    raise CliteError(f"Slack API error: {err}")
                return body
        except urllib.error.HTTPError as exc:
            try:
                err_body = json.loads(exc.read().decode("utf-8"))
                err_msg = err_body.get("error", f"HTTP {exc.code}")
            except Exception:
                err_msg = f"HTTP {exc.code}"
            raise CliteError(f"Slack API error: {err_msg}") from exc
        except Exception as exc:
            if isinstance(exc, CliteError):
                raise
            raise CliteError(f"Slack network error: {exc}") from exc

    def connect(self) -> None:
        if not self.app_token:
            raise CliteError(f"Slack adapter requires {APP_TOKEN_ENV} in .env")
        if not self.bot_token:
            raise CliteError(f"Slack adapter requires {BOT_TOKEN_ENV} in .env")

        # 1. Verify Bot Token and get bot identity via auth.test
        try:
            auth_info = self._call_web("auth.test")
            self.bot_user_id = str(auth_info.get("user_id", ""))
        except Exception as exc:
            raise CliteError(f"failed to authenticate with Slack bot token: {exc}") from exc

        logger.info("connected to Slack as bot user %s", self.bot_user_id)
        self._stop.clear()
        self._thread = start_thread(self._run_socket_mode, name="clite-slack")

    def disconnect(self) -> None:
        self._stop.set()
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def send(
        self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None
    ) -> SendResult:
        chunks = split_message(text, self.max_message_length)
        last_ts = ""

        # Replies in Slack should always be in thread
        target_thread = thread_id or reply_to

        for chunk in chunks:
            payload: dict[str, Any] = {
                "channel": chat_id,
                "text": chunk,
            }
            if target_thread:
                payload["thread_ts"] = target_thread

            try:
                res = self._call_web("chat.postMessage", payload)
                last_ts = str(res.get("ts", ""))
            except Exception as exc:
                logger.warning("failed to send message to Slack channel %s: %s", chat_id, exc)
                return SendResult(False, error=str(exc))

        return SendResult(True, message_id=last_ts)

    def _run_socket_mode(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._socket_mode_loop())
        finally:
            self._loop.close()

    async def _socket_mode_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                # Request a new WebSocket URL via apps.connections.open using app token
                conn_res = await asyncio.to_thread(self._call_web, "apps.connections.open", token=self.app_token)
                ws_url = conn_res.get("url")
                if not ws_url:
                    raise CliteError("no url returned from apps.connections.open")

                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    backoff = 1.0  # reset on successful connection
                    logger.info("Slack Socket Mode connected")
                    await self._handle_ws_messages(ws)
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.warning("Slack Socket Mode connection dropped (%s), reconnecting in %.1fs…", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    async def _handle_ws_messages(self, ws: Any) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            # Acknowledge the envelope immediately
            envelope_id = msg.get("envelope_id")
            if envelope_id:
                ack_payload = json.dumps({"envelope_id": envelope_id})
                await ws.send(ack_payload)

            msg_type = msg.get("type")
            if msg_type == "disconnect":
                logger.info("Slack sent disconnect signal")
                break

            if msg_type == "events_api":
                payload = msg.get("payload", {})
                event_id = str(payload.get("event_id", ""))
                # Deduplicate events: drop duplicate deliveries
                if event_id:
                    with self._seen_lock:
                        if event_id in self._seen_events:
                            logger.debug("dropping duplicate Slack event %s", event_id)
                            continue
                        self._seen_events.append(event_id)

                inner_event = payload.get("event", {})
                self._handle_event(inner_event)

    def _handle_event(self, event: dict[str, Any]) -> None:
        # Ignore bot messages and own messages
        user_id = str(event.get("user") or "")
        if not user_id or user_id == self.bot_user_id or event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        ev_type = event.get("type")
        channel = str(event.get("channel", ""))
        channel_type = event.get("channel_type", "")
        text = event.get("text", "")
        ts = str(event.get("ts", ""))
        # Reply always threads to the original message or existing thread
        thread_id = str(event.get("thread_ts") or ts)

        is_dm = channel_type == "im" or channel.startswith("D")
        if is_dm:
            chat_type = CHAT_DM
        else:
            chat_type = CHAT_GROUP
            # In group/channel, only respond if mentioned or app_mention
            mention_tag = f"<@{self.bot_user_id}>"
            is_mentioned = ev_type == "app_mention" or (self.bot_user_id and mention_tag in text)
            if not is_mentioned:
                return
            # Strip bot mention
            text = re.sub(rf"<@{re.escape(self.bot_user_id)}>", "", text).strip()

        source = SessionSource(
            platform=self.name,
            chat_id=channel,
            user_id=user_id,
            user_name="",
            chat_type=chat_type,
            thread_id=thread_id,
        )
        self.handle_message(MessageEvent(text=text, source=source, message_id=ts))


register_platform("slack", SlackAdapter)
