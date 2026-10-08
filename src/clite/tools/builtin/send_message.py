"""``send_message``: let the agent message a chat on a connected platform.

Offered only when a gateway is running in this process (``check_fn``), so the classic CLI and
one-shot runs never see it. The destination is not free-form: the runner allows only the chat
the conversation came from, a platform's home channel, and the entries in
``gateway.send_targets``. The agent cannot reach an arbitrary chat id.
"""

from __future__ import annotations

from typing import Any

from clite.tools.context import ToolContext
from clite.tools.registry import PARALLEL_NEVER, registry, tool_error, tool_result

SEND_MESSAGE_SCHEMA = {
    "name": "send_message",
    "description": (
        "Send a message to a chat on a connected platform, for example to tell the user "
        "something later on Telegram while working elsewhere. The target is a platform name "
        "(its configured home channel) or 'platform:chat id'. Allowed destinations are the "
        "current conversation, a home channel, and any chat listed in gateway.send_targets; "
        "anything else is refused. Use this to reach the user, not to spam other chats."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "A platform name (home channel) or 'platform:chat id'.",
            },
            "text": {"type": "string", "description": "The message to send."},
        },
        "required": ["target", "text"],
    },
}


def _gateway_available() -> bool:
    from clite.gateway.runner import active_runner

    return active_runner() is not None


def send_message_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    from clite.core.errors import CliteError
    from clite.gateway.runner import active_runner

    runner = active_runner()
    if runner is None:
        return tool_error("No gateway is running, so there is no chat to send to. Tell the user instead.")
    target = str(args.get("target") or "").strip()
    text = str(args.get("text") or "").strip()
    if not target:
        return tool_error("target is required: a platform name or 'platform:chat id'")
    if not text:
        return tool_error("text is required and cannot be empty")
    origin = getattr(getattr(ctx, "agent", None), "session_meta", None) or {}
    origin_source = origin.get("origin") if isinstance(origin, dict) else None
    try:
        destination = runner.send_to(target, text, origin=origin_source)
    except CliteError as exc:
        return tool_error(str(exc))
    return tool_result(delivered=True, destination=destination)


registry.register(
    "send_message",
    "messaging",
    SEND_MESSAGE_SCHEMA,
    send_message_tool,
    check_fn=_gateway_available,
    emoji="✉️",
    parallel=PARALLEL_NEVER,
)
