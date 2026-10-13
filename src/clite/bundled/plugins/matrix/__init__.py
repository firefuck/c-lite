"""Matrix gateway adapter using Client-Server API long polling.

Configuration (``gateway.platforms.matrix``)::

    enabled: true
    base_url: https://matrix.example.com
    allowed_users: ["@owner:example.com"]

The access token is read from ``MATRIX_ACCESS_TOKEN`` in ``.env``. This adapter deliberately
supports only unencrypted ``m.room.message`` events: Matrix E2EE is not implemented at this
stage, so encrypted rooms cannot be read or replied to.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import urllib.request
from typing import Any

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.threads import start_thread

logger = logging.getLogger("clite.plugin.matrix")

TOKEN_ENV = "MATRIX_ACCESS_TOKEN"
DEFAULT_BASE_URL = "https://matrix.org"
POLL_TIMEOUT_SECONDS = 30
register_secret(SecretSpec(TOKEN_ENV, "Matrix Client-Server API access token", category="messaging"))


class MatrixAdapter:
    """Translate unencrypted Matrix room messages to gateway events and send room replies."""

    name = "matrix"
    max_message_length = 65_000

    def __init__(self, config: dict[str, Any], runner: Any, ctx: Any) -> None:
        self.config = config
        self.runner = runner
        self.ctx = ctx
        self.token = get_secret(TOKEN_ENV) or ""
        self.base_url = str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.poll_timeout = int(config.get("poll_timeout") or POLL_TIMEOUT_SECONDS)
        self._next_batch = str(config.get("since") or "")
        self._transaction = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def allowed_users(self) -> set[str]:
        return {str(user) for user in self.config.get("allowed_users") or []}

    def connect(self) -> None:
        if not self.token:
            raise RuntimeError(f"{TOKEN_ENV} is not set; add it to .env")
        self._stop.clear()
        self._thread = start_thread(self._poll, name="clite-matrix")

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_timeout + 5)

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 40.0
    ) -> dict[str, Any]:
        request = urllib.request.Request(  # noqa: S310 - endpoint comes from configuration
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the homeserver URL from config
                parsed = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001 - receive and send failures stay on their paths
            raise RuntimeError(f"Matrix {method} {path.split('?', 1)[0]} failed: {exc}") from None
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Matrix {method} returned an invalid response")
        if parsed.get("errcode"):
            raise RuntimeError(f"Matrix {method} failed: {parsed.get('error') or parsed['errcode']}")
        return parsed

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                response = self._sync()
                self._next_batch = str(response.get("next_batch") or self._next_batch)
                for event in self._events(response):
                    message = self.to_event(event)
                    if message is not None:
                        self.handle_message(message)
            except Exception as exc:  # noqa: BLE001 - one failed long poll must not stop the adapter
                logger.warning("Matrix sync failed: %s", exc)
                self._stop.wait(1)

    def _sync(self) -> dict[str, Any]:
        query = {"timeout": str(max(self.poll_timeout, 0) * 1000)}
        if self._next_batch:
            query["since"] = self._next_batch
        return self._request(
            "GET", f"/_matrix/client/v3/sync?{urllib.parse.urlencode(query)}", timeout=self.poll_timeout + 10
        )

    @staticmethod
    def _events(response: dict[str, Any]):
        joined = (response.get("rooms") or {}).get("join") or {}
        if not isinstance(joined, dict):
            return
        for room_id, room in joined.items():
            timeline = room.get("timeline") if isinstance(room, dict) else None
            for event in (timeline or {}).get("events") or []:
                if isinstance(event, dict):
                    yield str(room_id), event

    def to_event(self, item):
        """Make a gateway event from one unencrypted Matrix timeline event."""
        room_id, event = item
        if event.get("type") != "m.room.message":
            return None
        sender = str(event.get("sender") or "")
        content = event.get("content") or {}
        if not sender or sender not in self.allowed_users() or content.get("msgtype") != "m.text":
            return None
        text = str(content.get("body") or "").strip()
        if not text:
            return None
        relates_to = content.get("m.relates_to") or {}
        reply = (relates_to.get("m.in_reply_to") or {}).get("event_id")
        return self.ctx.gateway_message_event(
            text=text,
            source=self.ctx.gateway_session_source(
                platform=self.name,
                chat_id=room_id,
                user_id=sender,
                user_name=sender,
                chat_type="group",
                thread_id=str(reply) if reply else None,
                chat_name=room_id,
            ),
            message_id=str(event.get("event_id") or ""),
            raw=event,
        )

    def handle_message(self, event) -> None:
        self.runner.dispatch(event)

    def send(self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None):
        self._transaction += 1
        path = "/_matrix/client/v3/rooms/{}/send/m.room.message/{}".format(
            urllib.parse.quote(chat_id, safe=""), self._transaction
        )
        body: dict[str, Any] = {"msgtype": "m.text", "body": text}
        target = reply_to or thread_id
        if target:
            body["m.relates_to"] = {"m.in_reply_to": {"event_id": target}}
        try:
            result = self._request("PUT", path, body)
        except Exception as exc:  # noqa: BLE001 - runner receives a result rather than an adapter exception
            return self.ctx.gateway_send_result(False, error=str(exc))
        return self.ctx.gateway_send_result(True, message_id=str(result.get("event_id") or ""))

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        return None

    def can_edit(self) -> bool:
        return False


def register(ctx) -> None:
    ctx.register_platform("matrix", lambda config, runner: MatrixAdapter(config, runner, ctx))
