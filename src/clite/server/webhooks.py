"""Configured, HMAC-authenticated inbound webhooks for the optional HTTP server."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from clite.core.env import get_secret
from clite.gateway.runner import active_runner
from clite.runtime.factory import build_agent


def webhook_secret_name(name: str) -> str:
    return "CLITE_WEBHOOK_" + "".join(char if char.isalnum() else "_" for char in name.upper()) + "_SECRET"


def _config(config: dict[str, Any], name: str) -> dict[str, Any] | None:
    hooks = config.get("webhooks") or {}
    item = hooks.get(name) if isinstance(hooks, dict) else None
    return item if isinstance(item, dict) and item.get("enabled", True) else None


def routes(config: dict[str, Any], client_factory: Callable[[], Any] | None) -> Callable[[Request], Any]:
    async def receive(request: Request) -> JSONResponse | PlainTextResponse:
        if not bool((config.get("server") or {}).get("webhooks_enabled", False)):
            return JSONResponse({"error": "not found"}, status_code=404)
        name = str(request.path_params["name"])
        runner = active_runner()
        adapter = runner.adapters.get("whatsapp") if name == "whatsapp" and runner is not None else None
        if adapter is not None:
            verify = getattr(adapter, "handle_webhook_verification", None)
            receive_whatsapp = getattr(adapter, "handle_webhook", None)
            if not callable(verify) or not callable(receive_whatsapp):
                return JSONResponse({"error": "not found"}, status_code=404)
            if request.method == "GET":
                challenge = verify(dict(request.query_params))
                return (
                    JSONResponse({"error": "forbidden"}, status_code=403)
                    if challenge is None
                    else PlainTextResponse(challenge)
                )
            accepted = receive_whatsapp(await request.body(), request.headers.get("x-hub-signature-256", ""))
            return JSONResponse({"ok": accepted}, status_code=200 if accepted else 401)
        spec = _config(config, name)
        secret = get_secret(webhook_secret_name(name))
        if spec is None or not secret:
            return JSONResponse({"error": "not found"}, status_code=404)
        raw = await request.body()
        signature = request.headers.get("x-clite-signature", "")
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return JSONResponse({"error": "invalid signature"}, status_code=401)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw.decode("utf-8", errors="replace")
        prompt = str(spec.get("prompt") or "Process this webhook payload.")
        untrusted = json.dumps(payload, ensure_ascii=False)
        message = f"{prompt}\n\n<untrusted_webhook_payload name={name!r}>\n{untrusted}\n</untrusted_webhook_payload>"

        def run() -> None:
            agent = build_agent(platform="api", client=client_factory() if client_factory else None)
            try:
                answer = agent.run_conversation(message).final_response
            finally:
                agent.close("webhook_complete")
            target = str(spec.get("deliver") or "")
            runner = active_runner()
            if target and runner is not None:
                runner.send_to(target, answer)

        asyncio.create_task(asyncio.to_thread(run))
        return JSONResponse({"ok": True}, status_code=202)

    return receive
