"""OpenAI Chat Completions: the protocol most providers speak.

The internal message format *is* this protocol's format, so conversion is mostly removing
internal bookkeeping keys.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from clite.providers.base import API_MODE_CHAT_COMPLETIONS, OMIT_TEMPERATURE
from clite.providers.transports.base import (
    INTERNAL_MESSAGE_KEYS,
    ProviderTransport,
    StreamAccumulator,
    register_transport,
)
from clite.providers.transports.types import HttpRequest, NormalizedResponse, RequestParams, ToolCall, Usage

if TYPE_CHECKING:
    from clite.providers.runtime import RuntimeRoute


def wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages as they go on the wire: internal keys dropped, cache markers made portable."""
    wired = []
    for message in messages:
        clean = {key: value for key, value in message.items() if key not in INTERNAL_MESSAGE_KEYS}
        marker = clean.pop("cache_control", None)
        if marker is not None:
            # A marker on a message without content parts (a tool result, an assistant turn
            # that is only tool calls) rides on a text part, which is the form routers accept.
            content = clean.get("content")
            if isinstance(content, str) and content:
                clean["content"] = [{"type": "text", "text": content, "cache_control": marker}]
            elif isinstance(content, list) and content:
                clean["content"] = [*content[:-1], {**content[-1], "cache_control": marker}]
        if clean.get("role") == "assistant" and clean.get("content") is None and not clean.get("tool_calls"):
            clean["content"] = ""
        wired.append(clean)
    return wired


def parse_usage(raw: dict[str, Any] | None) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    prompt = int(raw.get("prompt_tokens") or 0)
    details = raw.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or raw.get("prompt_cache_hit_tokens") or 0)
    written = int(details.get("cache_write_tokens") or raw.get("cache_creation_input_tokens") or 0)
    reasoning = int((raw.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    return Usage(
        input_tokens=max(prompt - cached - written, 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cache_read_tokens=cached,
        cache_write_tokens=written,
        reasoning_tokens=reasoning,
    )


def _reasoning_text(source: dict[str, Any]) -> str:
    return str(source.get("reasoning_content") or source.get("reasoning") or "")


class ChatCompletionsAccumulator(StreamAccumulator):
    def __init__(self, on_delta: Callable[[str], None] | None = None,
                 on_reasoning: Callable[[str], None] | None = None) -> None:
        super().__init__(on_delta, on_reasoning)
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.calls: dict[int, dict[str, str]] = {}
        self.finish_reason = ""
        self.usage: Usage | None = None
        self.model = ""

    def feed(self, event: str, data: str) -> bool:
        if data.strip() == "[DONE]":
            return False
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return True  # keep-alive comments and partial junk are not fatal
        if isinstance(chunk.get("error"), dict):
            from clite.providers.http import ProviderHTTPError

            error = chunk["error"]
            raise ProviderHTTPError(int(error.get("code") or 500) if str(error.get("code", "")).isdigit() else 500,
                                    json.dumps(chunk), {}, "")
        self.model = chunk.get("model") or self.model
        if chunk.get("usage"):
            self.usage = parse_usage(chunk["usage"])
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                self.content.append(text)
                self._emit(text)
            thought = _reasoning_text(delta)
            if thought:
                self.reasoning.append(thought)
                self._emit_reasoning(thought)
            for call in delta.get("tool_calls") or []:
                slot = self.calls.setdefault(int(call.get("index") or 0), {"id": "", "name": "", "arguments": ""})
                function = call.get("function") or {}
                slot["id"] = call.get("id") or slot["id"]
                slot["name"] += function.get("name") or ""
                slot["arguments"] += function.get("arguments") or ""
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]
        return True

    def finish(self) -> NormalizedResponse:
        calls = [
            ToolCall(id=slot["id"] or f"call_{index}", name=slot["name"], arguments=slot["arguments"] or "{}")
            for index, slot in sorted(self.calls.items())
            if slot["name"]
        ]
        return NormalizedResponse(
            content="".join(self.content) or None,
            tool_calls=calls,
            finish_reason=_finish_reason(self.finish_reason, bool(calls)),
            reasoning="".join(self.reasoning) or None,
            usage=self.usage,
            model=self.model,
        )


def _finish_reason(raw: str, has_calls: bool) -> str:
    if has_calls:
        return "tool_calls"
    return {"stop": "stop", "length": "length", "content_filter": "content_filter", "tool_calls": "stop",
            "function_call": "stop"}.get(raw or "stop", "stop")


class ChatCompletionsTransport(ProviderTransport):
    api_mode = API_MODE_CHAT_COMPLETIONS

    def build_request(self, route: RuntimeRoute, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                      params: RequestParams, *, stream: bool) -> HttpRequest:
        profile = route.profile
        wired = wire_messages(messages)
        if profile is not None:
            wired = profile.prepare_messages(wired)
        body: dict[str, Any] = {"model": route.model, "messages": wired}
        if tools:
            body["tools"] = tools
        max_tokens = params.max_tokens or route.max_tokens or (profile.get_max_tokens(route.model) if profile else None)
        if max_tokens:
            body[profile.max_tokens_param if profile else "max_tokens"] = max_tokens
        fixed = profile.fixed_temperature if profile else None
        if fixed is not OMIT_TEMPERATURE:
            temperature = fixed if fixed is not None else params.temperature
            if temperature is not None:
                body["temperature"] = temperature
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        if profile is not None:
            body.update(profile.build_extra_body(model=route.model, reasoning_effort=params.reasoning_effort,
                                                 session_id=params.session_id))
        body.update(params.extra_body)
        headers = {"Content-Type": "application/json", **route.headers}
        return HttpRequest(url=route.base_url.rstrip("/") + "/chat/completions", headers=headers, body=body)

    def parse_response(self, payload: dict[str, Any]) -> NormalizedResponse:
        choices = payload.get("choices") or []
        if not choices:
            return NormalizedResponse(content=None, finish_reason="stop", usage=parse_usage(payload.get("usage")),
                                      model=str(payload.get("model") or ""))
        message = choices[0].get("message") or {}
        calls = [
            ToolCall(
                id=str(call.get("id") or f"call_{index}"),
                name=str((call.get("function") or {}).get("name") or ""),
                arguments=_arguments_text((call.get("function") or {}).get("arguments")),
            )
            for index, call in enumerate(message.get("tool_calls") or [])
        ]
        calls = [call for call in calls if call.name]
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return NormalizedResponse(
            content=content or None,
            tool_calls=calls,
            finish_reason=_finish_reason(str(choices[0].get("finish_reason") or ""), bool(calls)),
            reasoning=_reasoning_text(message) or None,
            usage=parse_usage(payload.get("usage")),
            model=str(payload.get("model") or ""),
        )

    def stream_accumulator(self, on_delta: Callable[[str], None] | None = None,
                           on_reasoning: Callable[[str], None] | None = None) -> StreamAccumulator:
        return ChatCompletionsAccumulator(on_delta, on_reasoning)


def _arguments_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw or "{}"
    return json.dumps(raw if raw is not None else {})


register_transport(ChatCompletionsTransport())
