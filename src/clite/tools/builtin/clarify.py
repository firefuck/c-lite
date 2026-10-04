"""``clarify``: ask the user a question and wait for the answer."""

from __future__ import annotations

from typing import Any

from clite.tools.context import ToolContext
from clite.tools.registry import registry, tool_error, tool_result

MAX_CHOICES = 4

CLARIFY_SCHEMA = {
    "name": "clarify",
    "description": (
        "Ask the user a question when you cannot proceed without their decision: the request is ambiguous "
        "in a way that changes the work, or a choice is theirs to make. Offer up to 4 choices when the "
        "options are known; the user can always type their own answer. Do not use it for things you can "
        "find out yourself, or to ask permission for routine steps."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question, phrased so it can be answered briefly."},
            "choices": {"type": "array", "items": {"type": "string"}, "description": "Up to 4 suggested answers."},
        },
        "required": ["question"],
    },
}


def clarify_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    question = str(args.get("question") or "").strip()
    if not question:
        return tool_error("question is required")
    choices = [str(choice) for choice in (args.get("choices") or []) if str(choice).strip()][:MAX_CHOICES]
    ask = getattr(getattr(ctx, "callbacks", None), "clarify", None)
    if ask is None:
        return tool_error(
            "There is no user to ask in this context. Choose the most reasonable option yourself, "
            "say which one you chose, and continue."
        )
    try:
        answer = ask(question, choices)
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"could not ask the user: {exc}")
    if answer is None or not str(answer).strip():
        return tool_result(question=question, answer="", note="The user did not answer. Use your best judgment.")
    return tool_result(question=question, answer=str(answer).strip())


registry.register("clarify", "clarify", CLARIFY_SCHEMA, clarify_tool, emoji="❓")
