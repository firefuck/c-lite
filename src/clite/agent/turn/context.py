"""Phase: set the turn up. Runs once, before the first iteration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clite.agent.messages import content_text
from clite.agent.state import TurnState
from clite.plugins.hooks import has_hook, invoke_hook

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent


def build_turn_context(agent: AIAgent, state: TurnState) -> None:
    agent.interrupt_event.clear()
    agent.budget.reset()
    first_turn = not agent.messages
    agent.ensure_session()
    state.first_message_index = len(agent.messages)
    user_text = content_text(state.user_message)

    # Context gathered for this turn (recalled memory, hook output, reminders) travels with
    # the user message, never in the system prompt. It is stored beside the message as
    # ``turn_context``: the user's own words stay clean for display and search, and every
    # later request sends this message exactly as it was first sent. Sending it once and then
    # dropping it would change the conversation's prefix, which costs the prompt cache and
    # makes providers that sign their reasoning blocks reject the next request.
    parts: list[str] = []
    if agent.memory is not None:
        recalled = agent.memory.prefetch(user_text, agent.session_id)
        if recalled:
            parts.append(recalled)
        if "memory" in agent.tool_names:  # a reminder is only useful to a model that can act on it
            nudge = agent.memory.turn_nudge()
            if nudge:
                parts.append(nudge)
    if has_hook("pre_llm_call"):
        for result in invoke_hook(
            "pre_llm_call", session_id=agent.session_id, user_message=user_text, platform=agent.platform,
            model=agent.route.model, is_first_turn=first_turn,
        ):
            text = result.get("context") if isinstance(result, dict) else result if isinstance(result, str) else None
            if text:
                parts.append(str(text))
    message: dict[str, Any] = {"role": "user", "content": state.user_message}
    if parts:
        message["turn_context"] = "\n\n".join(parts)
    agent.append_message(message)
