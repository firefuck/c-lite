"""OpenAI-compatible chat completions routes for the optional HTTP API."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from clite.agent import AgentCallbacks
from clite.agent.messages import content_text
from clite.runtime.factory import build_agent


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": "invalid_request_error"}}, status_code=status)


def _prompt(messages: Any) -> str:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"}:
            raise ValueError("each message must have a system, user, or assistant role")
        text = content_text(message.get("content"))
        if message["role"] == "system":
            # Client system instructions are user-supplied input, never this agent's system prompt.
            parts.append(f"[Client-supplied context]\n{text}\n[/Client-supplied context]")
        elif message["role"] == "user":
            parts.append(text)
    if not parts:
        raise ValueError("messages must contain user content")
    return "\n\n".join(parts)


def _session_id(request: Request, body: dict[str, Any]) -> str | None:
    value = request.headers.get("x-clite-session-id") or body.get("user")
    if not isinstance(value, str) or not value.strip():
        return None
    return "api-" + value.strip()[:160]


def _completion(model: str, text: str, completion_id: str) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


def routes(config: dict[str, Any], client_factory: Callable[[], Any] | None) -> tuple[Callable[[Request], Any], Callable[[Request], Any]]:
    async def models(request: Request) -> JSONResponse:
        model = str((config.get("model") or {}).get("default") or "")
        return JSONResponse({"object": "list", "data": [{"id": model, "object": "model", "owned_by": "clite"}]})

    async def chat_completions(request: Request) -> Any:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            prompt = _prompt(body.get("messages"))
        except (ValueError, json.JSONDecodeError) as exc:
            return _error(str(exc))
        model = str(body.get("model") or (config.get("model") or {}).get("default") or "")
        session_id = _session_id(request, body)
        completion_id = "chatcmpl-" + uuid.uuid4().hex
        stream = bool(body.get("stream"))
        if not stream:
            def run() -> str:
                agent = build_agent(platform="api", session_id=session_id, client=client_factory() if client_factory else None)
                try:
                    return agent.run_conversation(prompt).final_response
                finally:
                    agent.close("api_complete")
            text = await asyncio.to_thread(run)
            return JSONResponse(_completion(model, text, completion_id))

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        def emit(text: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, text)
        def run_stream() -> None:
            agent = build_agent(
                platform="api", session_id=session_id, client=client_factory() if client_factory else None,
                callbacks=AgentCallbacks(on_delta=emit),
            )
            try:
                agent.run_conversation(prompt)
            finally:
                agent.close("api_complete")
                loop.call_soon_threadsafe(queue.put_nowait, None)
        asyncio.create_task(asyncio.to_thread(run_stream))
        async def events() -> AsyncIterator[bytes]:
            role = {"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
            yield f"data: {json.dumps(role)}\n\n".encode()
            while (text := await queue.get()) is not None:
                chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                         "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            done = {"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(done)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")
    return models, chat_completions
