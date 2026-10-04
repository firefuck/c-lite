"""Phases after the model answered: validate the response, then act on it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clite.agent.state import BREAK, CONTINUE, PROCEED, TurnState, Verdict
from clite.agent.tool_executor import run_tool_round
from clite.plugins.hooks import first_result, has_hook, invoke_hook

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent

MAX_EMPTY_RETRIES = 2
MAX_LENGTH_CONTINUATIONS = 3
CONTINUE_REQUEST = (
    "[Your reply was cut off by the output limit. Continue from exactly where it stopped. "
    "Do not repeat or summarise what you already wrote.]"
)
EMPTY_RESPONSE_TEXT = "(The model returned an empty response. Try rephrasing, or switch models with /model.)"


def normalize_response(agent: AIAgent, state: TurnState) -> Verdict:
    response = state.response
    assert response is not None
    text = (response.content or "").strip()

    if not response.tool_calls and not text:
        if state.empty_retries < MAX_EMPTY_RETRIES:
            state.empty_retries += 1
            agent.budget.refund()
            agent.callbacks.emit("on_status", "retry", f"empty response from the model, retrying ({state.empty_retries}/{MAX_EMPTY_RETRIES})")
            return Verdict(CONTINUE, "empty_response")
        message = {"role": "assistant", "content": EMPTY_RESPONSE_TEXT, "finish_reason": "stop"}
        agent.append_message(message)
        agent.callbacks.emit("on_message", message)
        state.final_response = state.partial_text + EMPTY_RESPONSE_TEXT
        state.error = "empty_response"
        state.exit_reason = "empty_response"
        return Verdict(BREAK, "empty_response")

    if response.finish_reason == "length" and not response.tool_calls and state.length_continuations < MAX_LENGTH_CONTINUATIONS:
        # Keep the partial text and ask for the rest. The pieces are joined into one final
        # response; the transcript keeps them as they really happened.
        state.length_continuations += 1
        state.partial_text += response.content or ""
        agent.append_message(response.to_assistant_message())
        agent.append_message({"role": "user", "content": CONTINUE_REQUEST})
        agent.callbacks.emit("on_status", "warning", "response hit the output limit, continuing")
        return Verdict(CONTINUE, "length")
    return PROCEED


def dispatch_response(agent: AIAgent, state: TurnState) -> Verdict:
    response = state.response
    assert response is not None

    if response.tool_calls:
        message = response.to_assistant_message()
        # Durable before any tool runs: if the process dies mid-tool, the transcript still
        # shows what was attempted.
        agent.append_message(message)
        agent.callbacks.emit("on_message", message)
        for result in run_tool_round(agent, state, response.tool_calls):
            agent.append_message(result)
        if agent.interrupt_event.is_set():
            state.interrupted = True
            state.exit_reason = "interrupted"
            return Verdict(BREAK, "interrupted")
        return Verdict(CONTINUE, "tools")

    text = response.content or ""
    if has_hook("transform_llm_output"):
        replacement = first_result(
            invoke_hook("transform_llm_output", session_id=agent.session_id, text=text, platform=agent.platform,
                        model=state.route.model)
        )
        if replacement is not None:
            text = replacement
    message = response.to_assistant_message()
    message["content"] = text
    agent.append_message(message)
    agent.callbacks.emit("on_message", message)
    state.final_response = state.partial_text + text
    state.completed = True
    state.exit_reason = "completed"
    return Verdict(BREAK, "completed")
