"""The trajectory format: one session as the steps a model walked through.

``clite sessions export --format trajectory`` writes this. It exists for evaluation and
training: the prompts, the tool calls and their results, in order, with nothing a consumer
would have to understand the agent to read. Three things are deliberately absent —
``provider_data`` (opaque blocks a provider asked back), the storage's bookkeeping fields, and
any known credential value, which is redacted on the way out.

Everything here is a pure function of one session row and its messages.
"""

from __future__ import annotations

import json
from typing import Any

from clite.agent.messages import content_text, is_internal
from clite.core.redact import redact

FORMAT = "clite-trajectory/1"
SESSION_KEYS = ("id", "source", "model", "provider", "title", "started_at")


def build_trajectory(session: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The exported document: the session, then one step per message the user could see.

    Messages the agent wrote to itself (``display_kind: internal``) and system messages are
    left out; the system prompt is rebuilt per turn from files on disk and is not part of the
    conversation. Image attachments are reduced to their text: the export carries no image
    bytes. Everything that is text is redacted, the session title included: the title is
    written from the user's first message, which is exactly where a pasted key ends up.
    """
    steps = [step for step in map(_step, messages) if step is not None]
    return {"format": FORMAT, "session": _session(session), "steps": steps}


def _session(session: dict[str, Any]) -> dict[str, Any]:
    return {key: redact(text) if isinstance(text := session.get(key), str) else text for key in SESSION_KEYS}


def _step(message: dict[str, Any]) -> dict[str, Any] | None:
    role = message.get("role")
    if role in (None, "system") or is_internal(message):
        return None
    step: dict[str, Any] = {"role": role, "content": redact(content_text(message.get("content")))}
    if message.get("timestamp"):
        step["timestamp"] = message["timestamp"]
    if message.get("turn_context"):
        # What the agent added to this turn (recalled memory, hook output). Kept apart from
        # ``content`` so a consumer can use the prompt alone.
        step["context"] = redact(str(message["turn_context"]))
    if role == "assistant":
        calls = [_call(call) for call in message.get("tool_calls") or []]
        if calls:
            step["tool_calls"] = calls
    elif role == "tool":
        step["tool_call_id"] = message.get("tool_call_id")
        step["name"] = message.get("name")
    return step


def _call(call: dict[str, Any]) -> dict[str, Any]:
    """One tool call: its id, name, and arguments as an object when they are JSON."""
    function = call.get("function") or {}
    raw = redact(str(function.get("arguments") or ""))
    try:
        arguments: Any = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        arguments = {"unparsed": raw}
    return {"id": call.get("id"), "name": function.get("name"), "arguments": arguments}
