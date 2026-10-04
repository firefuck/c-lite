"""Delegation: run subagents with their own context and return only their reports.

A child starts with an empty conversation. It sees the goal and the context the parent wrote
for it, nothing else, and the parent sees only the child's final report. That is the point:
the intermediate tool output never enters the parent's context window.

Limits, all from config (``delegation.*``): how deep delegation may nest, how many children
run at once, and how many iterations each child gets.
"""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from clite.agent.callbacks import AgentCallbacks
from clite.core.config import get_path
from clite.core.errors import CliteError
from clite.plugins.hooks import invoke_hook
from clite.providers.runtime import resolve_runtime_provider
from clite.tools.toolsets import resolve_toolsets

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent

logger = logging.getLogger("clite.agent.delegation")

# A child never gets these, whatever toolsets were requested: no recursive delegation beyond
# the depth limit, no questions to the user, no writes to shared memory, no scheduling.
BLOCKED_TOOLS = frozenset({"delegate_task", "clarify", "memory", "cronjob"})
DEFAULT_CHILD_TOOLSETS = ["terminal", "file", "web", "skills", "session_search", "todo"]
MAX_TASKS_PER_CALL = 8


def _child_toolsets(parent: AIAgent, requested: list[str] | None) -> tuple[list[str], list[str]]:
    """``(enabled, disabled)`` for a child: what was asked for, limited to what the parent has."""
    wanted = requested or DEFAULT_CHILD_TOOLSETS
    allowed = [name for name in wanted if set(resolve_toolsets([name])) & parent.tool_names]
    blocked_toolsets = ["delegation", "clarify", "memory", "cronjob"]
    return allowed, blocked_toolsets


def _child_route(parent: AIAgent):
    provider = str(get_path(parent.config, "delegation.provider", "") or "")
    model = str(get_path(parent.config, "delegation.model", "") or "")
    if not provider and not model:
        return parent.route
    try:
        if provider:
            return resolve_runtime_provider(provider, model or None, config=parent.config)
        return parent.route.with_model(model)
    except CliteError as exc:
        logger.warning("delegation route is unusable (%s); children use the parent's model", exc)
        return parent.route


def _run_child(parent: AIAgent, index: int, task: dict[str, Any]) -> dict[str, Any]:
    from clite.agent.agent import AIAgent

    goal = str(task.get("goal") or "").strip()
    context = str(task.get("context") or "").strip()
    enabled, disabled = _child_toolsets(parent, task.get("toolsets"))
    started = time.monotonic()

    def relay(event: str, **payload: Any) -> None:
        parent.callbacks.emit("on_subagent", event, {"index": index, "goal": goal[:120], **payload})

    child = AIAgent(
        _child_route(parent),
        platform=parent.platform, cwd=parent.cwd, config=parent.config, session_db=parent.db,
        persist=parent.db is not None, client=parent.client, parent=parent,
        enabled_toolsets=enabled, disabled_toolsets=disabled,
        max_turns=int(get_path(parent.config, "delegation.max_iterations", 50) or 50),
        skip_memory=True, approval_mode=parent.approval_mode, stream=False,
        callbacks=AgentCallbacks(
            on_tool_start=lambda call_id, name, args: relay("tool", tool=name),
            approve=parent.callbacks.approve,  # dangerous commands still need the user's yes
        ),
    )
    parent.register_child(child)
    relay("start")
    invoke_hook("subagent_start", parent_session_id=parent.session_id, session_id=child.session_id, goal=goal)
    try:
        prompt = f"# Task\n\n{goal}" + (f"\n\n# Context\n\n{context}" if context else "")
        result = child.run_conversation(prompt)
        report = {
            "index": index,
            "goal": goal,
            "status": "completed" if result.completed else "interrupted" if result.interrupted else "failed",
            "summary": result.final_response,
            "api_calls": result.api_calls,
            "duration_seconds": round(time.monotonic() - started, 1),
            "session_id": child.session_id,
        }
        if result.error:
            report["error"] = result.error
    except Exception as exc:  # noqa: BLE001 - one failed child must not fail its siblings
        logger.warning("subagent %d crashed", index, exc_info=True)
        report = {"index": index, "goal": goal, "status": "failed", "summary": "", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        parent.unregister_child(child)
        child.close("subagent_done")
    relay("complete", status=report["status"])
    invoke_hook("subagent_stop", parent_session_id=parent.session_id, session_id=child.session_id,
                status=report["status"])
    return report


def delegate(parent: AIAgent, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Run ``tasks`` (each ``{"goal", "context"?, "toolsets"?}``) and return their reports."""
    max_depth = int(get_path(parent.config, "delegation.max_spawn_depth", 1) or 1)
    if parent.depth >= max_depth:
        return {"error": f"Delegation depth limit reached ({max_depth}). Do this task yourself."}
    tasks = [task for task in tasks if isinstance(task, dict) and str(task.get("goal") or "").strip()]
    if not tasks:
        return {"error": "Provide a goal, or a tasks list where each task has a goal."}
    if len(tasks) > MAX_TASKS_PER_CALL:
        return {"error": f"At most {MAX_TASKS_PER_CALL} tasks per call; split the work into several calls."}
    workers = max(1, min(len(tasks), int(get_path(parent.config, "delegation.max_concurrent_children", 3) or 3)))
    if len(tasks) == 1:
        reports = [_run_child(parent, 0, tasks[0])]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clite-subagent") as pool:
            futures = [pool.submit(contextvars.copy_context().run, _run_child, parent, index, task)
                       for index, task in enumerate(tasks)]
            reports = [future.result() for future in futures]
    return {"results": reports, "completed": sum(1 for report in reports if report["status"] == "completed"),
            "total": len(reports)}
