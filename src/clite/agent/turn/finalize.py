"""Phase: close the turn. Always runs, including after an error or an interrupt."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from clite.agent.messages import INTERRUPTED_RESULT, content_text
from clite.agent.state import TurnResult, TurnState
from clite.plugins.hooks import has_hook, invoke_hook

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent

logger = logging.getLogger("clite.agent.turn")


def close_open_tool_calls(agent: AIAgent) -> None:
    """Give every unanswered tool call a result, so the stored transcript is always one a
    provider will accept on the next turn."""
    answered = {message.get("tool_call_id") for message in agent.messages if message.get("role") == "tool"}
    for message in list(agent.messages):
        for call in message.get("tool_calls") or []:
            if call.get("id") not in answered:
                agent.append_message({
                    "role": "tool", "tool_call_id": call.get("id"),
                    "name": (call.get("function") or {}).get("name"), "content": INTERRUPTED_RESULT,
                })
                answered.add(call.get("id"))


def finalize_turn(agent: AIAgent, state: TurnState) -> TurnResult:
    close_open_tool_calls(agent)
    if state.final_response is None:
        if state.error and not state.interrupted:
            state.final_response = state.partial_text or f"The model call failed: {state.error}"
        else:
            state.final_response = state.partial_text

    user_text = content_text(state.user_message)
    if state.completed and agent.memory is not None:
        agent.memory.after_turn(user_text, state.final_response, agent.session_id)
    if has_hook("post_llm_call"):
        invoke_hook(
            "post_llm_call", session_id=agent.session_id, user_message=user_text,
            assistant_response=state.final_response, platform=agent.platform, model=state.route.model,
            completed=state.completed, interrupted=state.interrupted, api_calls=state.api_calls,
        )
    if state.completed:
        agent.maybe_generate_title(user_text)

    return TurnResult(
        final_response=state.final_response,
        completed=state.completed,
        interrupted=state.interrupted,
        error=state.error,
        exit_reason=state.exit_reason,
        api_calls=state.api_calls,
        usage=state.usage,
        session_id=agent.session_id,
        model=state.route.model,
        provider=state.route.provider,
        duration=time.monotonic() - state.started_at,
        messages=list(agent.messages[state.first_message_index:]),
    )
