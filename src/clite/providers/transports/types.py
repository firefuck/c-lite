"""Provider-neutral shapes the agent loop works with.

Every wire protocol is normalised into these on the way in, so the loop never branches on
which provider answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # the raw JSON text the model produced; parsed (and repaired) by the loop

    def to_message_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class Usage:
    """Token counts for one call. ``input_tokens`` excludes cached tokens."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Everything the model read: what the context window is measured against."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens


@dataclass
class NormalizedResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # stop | tool_calls | length | content_filter
    reasoning: str | None = None
    usage: Usage | None = None
    model: str = ""
    # Opaque data the same provider needs back on the next request (e.g. signed thinking
    # blocks). Stored with the assistant message, never shown, never sent to another provider.
    provider_data: dict[str, Any] | None = None

    def to_assistant_message(self) -> dict[str, Any]:
        """The response as an internal-format assistant message."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [call.to_message_dict() for call in self.tool_calls]
        if self.reasoning:
            message["reasoning"] = self.reasoning
        if self.provider_data:
            message["provider_data"] = self.provider_data
        message["finish_reason"] = self.finish_reason
        return message


@dataclass
class RequestParams:
    """Per-call knobs, already resolved from config by the caller."""

    max_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str = ""
    session_id: str = ""
    timeout: float = 600.0
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass
class HttpRequest:
    url: str
    headers: dict[str, str]
    body: dict[str, Any]
