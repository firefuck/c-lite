"""WhatsApp Cloud platform plugin tests against local webhook and Graph API fakes."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from clite.gateway.platforms.base import PLATFORMS
from clite.plugins.manager import ensure_plugins_loaded


class _GraphHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict[str, Any]]] = []

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_POST(self) -> None:  # required by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append((self.path, body))
        encoded = b'{"messages":[{"id":"wamid.answer"}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _wait_for(predicate, timeout: float = 3) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        threading.Event().wait(0.01)
    return False


def test_whatsapp_plugin_verifies_local_webhook_dispatches_allowed_message_and_sends_reply(monkeypatch):
    _GraphHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GraphHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "access-secret")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-secret")

    class Runner:
        def __init__(self) -> None:
            self.events: list[Any] = []

        def dispatch(self, event) -> None:
            self.events.append(event)
            adapter.send(event.source.chat_id, "The answer", reply_to=event.message_id)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "12345"},
                            "contacts": [{"wa_id": "15550001111", "profile": {"name": "Allowed sender"}}],
                            "messages": [
                                {
                                    "from": "15550001111",
                                    "id": "wamid.question",
                                    "type": "text",
                                    "text": {"body": "Please reply."},
                                }
                            ],
                        },
                    }
                ]
            }
        ],
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    try:
        ensure_plugins_loaded()
        runner = Runner()
        adapter = PLATFORMS["whatsapp"](
            {
                "base_url": f"http://127.0.0.1:{server.server_address[1]}",
                "phone_number_id": "12345",
                "allowed_users": ["15550001111"],
            },
            runner,
        )
        assert (
            adapter.handle_webhook_verification(
                {"hub.mode": "subscribe", "hub.verify_token": "verify-secret", "hub.challenge": "challenge"}
            )
            == "challenge"
        )
        assert (
            adapter.handle_webhook_verification(
                {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "challenge"}
            )
            is None
        )
        assert adapter.handle_webhook(raw, signature)
        assert _wait_for(lambda: len(_GraphHandler.requests) == 1)
        assert len(runner.events) == 1
        event = runner.events[0]
        assert event.text == "Please reply."
        assert event.message_id == "wamid.question"
        assert event.source.chat_id == "15550001111"
        assert event.source.user_id == "15550001111"
        assert event.source.user_name == "Allowed sender"
        assert _GraphHandler.requests == [
            (
                "/v21.0/12345/messages",
                {
                    "messaging_product": "whatsapp",
                    "to": "15550001111",
                    "type": "text",
                    "text": {"body": "The answer"},
                    "context": {"message_id": "wamid.question"},
                },
            )
        ]
    finally:
        server.shutdown()
        server.server_close()
