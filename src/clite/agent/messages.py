"""Message hygiene: keep the transcript in a shape every provider accepts.

The stored history can become irregular (an interrupted tool round, a resumed session, a
compression boundary). These helpers repair it on the way out, on a copy; the stored history
is not rewritten.
"""

from __future__ import annotations

import json
import re
from typing import Any

INTERRUPTED_RESULT = json.dumps({"error": "interrupted before this tool ran"})


def content_text(content: Any) -> str:
    """Plain text of a message's content (string or content parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    return ""


def append_to_content(content: Any, addition: str) -> Any:
    """``content`` with ``addition`` appended, whether it is a string or content parts."""
    if not addition:
        return content
    if content is None or content == "":
        return addition
    if isinstance(content, str):
        return f"{content}\n\n{addition}"
    if isinstance(content, list):
        return [*content, {"type": "text", "text": addition}]
    return content


def sanitize_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A copy safe to send: every tool call has a result, and no result lacks its call.

    * A tool result whose call is missing is dropped.
    * A tool call with no result gets a stub result directly after its assistant message.
    * System messages inside the history are dropped (the system prompt is added separately).
    """
    call_ids = {call.get("id") for message in messages for call in message.get("tool_calls") or []}
    answered = {message.get("tool_call_id") for message in messages if message.get("role") == "tool"}
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "tool" and message.get("tool_call_id") not in call_ids:
            continue
        # Bookkeeping keys never leave the process; `provider_data` and `reasoning` stay,
        # because a transport may need them to replay the turn to the same provider.
        cleaned.append({key: value for key, value in message.items() if not key.startswith("_") and key != "timestamp"})
        if role == "assistant":
            missing = [call for call in message.get("tool_calls") or [] if call.get("id") not in answered]
            if missing:
                # Results for the calls that did run follow later in the list; stubs for the
                # rest are inserted after them by the pass below.
                cleaned[-1]["_missing_results"] = [
                    {"role": "tool", "tool_call_id": call.get("id"), "name": (call.get("function") or {}).get("name"),
                     "content": INTERRUPTED_RESULT}
                    for call in missing
                ]
    result: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for message in cleaned:
        if message.get("role") != "tool" and pending:
            result.extend(pending)
            pending = []
        stubs = message.pop("_missing_results", None)
        result.append(message)
        if stubs:
            pending = stubs
    result.extend(pending)
    return result


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def parse_tool_arguments(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """``(arguments, error)``. Tries the common repairs before giving up.

    Models sometimes wrap the JSON in a code fence, leave a trailing comma, or emit nothing at
    all for a tool with no parameters. Those are repaired silently. Anything else is reported
    back to the model as an error result so it can correct the call itself.
    """
    text = (raw or "").strip()
    if not text:
        return {}, None
    candidates = [text, _FENCE.sub("", text).strip()]
    candidates.append(_TRAILING_COMMA.sub(r"\1", candidates[-1]))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, None
        if isinstance(parsed, str):  # double-encoded JSON
            try:
                inner = json.loads(parsed)
            except json.JSONDecodeError:
                break
            if isinstance(inner, dict):
                return inner, None
        break
    return None, f"Invalid tool arguments: expected a JSON object, got: {text[:200]}"
