"""Discord platform adapter: WebSocket Gateway v10 + REST API.

Configuration (``config.yaml``)::

    gateway:
      platforms:
        discord:
          enabled: true
          allowed_users: ["1234567890"]    # Discord user IDs; others rejected

The bot token is read from ``DISCORD_BOT_TOKEN`` in ``.env``.
``base_url`` and ``gateway_url`` can point the adapter at mock servers for tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import websockets

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.errors import CliteError
from clite.core.threads import start_thread
from clite.gateway.event import CHAT_DM, CHAT_GROUP, MessageEvent, SendResult, SessionSource
from clite.gateway.platforms.base import BasePlatformAdapter, register_platform, split_message

logger = logging.getLogger("clite.gateway.discord")

TOKEN_ENV = "DISCORD_BOT_TOKEN"
DEFAULT_BASE_URL = "https://discord.com/api/v10"
DEFAULT_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

register_secret(
    SecretSpec(
        TOKEN_ENV,
        "Discord bot token from the Discord Developer Portal",
        category="messaging",
        url="https://discord.com/developers/applications",
    )
)


class DiscordAdapter(BasePlatformAdapter):
    name = "discord"
    max_message_length = 2000

    def __init__(self, config: dict[str, Any], runner: Any) -> None:
        super().__init__(config, runner)
        self.token = get_secret(TOKEN_ENV) or ""
        self.base_url = str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.gateway_url = str(config.get("gateway_url") or DEFAULT_GATEWAY_URL)
        self.bot_id = ""
        self.bot_username = ""

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None
        self._last_seq: int | None = None
        self._session_id: str | None = None
        self._resume_gateway_url: str | None = None

    def _call_rest(
        self, method: str, endpoint: str, payload: dict[str, Any] | None = None, timeout: float = 30.0
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "clite (https://github.com/dragovics/clite, 0.1)",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 - the Discord API base URL
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the Discord API base URL
                body = resp.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            try:
                err_data = json.loads(exc.read())
            except Exception:  # noqa: BLE001 - an unreadable error body falls back to the status
                err_data = {"message": f"HTTP {exc.code}"}
            raise CliteError(f"Discord API error {exc.code}: {err_data.get('message', '')}") from exc
        except Exception as exc:
            raise CliteError(f"Discord network error: {exc}") from exc

    def connect(self) -> None:
        if not self.token:
            raise CliteError(f"Discord adapter requires {TOKEN_ENV} in .env")

        # Verify bot credentials via REST
        try:
            me = self._call_rest("GET", "/users/@me")
            self.bot_id = str(me.get("id", ""))
            self.bot_username = str(me.get("username", ""))
        except Exception as exc:
            raise CliteError(f"failed to connect to Discord with token: {exc}") from exc

        logger.info("connected to Discord as %s (%s)", self.bot_username, self.bot_id)
        self._stop.clear()
        self._thread = start_thread(self._run_gateway, name="clite-discord")

    def disconnect(self) -> None:
        self._stop.set()
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def send(
        self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None
    ) -> SendResult:
        target = thread_id or chat_id
        chunks = split_message(text, self.max_message_length)
        last_id = ""

        for idx, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"content": chunk}
            if idx == 0 and reply_to:
                payload["message_reference"] = {"message_id": reply_to}
            try:
                res = self._call_rest("POST", f"/channels/{target}/messages", payload)
                last_id = str(res.get("id", ""))
            except Exception as exc:  # noqa: BLE001 - a failed send is reported, not raised
                logger.warning("failed to send message chunk to Discord %s: %s", target, exc)
                return SendResult(False, error=str(exc))

        return SendResult(True, message_id=last_id)

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        target = thread_id or chat_id
        try:
            self._call_rest("POST", f"/channels/{target}/typing")
        except Exception as exc:  # noqa: BLE001 - the typing indicator is cosmetic
            logger.debug("failed to trigger Discord typing indicator for %s: %s", target, exc)

    def _run_gateway(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._gateway_loop())
        finally:
            self._loop.close()

    async def _gateway_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            ws_url = self._resume_gateway_url or self.gateway_url
            try:
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    backoff = 1.0  # reset on successful connection
                    await self._handle_connection(ws)
            except Exception as exc:  # noqa: BLE001 - any connection failure reconnects with backoff
                if self._stop.is_set():
                    break
                logger.warning(
                    "Discord gateway connection dropped (%s), reconnecting in %.1fs…", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    async def _handle_connection(self, ws: Any) -> None:
        # Step 1: Wait for Opcode 10 (HELLO)
        hello_raw = await ws.recv()
        hello = json.loads(hello_raw)
        if hello.get("op") != 10:
            logger.warning("expected Opcode 10 HELLO, got %s", hello)
            return

        heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000.0

        # Step 2: Identify or Resume
        if self._session_id and self._last_seq is not None:
            # Resume
            resume_payload = {
                "op": 6,
                "d": {"token": self.token, "session_id": self._session_id, "seq": self._last_seq},
            }
            await ws.send(json.dumps(resume_payload))
        else:
            # Identify
            identify_payload = {
                "op": 2,
                "d": {
                    "token": self.token,
                    "intents": 33280,  # GUILDS (1) + GUILD_MESSAGES (512) + DIRECT_MESSAGES (4096) + MESSAGE_CONTENT (32768)
                    "properties": {"os": "linux", "browser": "clite", "device": "clite"},
                },
            }
            await ws.send(json.dumps(identify_payload))

        last_ack = time.monotonic()

        async def heartbeat_worker():
            nonlocal last_ack
            while not self._stop.is_set():
                await asyncio.sleep(heartbeat_interval)
                # Check if missed heartbeat ACK
                if time.monotonic() - last_ack > heartbeat_interval * 2.5:
                    logger.warning("missed Discord heartbeat ACK, disconnecting to resume…")
                    await ws.close(1000, "Missed heartbeat ACK")
                    break
                hb = {"op": 1, "d": self._last_seq}
                await ws.send(json.dumps(hb))

        hb_task = asyncio.create_task(heartbeat_worker())

        try:
            async for raw in ws:
                data = json.loads(raw)
                op = data.get("op")
                seq = data.get("s")
                if seq is not None:
                    self._last_seq = seq

                if op == 11:  # HEARTBEAT_ACK
                    last_ack = time.monotonic()
                elif op == 7:  # RECONNECT
                    logger.info("Discord requested reconnect (Opcode 7)")
                    break
                elif op == 9:  # INVALID_SESSION
                    logger.warning("Discord session invalidated (Opcode 9)")
                    self._session_id = None
                    self._last_seq = None
                    break
                elif op == 0:  # DISPATCH
                    event_type = data.get("t")
                    event_data = data.get("d") or {}
                    if event_type == "READY":
                        self._session_id = event_data.get("session_id")
                        self._resume_gateway_url = event_data.get("resume_gateway_url")
                        logger.info("Discord Gateway READY (session: %s)", self._session_id)
                    elif event_type == "MESSAGE_CREATE":
                        self._on_message_create(event_data)
        finally:
            hb_task.cancel()

    def _on_message_create(self, data: dict[str, Any]) -> None:
        author = data.get("author") or {}
        author_id = str(author.get("id", ""))
        # Ignore bot's own messages and other bots
        if author_id == self.bot_id or author.get("bot", False):
            return

        channel_id = str(data.get("channel_id", ""))
        guild_id = data.get("guild_id")
        content = data.get("content", "")
        message_id = str(data.get("id", ""))
        thread_id = None

        # Check if message is in a thread
        # Discord thread channel types: 11 (PUBLIC_THREAD), 12 (PRIVATE_THREAD)
        channel_type = data.get("channel_type")
        if channel_type in (11, 12) or "thread" in data:
            thread_id = channel_id

        # In direct messages (no guild_id)
        if not guild_id:
            chat_type = CHAT_DM
        else:
            chat_type = CHAT_GROUP
            # In a guild channel, only respond if mentioned or replying to agent
            mention_pattern = rf"<@!?{re.escape(self.bot_id)}>"
            is_mentioned = bool(re.search(mention_pattern, content))
            referenced = data.get("referenced_message")
            is_reply_to_bot = bool(referenced and str(referenced.get("author", {}).get("id")) == self.bot_id)

            if not (is_mentioned or is_reply_to_bot):
                return

            # Strip the bot mention from prompt content
            content = re.sub(mention_pattern, "", content).strip()

        source = SessionSource(
            platform=self.name,
            chat_id=channel_id,
            user_id=author_id,
            user_name=author.get("username", ""),
            chat_type=chat_type,
            thread_id=thread_id,
        )
        self.handle_message(MessageEvent(text=content, source=source, message_id=message_id))


register_platform("discord", DiscordAdapter)
