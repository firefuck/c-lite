"""Signal gateway adapter using a user-run signal-cli REST service.

Configuration (``gateway.platforms.signal``)::

    enabled: true
    base_url: http://127.0.0.1:8080
    account: +15550002222
    allowed_users: [+15550001111]

The user runs signal-cli-rest-api or an equivalent signal-cli REST bridge. The adapter polls
``GET /v1/receive/<account>`` and sends replies through ``POST /v2/send``. Only configured
``allowed_users`` are forwarded; Signal has no pairing flow in this adapter.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import urllib.request
from typing import Any

from clite.core.threads import start_thread

logger = logging.getLogger("clite.plugin.signal")


class SignalAdapter:
    """Translate signal-cli REST envelopes to gateway events and send direct replies."""

    name = "signal"
    max_message_length = 65_000

    def __init__(self, config: dict[str, Any], runner: Any, ctx: Any) -> None:
        self.config = config
        self.runner = runner
        self.ctx = ctx
        self.base_url = str(config.get("base_url") or "http://127.0.0.1:8080").rstrip("/")
        self.account = str(config.get("account") or "")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def allowed_users(self) -> set[str]:
        return {str(user) for user in self.config.get("allowed_users") or []}

    def connect(self) -> None:
        if not self.account:
            raise RuntimeError("signal requires account; set the signal-cli phone number")
        self._stop.clear()
        self._thread = start_thread(self._poll, name="clite-signal")

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=float(self.config.get("poll_interval", 1)) + 5)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(  # noqa: S310 - endpoint is explicitly user configured
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=float(self.config.get("request_timeout", 30))
            ) as response:  # noqa: S310
                return json.loads(response.read())
        except Exception as exc:  # noqa: BLE001 - protocol failures must not kill polling
            raise RuntimeError(f"signal-cli {method} {path.split('?', 1)[0]} failed: {exc}") from None

    def _poll(self) -> None:
        interval = max(float(self.config.get("poll_interval", 1)), 0.01)
        while not self._stop.is_set():
            try:
                for envelope in self._receive():
                    event = self.to_event(envelope)
                    if event is not None:
                        self.handle_message(event)
            except Exception as exc:  # noqa: BLE001 - one service failure must not stop the adapter
                logger.warning("signal-cli receive failed: %s", exc)
            self._stop.wait(interval)

    def _receive(self) -> list[Any]:
        account = urllib.parse.quote(self.account, safe="")
        result = self._request("GET", f"/v1/receive/{account}")
        return result if isinstance(result, list) else []

    def to_event(self, item: Any):
        """Make a gateway event from one signal-cli REST receive envelope."""
        envelope = item.get("envelope") if isinstance(item, dict) else None
        if not isinstance(envelope, dict):
            return None
        sender = str(envelope.get("source") or "")
        message = envelope.get("dataMessage") or {}
        text = str(message.get("message") or "").strip() if isinstance(message, dict) else ""
        if not sender or sender not in self.allowed_users() or not text:
            return None
        timestamp = envelope.get("timestamp")
        return self.ctx.gateway_message_event(
            text=text,
            source=self.ctx.gateway_session_source(
                platform=self.name,
                chat_id=sender,
                user_id=sender,
                user_name=str(envelope.get("sourceName") or sender),
                chat_type="dm",
                thread_id=None,
                chat_name=str(envelope.get("sourceName") or sender),
            ),
            message_id=str(timestamp or ""),
            raw=item,
        )

    def handle_message(self, event) -> None:
        self.runner.dispatch(event)

    def send(self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None):
        del reply_to, thread_id
        try:
            result = self._request(
                "POST", "/v2/send", {"message": text, "number": self.account, "recipients": [chat_id]}
            )
        except Exception as exc:  # noqa: BLE001 - runner receives an outcome rather than an adapter exception
            return self.ctx.gateway_send_result(False, error=str(exc))
        message_id = str(result.get("timestamp") or "") if isinstance(result, dict) else ""
        return self.ctx.gateway_send_result(True, message_id=message_id)

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        return None

    def can_edit(self) -> bool:
        return False


def register(ctx) -> None:
    ctx.register_platform("signal", lambda config, runner: SignalAdapter(config, runner, ctx))
