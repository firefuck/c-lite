"""Rough token estimates.

Used only to decide *when* to compress, before the provider has reported real usage. Four
characters per token is close enough for that; exact counts come from the API response.
"""

from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 4
_PER_MESSAGE_OVERHEAD = 4


def estimate_text_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def estimate_message_tokens(message: dict[str, Any]) -> int:
    content = message.get("content")
    size = len(content) if isinstance(content, str) else len(json.dumps(content, default=str)) if content else 0
    if message.get("tool_calls"):
        size += len(json.dumps(message["tool_calls"], default=str))
    return size // CHARS_PER_TOKEN + _PER_MESSAGE_OVERHEAD


def estimate_messages_tokens(messages: list[dict[str, Any]], *, system_prompt: str = "",
                             tools: list[dict[str, Any]] | None = None) -> int:
    total = sum(estimate_message_tokens(message) for message in messages)
    total += estimate_text_tokens(system_prompt)
    if tools:
        total += len(json.dumps(tools, default=str)) // CHARS_PER_TOKEN
    return total
