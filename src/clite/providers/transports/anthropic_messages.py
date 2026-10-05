"""Anthropic Messages API.

Differences from the internal (OpenAI-style) format that this transport bridges:

* the system prompt is a top-level field, not a message;
* tool results are ``tool_result`` blocks inside a *user* message;
* roles must strictly alternate, so adjacent same-role messages are merged;
* thinking blocks carry a signature and must be replayed byte-for-byte on the next request,
  so the raw blocks are kept in ``provider_data`` and reused verbatim.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from clite.providers.base import API_MODE_ANTHROPIC
from clite.providers.transports.base import ProviderTransport, StreamAccumulator, register_transport
from clite.providers.transports.types import HttpRequest, NormalizedResponse, RequestParams, ToolCall, Usage

if TYPE_CHECKING:
    from clite.providers.runtime import RuntimeRoute

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 8192
REPLAY_KEY = "anthropic_blocks"
_STOP_REASONS = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length",
                 "refusal": "content_filter", "pause_turn": "stop"}
_EMPTY_PLACEHOLDER = "(no content)"


# ── outgoing conversion ──────────────────────────────────────────────────────────────────


def _text_block(text: str, marker: Any = None) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "text", "text": text}
    if marker is not None:
        block["cache_control"] = marker
    return block


def _convert_part(part: Any) -> dict[str, Any] | None:
    if isinstance(part, str):
        return _text_block(part) if part else None
    if not isinstance(part, dict):
        return None
    kind = part.get("type")
    if kind == "text":
        if not part.get("text"):
            return None
        return _text_block(part["text"], part.get("cache_control"))
    if kind == "image_url":
        url = (part.get("image_url") or {}).get("url", "")
        if url.startswith("data:"):
            header, _, data = url.partition(",")
            media_type = header[5:].split(";")[0] or "image/png"
            source: dict[str, Any] = {"type": "base64", "media_type": media_type, "data": data}
        else:
            source = {"type": "url", "url": url}
        block = {"type": "image", "source": source}
        if part.get("cache_control") is not None:
            block["cache_control"] = part["cache_control"]
        return block
    return part  # already an Anthropic-native block


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [_text_block(content)] if content else []
    return [block for block in (_convert_part(part) for part in content) if block is not None]


def _mark_last(blocks: list[dict[str, Any]], marker: Any) -> None:
    if marker is not None and blocks:
        blocks[-1] = {**blocks[-1], "cache_control": marker}


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def convert_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(system_blocks, messages)`` in Anthropic's shape."""
    system: list[dict[str, Any]] = []
    converted: list[dict[str, Any]] = []

    def push(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})

    for message in messages:
        role = message.get("role")
        marker = message.get("cache_control")
        if role == "system":
            blocks = _content_blocks(message.get("content"))
            _mark_last(blocks, marker)
            system.extend(blocks)
        elif role == "user":
            blocks = _content_blocks(message.get("content")) or [_text_block(_EMPTY_PLACEHOLDER)]
            _mark_last(blocks, marker)
            push("user", blocks)
        elif role == "assistant":
            replay = (message.get("provider_data") or {}).get(REPLAY_KEY)
            if replay:
                blocks = [dict(block) for block in replay]
            else:
                blocks = _content_blocks(message.get("content"))
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    blocks.append({"type": "tool_use", "id": call.get("id"), "name": function.get("name"),
                                   "input": _parse_arguments(function.get("arguments"))})
            _mark_last(blocks, marker)
            push("assistant", blocks)
        elif role == "tool":
            content = message.get("content")
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id"),
                "content": content if isinstance(content, str) else _content_blocks(content),
            }
            if marker is not None:
                block["cache_control"] = marker
            push("user", [block])
    if converted and converted[0]["role"] != "user":
        converted.insert(0, {"role": "user", "content": [_text_block("(conversation continues)")]})
    return system, converted


def convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    converted = []
    for tool in tools or []:
        function = tool.get("function", tool)
        converted.append({
            "name": function["name"],
            "description": function.get("description", ""),
            "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
        })
    return converted


# ── incoming conversion ──────────────────────────────────────────────────────────────────


def parse_usage(raw: dict[str, Any] | None) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    return Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cache_read_tokens=int(raw.get("cache_read_input_tokens") or 0),
        cache_write_tokens=int(raw.get("cache_creation_input_tokens") or 0),
        reasoning_tokens=int((raw.get("output_tokens_details") or {}).get("thinking_tokens") or 0),
    )


def response_from_blocks(blocks: list[dict[str, Any]], stop_reason: str, usage: Usage | None, model: str) -> NormalizedResponse:
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    thinking = "".join(block.get("thinking", "") for block in blocks if block.get("type") == "thinking")
    calls = [
        ToolCall(id=str(block.get("id")), name=str(block.get("name")), arguments=json.dumps(block.get("input") or {}))
        for block in blocks
        if block.get("type") == "tool_use"
    ]
    needs_replay = any(block.get("type") in ("thinking", "redacted_thinking") for block in blocks)
    return NormalizedResponse(
        content=text or None,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else _STOP_REASONS.get(stop_reason, "stop"),
        reasoning=thinking or None,
        usage=usage,
        model=model,
        provider_data={REPLAY_KEY: blocks} if needs_replay else None,
    )


class AnthropicAccumulator(StreamAccumulator):
    def __init__(self, on_delta: Callable[[str], None] | None = None,
                 on_reasoning: Callable[[str], None] | None = None) -> None:
        super().__init__(on_delta, on_reasoning)
        self.blocks: dict[int, dict[str, Any]] = {}
        self.partial_json: dict[int, str] = {}
        self.stop_reason = ""
        self.usage = Usage()
        self.model = ""

    def feed(self, event: str, data: str) -> bool:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return True
        kind = payload.get("type") or event
        if kind == "message_start":
            message = payload.get("message") or {}
            self.model = message.get("model") or ""
            self.usage = parse_usage(message.get("usage")) or Usage()
        elif kind == "content_block_start":
            self.blocks[int(payload["index"])] = dict(payload.get("content_block") or {})
        elif kind == "content_block_delta":
            index = int(payload["index"])
            block = self.blocks.setdefault(index, {})
            delta = payload.get("delta") or {}
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                block["text"] = block.get("text", "") + delta.get("text", "")
                self._emit(delta.get("text", ""))
            elif delta_type == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
                self._emit_reasoning(delta.get("thinking", ""))
            elif delta_type == "signature_delta":
                block["signature"] = block.get("signature", "") + delta.get("signature", "")
            elif delta_type == "input_json_delta":
                self.partial_json[index] = self.partial_json.get(index, "") + delta.get("partial_json", "")
        elif kind == "content_block_stop":
            index = int(payload["index"])
            if index in self.partial_json:
                try:
                    self.blocks[index]["input"] = json.loads(self.partial_json.pop(index) or "{}")
                except json.JSONDecodeError:
                    self.blocks[index]["input"] = {}
        elif kind == "message_delta":
            self.stop_reason = (payload.get("delta") or {}).get("stop_reason") or self.stop_reason
            self.usage.output_tokens = int((payload.get("usage") or {}).get("output_tokens") or self.usage.output_tokens)
        elif kind == "message_stop":
            return False
        elif kind == "error":
            from clite.providers.http import ProviderHTTPError

            error = payload.get("error") or {}
            status = {"overloaded_error": 529, "rate_limit_error": 429, "api_error": 500}.get(str(error.get("type")), 400)
            raise ProviderHTTPError(status, json.dumps(payload), {}, "")
        return True

    def finish(self) -> NormalizedResponse:
        blocks = [self.blocks[index] for index in sorted(self.blocks)]
        return response_from_blocks(blocks, self.stop_reason, self.usage, self.model)


class AnthropicMessagesTransport(ProviderTransport):
    api_mode = API_MODE_ANTHROPIC

    def build_request(self, route: RuntimeRoute, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                      params: RequestParams, *, stream: bool) -> HttpRequest:
        profile = route.profile
        prepared = profile.prepare_messages(list(messages)) if profile is not None else messages
        system, converted = convert_messages(prepared)
        max_tokens = (params.max_tokens or route.max_tokens
                      or (profile.get_max_tokens(route.model) if profile else None) or DEFAULT_MAX_TOKENS)
        body: dict[str, Any] = {"model": route.model, "max_tokens": max_tokens, "messages": converted}
        if system:
            body["system"] = system
        wire_tools = convert_tools(tools)
        if wire_tools:
            body["tools"] = wire_tools
        extras = profile.build_extra_body(model=route.model, reasoning_effort=params.reasoning_effort,
                                          session_id=params.session_id) if profile is not None else {}
        # Thinking fixes the sampling temperature server-side; sending one is an error.
        temperature = profile.resolve_temperature(route.model, params.temperature) if profile else params.temperature
        if temperature is not None and "thinking" not in extras:
            body["temperature"] = temperature
        if stream:
            body["stream"] = True
        body.update(extras)
        body.update(params.extra_body)
        headers = {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION, **route.headers}
        base = route.base_url.rstrip("/")
        url = base + "/messages" if base.endswith("/v1") else base + "/v1/messages"
        return HttpRequest(url=url, headers=headers, body=body)

    def parse_response(self, payload: dict[str, Any]) -> NormalizedResponse:
        return response_from_blocks(
            list(payload.get("content") or []), str(payload.get("stop_reason") or ""),
            parse_usage(payload.get("usage")), str(payload.get("model") or ""),
        )

    def stream_accumulator(self, on_delta: Callable[[str], None] | None = None,
                           on_reasoning: Callable[[str], None] | None = None) -> StreamAccumulator:
        return AnthropicAccumulator(on_delta, on_reasoning)


register_transport(AnthropicMessagesTransport())
