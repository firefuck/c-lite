"""Phases that open each iteration: interrupt and budget checks, then pre-flight compression."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from clite.agent.context.tokens import estimate_messages_tokens
from clite.agent.messages import append_to_content
from clite.agent.state import BREAK, PROCEED, TurnState, Verdict
from clite.core.config import get_path
from clite.providers.transports.types import RequestParams

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent

logger = logging.getLogger("clite.agent.turn")

WRAP_UP_REQUEST = (
    "[You have reached the limit for this turn ({reason}). Do not call any tools. Tell the user what you "
    "accomplished, what is left, and what blocked you, if anything.]"
)
WRAP_UP_FALLBACK = "I reached the limit for this turn ({reason}) before finishing. Ask me to continue and I will pick up where I stopped."


def _wrap_up(agent: AIAgent, state: TurnState, reason: str) -> Verdict:
    """The budget is spent: one last call without tools, so the user gets a real status
    instead of a turn that just stops."""
    from clite.agent.turn.request import assemble_api_messages

    state.exit_reason = "budget_exhausted"
    request = [*assemble_api_messages(agent, state), {"role": "user", "content": WRAP_UP_REQUEST.format(reason=reason)}]
    try:
        response = agent.client.complete(
            state.route, request, None, stream=agent.stream, on_delta=agent.callbacks.on_delta,
            cancel=agent.interrupt_event, params=RequestParams(session_id=agent.session_id),
        )
        text = (response.content or "").strip() or WRAP_UP_FALLBACK.format(reason=reason)
        agent.record_usage(state, response.usage)
    except Exception as exc:  # noqa: BLE001 - the turn must still end cleanly
        logger.warning("wrap-up call failed: %s", exc)
        text = WRAP_UP_FALLBACK.format(reason=reason)
    message = {"role": "assistant", "content": text, "finish_reason": "stop"}
    agent.append_message(message)
    agent.callbacks.emit("on_message", message)
    state.final_response = state.partial_text + text
    return Verdict(BREAK, reason)


def _apply_steer(agent: AIAgent) -> None:
    """Fold queued ``/steer`` text into the newest message the model has not seen yet.

    Steering never interrupts: it rides on the last tool result (or the user message, on the
    first iteration), so the cached prefix before it stays valid.
    """
    steer = agent.take_steer()
    if not steer or not agent.messages:
        return
    note = "[The user adds, while you work: " + " ".join(steer) + "]"
    last = agent.messages[-1]
    if last.get("role") in ("tool", "user"):
        agent.replace_last_content(append_to_content(last.get("content"), note))
    else:
        agent.append_message({"role": "user", "content": note})


def begin_iteration(agent: AIAgent, state: TurnState) -> Verdict:
    if agent.interrupt_event.is_set():
        state.interrupted = True
        state.exit_reason = "interrupted"
        return Verdict(BREAK, "interrupted")
    limit = agent.run_budget_seconds
    if limit and time.monotonic() - state.started_at > limit:
        return _wrap_up(agent, state, "time budget")
    if not agent.budget.consume():
        return _wrap_up(agent, state, "iteration budget")
    state.iteration += 1
    _apply_steer(agent)
    agent.callbacks.emit("on_step", state.iteration)
    return PROCEED


def prepare_iteration(agent: AIAgent, state: TurnState) -> Verdict:
    """Compress before calling the model when the conversation is already near the window.

    Waiting for the provider to reject the request would cost a failed call and, on some
    providers, a confusing error instead of a clean "context too long".
    """
    if not get_path(agent.config, "compression.enabled", True):
        return PROCEED
    if state.compression_attempts >= int(get_path(agent.config, "compression.max_attempts", 3)):
        return PROCEED
    engine = agent.context_engine
    estimate = max(
        engine.last_prompt_tokens,
        estimate_messages_tokens(agent.messages, system_prompt=agent.system_prompt or "", tools=agent.tools),
    )
    if engine.should_compress(estimate):
        agent.compress_context(state, reason="threshold")
    return PROCEED
