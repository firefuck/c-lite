"""Test doubles for the model client. Shipped in the package so plugin authors can use them.

``ScriptedClient`` returns the responses you queue, in order, and records every call. It is
how the agent loop is tested without a network: the test states what the model "says" and
asserts on what the loop does with it.
"""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable
from typing import Any

from clite.providers.runtime import RuntimeRoute
from clite.providers.transports.types import NormalizedResponse, RequestParams, ToolCall, Usage


def text_response(text: str, *, usage: Usage | None = None, reasoning: str | None = None,
                  finish_reason: str = "stop") -> NormalizedResponse:
    return NormalizedResponse(content=text, finish_reason=finish_reason, usage=usage or Usage(10, 5), reasoning=reasoning)


def tool_call_response(*calls: tuple[str, dict[str, Any] | str], content: str | None = None,
                       usage: Usage | None = None) -> NormalizedResponse:
    """A response that calls tools: ``tool_call_response(("terminal", {"command": "ls"}))``.

    Pass a string instead of a dict to send raw (possibly malformed) argument text.
    """
    tool_calls = [
        ToolCall(id=f"call_{index}_{name}", name=name,
                 arguments=arguments if isinstance(arguments, str) else json.dumps(arguments))
        for index, (name, arguments) in enumerate(calls)
    ]
    return NormalizedResponse(content=content, tool_calls=tool_calls, finish_reason="tool_calls",
                              usage=usage or Usage(10, 5))


def mock_route(model: str = "test-model", provider: str = "mock", **overrides: Any) -> RuntimeRoute:
    """A route that needs no credentials, for constructing an agent in a test."""
    from clite.providers.registry import get_provider

    values: dict[str, Any] = {
        "provider": provider, "model": model, "api_mode": "mock", "base_url": "",
        "profile": get_provider(provider), "source": "test",
    }
    values.update(overrides)
    return RuntimeRoute(**values)


class ScriptedClient:
    """Queue responses (or exceptions, or callables); each ``complete`` call consumes one."""

    def __init__(self, responses: list[Any] | None = None, *, default: NormalizedResponse | None = None) -> None:
        self.responses: list[Any] = list(responses or [])
        self.default = default
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def queue(self, *responses: Any) -> None:
        self.responses.extend(responses)

    def complete(
        self,
        route: RuntimeRoute,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        params: RequestParams | None = None,
        stream: bool = True,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> NormalizedResponse:
        with self._lock:
            self.calls.append({
                "route": route, "messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools),
                "params": params, "stream": stream,
            })
            if self.responses:
                item = self.responses.pop(0)
            elif self.default is not None:
                item = copy.deepcopy(self.default)
            else:
                raise AssertionError(f"ScriptedClient ran out of responses on call {len(self.calls)}")
        if callable(item) and not isinstance(item, NormalizedResponse):
            item = item(messages=messages, tools=tools, cancel=cancel, route=route)
        if isinstance(item, BaseException):
            raise item
        if on_reasoning is not None and item.reasoning:
            on_reasoning(item.reasoning)
        if on_delta is not None and item.content:
            on_delta(item.content)
        return item

    # ── assertions helpers ───────────────────────────────────────────────────────────────

    @property
    def last_messages(self) -> list[dict[str, Any]]:
        return self.calls[-1]["messages"]

    def system_prompts(self) -> list[Any]:
        """The system prompt of every call, to assert it stayed byte-identical."""
        return [call["messages"][0]["content"] for call in self.calls if call["messages"][0]["role"] == "system"]
