"""Prompt-cache breakpoints for providers that take explicit ``cache_control`` markers.

Strategy "system and 3": one breakpoint on the system prompt (stable for the whole session)
and one on each of the last three non-system messages (a rolling window). That is the four
breakpoints the API allows, and it means each request re-reads everything up to the previous
turn from cache.

The markers are applied to a copy at request time. The stored conversation never contains
them, so the same history can be sent to a provider that would reject them.
"""

from __future__ import annotations

import copy
from typing import Any

MAX_BREAKPOINTS = 4


def cache_marker(ttl: str = "5m") -> dict[str, str]:
    marker = {"type": "ephemeral"}
    if ttl == "1h":
        marker["ttl"] = "1h"
    return marker


def _mark(message: dict[str, Any], marker: dict[str, str]) -> None:
    content = message.get("content")
    if message.get("role") == "tool" or content is None or content == "":
        message["cache_control"] = marker  # the transport moves it onto the right block
    elif isinstance(content, str):
        message["content"] = [{"type": "text", "text": content, "cache_control": marker}]
    elif isinstance(content, list) and content:
        last = content[-1]
        if isinstance(last, dict):
            content[-1] = {**last, "cache_control": marker}
        else:
            message["cache_control"] = marker


def apply_cache_markers(messages: list[dict[str, Any]], ttl: str = "5m") -> list[dict[str, Any]]:
    """A deep copy of ``messages`` with up to four cache breakpoints."""
    marked = copy.deepcopy(messages)
    marker = cache_marker(ttl)
    remaining = MAX_BREAKPOINTS
    if marked and marked[0].get("role") == "system":
        _mark(marked[0], marker)
        remaining -= 1
    others = [message for message in marked if message.get("role") != "system"]
    for message in others[-remaining:]:
        _mark(message, marker)
    return marked
