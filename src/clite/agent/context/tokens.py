"""Token estimates, anchored to the last number the provider reported.

Estimates decide *when* to compress, before the provider has reported real usage for the new
messages. Four characters per token is close enough for that. Once a response has carried a
real ``prompt_tokens`` count, that number is the anchor: everything it already measured is
reused exactly, and only the messages appended after it are estimated.
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
    size = (
        len(content) if isinstance(content, str) else len(json.dumps(content, default=str)) if content else 0
    )
    if message.get("tool_calls"):
        size += len(json.dumps(message["tool_calls"], default=str))
    return size // CHARS_PER_TOKEN + _PER_MESSAGE_OVERHEAD


def estimate_messages_tokens(
    messages: list[dict[str, Any]], *, system_prompt: str = "", tools: list[dict[str, Any]] | None = None
) -> int:
    total = sum(estimate_message_tokens(message) for message in messages)
    total += estimate_text_tokens(system_prompt)
    if tools:
        total += len(json.dumps(tools, default=str)) // CHARS_PER_TOKEN
    return total


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    *,
    system_prompt: str = "",
    tools: list[dict[str, Any]] | None = None,
    anchor_tokens: int = 0,
    anchor_message_count: int = 0,
) -> int:
    """The prompt size, reusing the provider's last number where it still applies.

    ``anchor_tokens`` is the last ``prompt_tokens`` the provider reported and
    ``anchor_message_count`` is how many messages the request carried when it did. Those
    counts already include the system prompt and tools as they were then, so only the messages
    after ``anchor_message_count`` are estimated on top. With no anchor this is a plain
    estimate, and ``system_prompt``/``tools`` are counted as usual.

    The anchor is trusted only when it is at least as large as the messages it claims to cover
    — otherwise the number does not describe this transcript (a stale count, or a provider that
    reported something else) and the plain estimate is the safer answer.
    """
    if anchor_tokens and 0 < anchor_message_count <= len(messages):
        covered = sum(estimate_message_tokens(message) for message in messages[:anchor_message_count])
        if anchor_tokens >= covered:
            trailing = sum(estimate_message_tokens(message) for message in messages[anchor_message_count:])
            return anchor_tokens + trailing
    return estimate_messages_tokens(messages, system_prompt=system_prompt, tools=tools)
