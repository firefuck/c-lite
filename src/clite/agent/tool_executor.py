"""Run one round of tool calls and return the tool messages, in the model's order.

Parallelism policy (decided per batch, from each tool's registered ``parallel`` setting):

* a batch runs in parallel only if *every* call is ``safe`` (read-only) or ``path`` (scoped
  to a file), and no two ``path`` calls name the same file;
* anything else runs sequentially, in order. One interactive or side-effecting tool makes the
  whole batch sequential, because the model may have ordered the calls deliberately.

Results always come back in the original order, whatever order they finished in.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from clite.agent.messages import parse_tool_arguments
from clite.core.config import get_path
from clite.providers.transports.types import ToolCall
from clite.tools.context import ToolContext
from clite.tools.dispatch import handle_function_call
from clite.tools.registry import PARALLEL_NEVER, PARALLEL_PATH, registry, tool_error

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent
    from clite.agent.state import TurnState

logger = logging.getLogger("clite.agent.tools")

CANCELLED_RESULT = json.dumps({"error": "cancelled: the user interrupted before this tool ran"})


def can_run_in_parallel(calls: list[tuple[ToolCall, dict[str, Any] | None]], resolve_path=None) -> bool:
    if len(calls) < 2:
        return False
    seen_paths: set[str] = set()
    for call, args in calls:
        entry = registry.get(call.name)
        if entry is None or args is None or entry.parallel == PARALLEL_NEVER:
            return False
        if entry.parallel == PARALLEL_PATH:
            for name in entry.path_args:
                value = args.get(name)
                if not isinstance(value, str) or not value:
                    return False
                key = resolve_path(value) if resolve_path else value
                if key in seen_paths:
                    return False
                seen_paths.add(key)
    return True


def _context_for(agent: AIAgent, state: TurnState, call: ToolCall) -> ToolContext:
    return ToolContext(
        session_id=agent.session_id, task_id=state.task_id, tool_call_id=call.id, platform=agent.platform,
        cwd=agent.cwd, agent=agent, callbacks=agent.callbacks, config=agent.config, interrupt=agent.interrupt_event,
        approval_mode=agent.approval_mode, enabled_tools=agent.tool_names, depth=agent.depth,
    )


def _run_one(agent: AIAgent, state: TurnState, call: ToolCall, args: dict[str, Any] | None, error: str | None) -> str:
    if error is not None:
        return tool_error(error)
    if agent.interrupt_event.is_set():
        return CANCELLED_RESULT
    assert args is not None
    agent.callbacks.emit("on_tool_start", call.id, call.name, args)
    started = time.monotonic()
    result = None
    if agent.memory is not None:
        result = agent.memory.handle_provider_tool(call.name, args, session_id=agent.session_id)
    if result is None:
        result = handle_function_call(call.name, args, _context_for(agent, state, call))
    agent.callbacks.emit("on_tool_complete", call.id, call.name, args, result, time.monotonic() - started)
    return result


def run_tool_round(agent: AIAgent, state: TurnState, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    parsed = [(call, *parse_tool_arguments(call.arguments)) for call in tool_calls]
    pairs = [(call, args) for call, args, _error in parsed]

    def resolve(path: str) -> str:
        from clite.tools.environments import get_environment

        return get_environment(state.task_id, cwd=agent.cwd).resolve_path(path)

    if can_run_in_parallel(pairs, resolve):
        workers = min(len(parsed), int(get_path(agent.config, "agent.max_tool_workers", 8) or 8))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clite-tool") as pool:
            futures = [
                # Each worker gets a copy of the context so profile and secret scopes follow it.
                pool.submit(contextvars.copy_context().run, _run_one, agent, state, call, args, error)
                for call, args, error in parsed
            ]
            results = [future.result() for future in futures]
    else:
        results = [_run_one(agent, state, call, args, error) for call, args, error in parsed]

    messages = [
        {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result}
        for (call, _args, _error), result in zip(parsed, results, strict=True)
    ]
    remaining = agent.budget.remaining
    if messages and remaining is not None and agent.budget.limit and remaining <= max(1, agent.budget.limit // 10):
        # Tell the model while it can still act on it, on the newest tool result (never in
        # the system prompt, which must stay byte-stable).
        messages[-1]["content"] += (
            f"\n\n[BUDGET: {remaining} tool-calling iteration(s) left in this turn. "
            "Wrap up and give the user your answer.]"
        )
    return messages
