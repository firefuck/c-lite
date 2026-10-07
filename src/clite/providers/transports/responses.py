"""Responses wire conversion and streaming, with stateless replay of complete output items."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from clite.providers.base import API_MODE_RESPONSES
from clite.providers.http import ProviderHTTPError
from clite.providers.transports.base import ProviderTransport, StreamAccumulator, register_transport
from clite.providers.transports.types import HttpRequest, NormalizedResponse, RequestParams, ToolCall, Usage

if TYPE_CHECKING:
    from clite.providers.runtime import RuntimeRoute

REPLAY_KEY = "responses_output"


def _content(content: Any, role: str) -> Any:
    if not isinstance(content, list):
        return deepcopy(content)
    converted = []
    for part in content:
        if isinstance(part, str):
            part = {"type": "text", "text": part}
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            if role == "assistant":
                converted.append({"type": "output_text", "text": part.get("text", ""), "annotations": []})
            else:
                converted.append({"type": "input_text", "text": part.get("text", "")})
        elif part.get("type") == "image_url":
            image = part.get("image_url") or {}
            item = {"type": "input_image", "image_url": image.get("url", "")}
            if image.get("detail"):
                item["detail"] = image["detail"]
            converted.append(item)
        else:
            # Cache markers are another protocol's metadata, not Responses content fields.
            converted.append({key: deepcopy(value) for key, value in part.items() if key != "cache_control"})
    return converted


def convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build append-only input items; replay opaque output without rebuilding its IDs or order."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant" and (message.get("provider_data") or {}).get(REPLAY_KEY):
            converted.extend(deepcopy(message["provider_data"][REPLAY_KEY]))
            continue
        if role == "tool":
            converted.append({"type": "function_call_output", "call_id": message.get("tool_call_id"),
                              "output": message.get("content") or ""})
            continue
        content = message.get("content")
        if content is not None and (content or not message.get("tool_calls")):
            converted.append({"role": role, "content": _content(content, str(role))})
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            converted.append({"type": "function_call", "call_id": call["id"], "name": function["name"],
                              "arguments": function.get("arguments") or "{}"})
    return converted


def parse_response(payload: dict[str, Any]) -> NormalizedResponse:
    """Normalize a response while retaining an independent, replayable output snapshot."""
    if payload.get("error") or payload.get("status") == "failed":
        error = payload.get("error") or {"code": "server_error", "message": "Response failed; retry the request."}
        raise ProviderHTTPError(400, json.dumps({"error": error}), {}, "")
    output = deepcopy(payload.get("output") or [])
    text: list[str] = []
    reasoning: list[str] = []
    calls: list[ToolCall] = []
    refused = False
    for item in output:
        kind = item.get("type")
        if kind == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    text.append(part.get("text", ""))
                elif part.get("type") == "refusal":
                    text.append(part.get("refusal", ""))
                    refused = True
        elif kind == "reasoning":
            reasoning.extend(part.get("text", "") for part in item.get("summary") or [])
        elif kind == "function_call":
            calls.append(ToolCall(id=item["call_id"], name=item["name"], arguments=item.get("arguments") or "{}"))
    raw = payload.get("usage")
    usage = None
    if isinstance(raw, dict):
        cached = int((raw.get("input_tokens_details") or {}).get("cached_tokens") or 0)
        usage = Usage(input_tokens=max(int(raw.get("input_tokens") or 0) - cached, 0),
                      output_tokens=int(raw.get("output_tokens") or 0), cache_read_tokens=cached,
                      reasoning_tokens=int((raw.get("output_tokens_details") or {}).get("reasoning_tokens") or 0))
    finish_reason = "tool_calls" if calls else "stop"
    incomplete = payload.get("status") == "incomplete"
    if incomplete or refused:
        detail = (payload.get("incomplete_details") or {}).get("reason")
        finish_reason = "content_filter" if refused or detail == "content_filter" else "length"
        calls = []  # Never execute a function whose argument stream may have been cut short.
    return NormalizedResponse(content="".join(text) or None, reasoning="".join(reasoning) or None,
                              tool_calls=calls, finish_reason=finish_reason, usage=usage,
                              model=str(payload.get("model") or ""),
                              provider_data={REPLAY_KEY: output} if output and not incomplete else None)


class ResponsesAccumulator(StreamAccumulator):
    def __init__(self, on_delta: Callable[[str], None] | None = None,
                 on_reasoning: Callable[[str], None] | None = None) -> None:
        super().__init__(on_delta, on_reasoning)
        self.items: dict[int, dict[str, Any]] = {}
        self.response: dict[str, Any] = {}
        self.completed = False

    def feed(self, event: str, data: str) -> bool:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return True
        if not isinstance(payload, dict):
            return True
        kind = payload.get("type") or event
        if kind in ("response.created", "response.in_progress"):
            self.response.update(payload.get("response") or {})
        elif kind in ("response.output_item.added", "response.output_item.done"):
            self.items[int(payload["output_index"])] = deepcopy(payload["item"])
        elif kind == "response.function_call_arguments.delta":
            item = self.items[int(payload["output_index"])]
            item["arguments"] = item.get("arguments", "") + payload.get("delta", "")
        elif kind == "response.function_call_arguments.done":
            self.items[int(payload["output_index"])]["arguments"] = payload["arguments"]
        elif kind in ("response.output_text.delta", "response.refusal.delta"):
            self._emit(payload.get("delta", ""))
        elif kind == "response.reasoning_summary_text.delta":
            self._emit_reasoning(payload.get("delta", ""))
        elif kind in ("response.failed", "error"):
            failure = payload.get("response") or payload
            error = failure.get("error") or failure
            raise ProviderHTTPError(400, json.dumps({"error": error}), {}, "")
        elif kind in ("response.completed", "response.incomplete"):
            self.completed = True
            final = payload.get("response") or {}
            self.response.update(final)
            if "output" not in final:
                self.response["output"] = [self.items[index] for index in sorted(self.items)]
            return False
        return True

    def finish(self) -> NormalizedResponse:
        if not self.completed:
            raise ProviderHTTPError(502, json.dumps({"error": {"message":
                "Responses stream ended before a terminal event; retry the request."}}), {}, "")
        return parse_response(self.response)


class ResponsesTransport(ProviderTransport):
    api_mode = API_MODE_RESPONSES

    def build_request(self, route: RuntimeRoute, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                      params: RequestParams, *, stream: bool) -> HttpRequest:
        profile = route.profile
        prepared = deepcopy(messages)
        if profile is not None:
            prepared = profile.prepare_messages(prepared)
        body: dict[str, Any] = {"model": route.model, "input": convert_messages(prepared),
                                "store": False, "stream": stream, "include": ["reasoning.encrypted_content"]}
        if tools:
            # Responses defaults to strict schemas, unlike the internal Chat-style tools.
            # Preserve optional parameters unless the tool explicitly requests strict mode.
            body["tools"] = [{"type": "function", "strict": False, **deepcopy(tool.get("function", tool))}
                             for tool in tools]
        max_tokens = params.max_tokens or route.max_tokens or (profile.get_max_tokens(route.model) if profile else None)
        if max_tokens:
            body["max_output_tokens"] = max_tokens
        temperature = profile.resolve_temperature(route.model, params.temperature) if profile else params.temperature
        if temperature is not None:
            body["temperature"] = temperature
        if profile is not None:
            body.update(profile.build_extra_body(model=route.model, reasoning_effort=params.reasoning_effort,
                                                 session_id=params.session_id, show_reasoning=params.show_reasoning))
        if "reasoning_effort" in body:
            body.setdefault("reasoning", {})["effort"] = body.pop("reasoning_effort")
        if params.show_reasoning:
            body.setdefault("reasoning", {})["summary"] = "auto"
        body.update(params.extra_body)
        return HttpRequest(url=route.base_url.rstrip("/") + "/responses",
                           headers={"Content-Type": "application/json", **route.headers}, body=body)

    def parse_response(self, payload: dict[str, Any]) -> NormalizedResponse:
        return parse_response(payload)

    def stream_accumulator(self, on_delta: Callable[[str], None] | None = None,
                           on_reasoning: Callable[[str], None] | None = None) -> StreamAccumulator:
        return ResponsesAccumulator(on_delta, on_reasoning)


register_transport(ResponsesTransport())
