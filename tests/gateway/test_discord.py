"""Tests for the Discord platform adapter against a local mock Discord server."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from websockets.asyncio.server import serve

from clite.core.env import secret_names
from clite.gateway.event import CHAT_DM, CHAT_GROUP, MessageEvent
from clite.gateway.platforms.discord import TOKEN_ENV, DiscordAdapter


class FakeDiscordServer:
    def __init__(self):
        self.sent_messages = []
        self.rest_calls = []
        self.ws_clients = set()
        self.heartbeats_received = 0
        self.miss_heartbeat_ack = False
        self.last_identify = None
        self.loop = asyncio.new_event_loop()

        # 1. Local HTTP REST Server
        server_self = self

        class RestHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                server_self.rest_calls.append(("GET", self.path))
                if self.path == "/users/@me":
                    if "Bot good-token" not in self.headers.get("Authorization", ""):
                        return self._reply({"message": "401: Unauthorized"}, status=401)
                    return self._reply({"id": "bot-999", "username": "clite_bot"})
                self._reply({}, status=404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length > 0 else {}
                server_self.rest_calls.append(("POST", self.path, body))
                if "/messages" in self.path:
                    server_self.sent_messages.append(body)
                    return self._reply({"id": f"msg-{len(server_self.sent_messages)}", **body})
                if "/typing" in self.path:
                    return self._reply({})
                self._reply({})

            def _reply(self, payload, status=200):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), RestHandler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.rest_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        # 2. Local WebSocket Gateway Server
        self._ws_server = None
        self.ws_port = 0
        self._ready_event = threading.Event()
        threading.Thread(target=self._run_ws, daemon=True).start()
        self._ready_event.wait(timeout=5.0)

    def _run_ws(self):
        asyncio.set_event_loop(self.loop)

        async def handler(websocket):
            self.ws_clients.add(websocket)
            try:
                # Opcode 10 HELLO
                await websocket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
                async for msg in websocket:
                    data = json.loads(msg)
                    op = data.get("op")
                    if op == 2:  # IDENTIFY
                        self.last_identify = data["d"]
                        # Send READY
                        ready = {
                            "op": 0,
                            "t": "READY",
                            "d": {
                                "session_id": "sess-discord-123",
                                "user": {"id": "bot-999", "username": "clite_bot"},
                                "resume_gateway_url": self.ws_url,
                            },
                        }
                        await websocket.send(json.dumps(ready))
                    elif op == 1:  # HEARTBEAT
                        self.heartbeats_received += 1
                        if not self.miss_heartbeat_ack:
                            await websocket.send(json.dumps({"op": 11}))  # HEARTBEAT_ACK
            finally:
                self.ws_clients.discard(websocket)

        async def main():
            server = await serve(handler, "127.0.0.1", 0)
            self._ws_server = server
            self.ws_port = server.sockets[0].getsockname()[1]
            self._ready_event.set()
            await server.wait_closed()

        self.loop.run_until_complete(main())

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.ws_port}"

    def push_message(
        self,
        content: str,
        *,
        author_id="user-1",
        username="alice",
        channel_id="chan-1",
        guild_id=None,
        channel_type=0,
        is_bot=False,
        referenced_author_id=None,
    ):
        payload = {
            "op": 0,
            "t": "MESSAGE_CREATE",
            "d": {
                "id": f"in-{time.time()}",
                "channel_id": channel_id,
                "guild_id": guild_id,
                "channel_type": channel_type,
                "content": content,
                "author": {"id": author_id, "username": username, "bot": is_bot},
            },
        }
        if referenced_author_id:
            payload["d"]["referenced_message"] = {"author": {"id": referenced_author_id}}

        data = json.dumps(payload)
        for client in list(self.ws_clients):
            asyncio.run_coroutine_threadsafe(client.send(data), self.loop)

    def close(self):
        self.httpd.shutdown()
        if self._ws_server:
            self._ws_server.close()


class DummyRunner:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, event: MessageEvent):
        self.dispatched.append(event)


@pytest.fixture
def fake_discord():
    server = FakeDiscordServer()
    yield server
    server.close()


def test_discord_token_is_registered_secret():
    assert TOKEN_ENV in secret_names()


def test_discord_connect_and_message_handling(fake_discord, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "good-token")
    runner = DummyRunner()

    config = {
        "base_url": fake_discord.rest_url,
        "gateway_url": fake_discord.ws_url,
        "allowed_users": ["user-1"],
    }

    adapter = DiscordAdapter(config, runner)
    adapter.connect()

    # Wait for gateway connection and READY
    time.sleep(0.3)
    assert adapter.bot_id == "bot-999"
    assert adapter.bot_username == "clite_bot"
    assert fake_discord.last_identify is not None
    assert fake_discord.last_identify["token"] == "good-token"

    # 1. Direct Message (no guild_id): always answered
    fake_discord.push_message("hello bot directly", author_id="user-1", channel_id="dm-chan-1", guild_id=None)
    time.sleep(0.2)
    assert len(runner.dispatched) == 1
    ev1 = runner.dispatched[0]
    assert ev1.text == "hello bot directly"
    assert ev1.source.chat_type == CHAT_DM
    assert ev1.source.user_id == "user-1"
    assert ev1.source.chat_id == "dm-chan-1"

    # 2. Guild message WITHOUT mention: ignored
    fake_discord.push_message(
        "just chat in server", author_id="user-1", channel_id="guild-chan", guild_id="guild-1"
    )
    time.sleep(0.1)
    assert len(runner.dispatched) == 1

    # 3. Guild message WITH mention: stripped and answered
    fake_discord.push_message(
        "<@bot-999> what is python?", author_id="user-1", channel_id="guild-chan", guild_id="guild-1"
    )
    time.sleep(0.2)
    assert len(runner.dispatched) == 2
    ev2 = runner.dispatched[1]
    assert ev2.text == "what is python?"
    assert ev2.source.chat_type == CHAT_GROUP
    assert ev2.source.chat_id == "guild-chan"

    # 4. Message in a Thread: thread_id populated
    fake_discord.push_message(
        "<@!bot-999> in thread",
        author_id="user-1",
        channel_id="thread-chan",
        guild_id="guild-1",
        channel_type=11,
    )
    time.sleep(0.2)
    assert len(runner.dispatched) == 3
    ev3 = runner.dispatched[2]
    assert ev3.text == "in thread"
    assert ev3.source.thread_id == "thread-chan"

    # 5. Message from bot itself: ignored
    fake_discord.push_message("echo", author_id="bot-999", is_bot=True)
    time.sleep(0.1)
    assert len(runner.dispatched) == 3

    # 6. Send response via adapter.send
    res = adapter.send("dm-chan-1", "response from agent", reply_to="in-123")
    assert res.success is True
    assert len(fake_discord.sent_messages) == 1
    sent = fake_discord.sent_messages[0]
    assert sent["content"] == "response from agent"
    assert sent["message_reference"] == {"message_id": "in-123"}

    adapter.disconnect()


def test_missed_heartbeat_triggers_reconnect(fake_discord, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "good-token")
    runner = DummyRunner()

    config = {
        "base_url": fake_discord.rest_url,
        "gateway_url": fake_discord.ws_url,
    }

    adapter = DiscordAdapter(config, runner)
    adapter.connect()

    # Wait for initial connection
    time.sleep(0.2)
    initial_hb = fake_discord.heartbeats_received
    assert initial_hb >= 1

    # Simulate dropped/missed heartbeat ACKs
    fake_discord.miss_heartbeat_ack = True

    # Sleep longer than 2.5 * 100ms interval
    time.sleep(0.5)

    # Resume ACKs
    fake_discord.miss_heartbeat_ack = False
    time.sleep(0.4)

    # The adapter must have reconnected and resumed heartbeating
    assert fake_discord.heartbeats_received > initial_hb

    adapter.disconnect()
