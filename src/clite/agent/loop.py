"""The turn loop: a short driver over phase functions.

    build_turn_context
    loop:
        begin_iteration      interrupt? budget? steer
        prepare_iteration    pre-flight compression
        call_model           request + retries, rotation, fallback, compress-on-overflow
        normalize_response   empty or truncated responses
        dispatch_response    run tools (then loop) or finish with text
    finalize_turn            always runs

Each phase returns a verdict: ``next`` continues down the list, ``continue`` starts a new
iteration, ``break`` ends the turn. To change the loop's behaviour, change or insert a phase;
this driver should stay this small.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from clite.agent.state import BREAK, NEXT, TurnResult, TurnState, Verdict
from clite.agent.turn.context import build_turn_context
from clite.agent.turn.finalize import finalize_turn
from clite.agent.turn.iteration import begin_iteration, prepare_iteration
from clite.agent.turn.request import call_model
from clite.agent.turn.response import dispatch_response, normalize_response

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent

logger = logging.getLogger("clite.agent.loop")

Phase = Callable[["AIAgent", TurnState], Verdict]

ITERATION_PHASES: tuple[Phase, ...] = (
    begin_iteration,
    prepare_iteration,
    call_model,
    normalize_response,
    dispatch_response,
)


def run_turn(agent: AIAgent, state: TurnState) -> TurnResult:
    try:
        build_turn_context(agent, state)
        running = True
        while running:
            for phase in ITERATION_PHASES:
                verdict = phase(agent, state)
                if verdict.action == BREAK:
                    running = False
                    break
                if verdict.action != NEXT:
                    break  # "continue": begin a new iteration
    except Exception as exc:  # noqa: BLE001 - a bug in a phase must not take the surface down
        logger.exception("turn failed in session %s", agent.session_id)
        state.error = f"internal error: {type(exc).__name__}: {exc}"
        state.exit_reason = "internal_error"
    return finalize_turn(agent, state)
