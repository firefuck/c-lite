"""Phase: set the turn up. Runs once, before the first iteration."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

    # Context that applies to this turn only is collected here and attached to the user
    # message on the wire. It never enters the system prompt and is never stored.
    parts: list[str] = []
    if agent.memory is not None:
        recalled = agent.memory.prefetch(user_text, agent.session_id)
        if recalled:
            parts.append(recalled)
    if has_hook("pre_llm_call"):
        for result in invoke_hook(
            "pre_llm_call", session_id=agent.session_id, user_message=user_text, platform=agent.platform,
            model=agent.route.model, is_first_turn=first_turn,
        ):
            text = result.get("context") if isinstance(result, dict) else result if isinstance(result, str) else None
            if text:
                parts.append(str(text))
    state.turn_context = "\n\n".join(parts)

    agent.append_message({"role": "user", "content": state.user_message})
