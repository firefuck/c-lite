"""Offline provider: deterministic answers without a network or an API key.

It exists so every surface (CLI, TUI, desktop, gateway) can be run and tested end to end on a
machine with no credentials. It is not a model. It reacts to a few directives in the last
user message:

``!<tool> {json args}``   call that tool, then report its result
``!sleep <seconds>``      stream slowly (to try out interrupting)
``!error <status>``       fail with that HTTP status (to try out retry and fallback)
``!long <words>``         produce that many words
anything else             echo the message back
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from clite.providers.base import API_MODE_MOCK
from clite.providers.transports.base import ProviderTransport, StreamAccumulator, register_transport
from clite.providers.transports.types import HttpRequest, NormalizedResponse, RequestParams, ToolCall, Usage

if TYPE_CHECKING:
    from clite.providers.runtime import RuntimeRoute

_DIRECTIVE = re.compile(r"^!(\w+)\s*(.*)$", re.DOTALL)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(len(json.dumps(message, default=str)) for message in messages) // 4


class MockTransport(ProviderTransport):
    api_mode = API_MODE_MOCK
    local = True

    def build_request(self, route: RuntimeRoute, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                      params: RequestParams, *, stream: bool) -> HttpRequest:
        raise NotImplementedError("the mock transport answers locally")

    def parse_response(self, payload: dict[str, Any]) -> NormalizedResponse:
        raise NotImplementedError("the mock transport answers locally")

    def stream_accumulator(self, on_delta: Callable[[str], None] | None = None,
                           on_reasoning: Callable[[str], None] | None = None) -> StreamAccumulator:
        raise NotImplementedError("the mock transport answers locally")

    def run(
        self,
        route: RuntimeRoute,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        params: RequestParams,
        *,
        on_delta: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> NormalizedResponse:
        usage = Usage(input_tokens=_estimate_tokens(messages))
        last = messages[-1] if messages else {"role": "user", "content": ""}
        offered = {tool.get("function", tool).get("name") for tool in tools or []}

        if last.get("role") == "tool":
            text = f"The {last.get('name') or 'tool'} tool returned: {_text_of(last.get('content'))[:500]}"
            return self._speak(text, usage, route, on_delta, cancel)

        prompt = _text_of(last.get("content")).strip()
        match = _DIRECTIVE.match(prompt)
        delay = 0.0
        if match:
            name, rest = match.group(1), match.group(2).strip()
            if name == "error":
                from clite.providers.http import ProviderHTTPError

                status = int(rest) if rest.isdigit() else 500
                raise ProviderHTTPError(status, json.dumps({"error": {"message": f"mock error {status}"}}), {}, "mock://")
            if name == "sleep":
                delay = float(rest or 1)
                prompt = "sleeping " + " ".join(["z"] * 20)
            elif name == "long":
                prompt = " ".join(f"word{n}" for n in range(int(rest or 200)))
            elif name in offered:
                try:
                    arguments = json.dumps(json.loads(rest or "{}"))
                except json.JSONDecodeError:
                    arguments = rest  # malformed on purpose: lets a test exercise argument repair
                usage.output_tokens = len(arguments) // 4 + 1
                return NormalizedResponse(
                    content=None,
                    tool_calls=[ToolCall(id="call_" + uuid.uuid4().hex[:12], name=name, arguments=arguments)],
                    finish_reason="tool_calls", usage=usage, model=route.model,
                )
            else:
                prompt = f"(mock) unknown directive or tool {name!r}; offered tools: {sorted(offered)}"
        text = prompt if match else f"You said: {prompt}"
        return self._speak(text, usage, route, on_delta, cancel, delay)

    @staticmethod
    def _speak(text: str, usage: Usage, route: RuntimeRoute, on_delta: Callable[[str], None] | None,
               cancel: threading.Event | None, delay: float = 0.0) -> NormalizedResponse:
        words = re.findall(r"\S+\s*", text) or [text]
        pause = delay / max(len(words), 1)
        for word in words:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
            if on_delta is not None:
                on_delta(word)
            if pause:
                time.sleep(pause)
        usage.output_tokens = len(text) // 4 + 1
        return NormalizedResponse(content=text, finish_reason="stop", usage=usage, model=route.model)


register_transport(MockTransport())
