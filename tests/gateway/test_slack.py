"""Tests for the Slack platform adapter against a local mock Socket Mode & Web API server."""

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
from clite.gateway.platforms.slack import APP_TOKEN_ENV, BOT_TOKEN_ENV, SlackAdapter


class FakeSlackServer:
    def __init__(self):
        self.posted_messages = []
        self.web_calls = []
        self.ws_clients = set()
        self.received_acks = []
        self.loop = asyncio.new_event_loop()

        # 1. Local HTTP Web API Server
        server_self = self

        class RestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                auth = self.headers.get("Authorization", "")
                server_self.web_calls.append((self.path, body, auth))

                if self.path == "/auth.test":
                    if "Bearer good-bot-token" not in auth:
                        return self._reply({"ok": False, "error": "invalid_auth"}, 401)
                    return self._reply({"ok": True, "user_id": "U_BOT_99"})

                if self.path == "/apps.connections.open":
                    if "Bearer good-app-token" not in auth:
                        return self._reply({"ok": False, "error": "invalid_auth"}, 401)
                    return self._reply({"ok": True, "url": server_self.ws_url})

                if self.path == "/chat.postMessage":
                    server_self.posted_messages.append(body)
                    return self._reply(
                        {"ok": True, "ts": f"1700000000.{len(server_self.posted_messages)}", "message": body}
                    )

                self._reply({"ok": True})
                return None

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
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

        # 2. Local WebSocket Socket Mode Server
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
                async for msg in websocket:
                    data = json.loads(msg)
                    env_id = data.get("envelope_id")
                    if env_id:
                        self.received_acks.append(env_id)
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

    def push_event(self, envelope_id: str, event_id: str, event_data: dict):
        payload = {
            "envelope_id": envelope_id,
            "type": "events_api",
            "accepts_response_payload": False,
            "payload": {
                "event_id": event_id,
                "event_time": int(time.time()),
                "event": event_data,
            },
        }
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
def fake_slack():
    server = FakeSlackServer()
    yield server
    server.close()


def test_slack_tokens_are_registered_secrets():
    secrets = secret_names()
    assert APP_TOKEN_ENV in secrets
    assert BOT_TOKEN_ENV in secrets


def test_slack_connect_message_ack_dedupe_and_thread_reply(fake_slack, monkeypatch):
    monkeypatch.setenv(APP_TOKEN_ENV, "good-app-token")
    monkeypatch.setenv(BOT_TOKEN_ENV, "good-bot-token")
    runner = DummyRunner()

    config = {
        "base_url": fake_slack.base_url,
        "allowed_users": ["U_ALICE"],
    }

    adapter = SlackAdapter(config, runner)
    adapter.connect()

    # Wait for connection
    time.sleep(0.3)
    assert adapter.bot_user_id == "U_BOT_99"

    # 1. Incoming Direct Message (channel type "im")
    fake_slack.push_event(
        envelope_id="env-1",
        event_id="Ev-001",
        event_data={
            "type": "message",
            "user": "U_ALICE",
            "channel": "D_DIRECT",
            "channel_type": "im",
            "text": "hello in private",
            "ts": "1700000001.000100",
        },
    )
    time.sleep(0.2)

    # Must be acknowledged
    assert "env-1" in fake_slack.received_acks
    assert len(runner.dispatched) == 1
    ev1 = runner.dispatched[0]
    assert ev1.text == "hello in private"
    assert ev1.source.chat_type == CHAT_DM
    assert ev1.source.user_id == "U_ALICE"
    # Thread ID should default to message ts so reply starts thread
    assert ev1.source.thread_id == "1700000001.000100"

    # 2. Duplicate delivery of same event_id: must ack, but NOT dispatch again
    fake_slack.push_event(
        envelope_id="env-1-retry",
        event_id="Ev-001",
        event_data={
            "type": "message",
            "user": "U_ALICE",
            "channel": "D_DIRECT",
            "channel_type": "im",
            "text": "hello in private",
            "ts": "1700000001.000100",
        },
    )
    time.sleep(0.2)
    assert "env-1-retry" in fake_slack.received_acks
    assert len(runner.dispatched) == 1  # Still 1, deduplicated!

    # 3. Channel message without mention: ignored
    fake_slack.push_event(
        envelope_id="env-2",
        event_id="Ev-002",
        event_data={
            "type": "message",
            "user": "U_BOB",
            "channel": "C_GENERAL",
            "channel_type": "channel",
            "text": "chatter among humans",
            "ts": "1700000002.000100",
        },
    )
    time.sleep(0.2)
    assert "env-2" in fake_slack.received_acks
    assert len(runner.dispatched) == 1

    # 4. Channel message with app_mention in existing thread: answered in that thread
    fake_slack.push_event(
        envelope_id="env-3",
        event_id="Ev-003",
        event_data={
            "type": "app_mention",
            "user": "U_BOB",
            "channel": "C_GENERAL",
            "channel_type": "channel",
            "text": "<@U_BOT_99> check this code",
            "ts": "1700000003.000200",
            "thread_ts": "1700000000.999999",  # inside an ongoing thread
        },
    )
    time.sleep(0.2)
    assert "env-3" in fake_slack.received_acks
    assert len(runner.dispatched) == 2
    ev2 = runner.dispatched[1]
    assert ev2.text == "check this code"
    assert ev2.source.chat_type == CHAT_GROUP
    assert ev2.source.thread_id == "1700000000.999999"

    # 5. Outbound send: goes to the exact thread
    res = adapter.send("C_GENERAL", "here is the fix", thread_id=ev2.source.thread_id)
    assert res.success is True
    assert len(fake_slack.posted_messages) == 1
    posted = fake_slack.posted_messages[0]
    assert posted["channel"] == "C_GENERAL"
    assert posted["text"] == "here is the fix"
    assert posted["thread_ts"] == "1700000000.999999"

    adapter.disconnect()
