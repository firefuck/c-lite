"""Delegation: run subagents with their own context and return only their reports.

A child starts with an empty conversation. It sees the goal and the context the parent wrote
for it, nothing else, and the parent sees only the child's final report. That is the point:
the intermediate tool output never enters the parent's context window.

Three shapes, all from config (``delegation.*``):

* **Synchronous.** ``delegate(parent, tasks)`` runs the tasks and returns their reports.
* **Background.** ``delegate(parent, tasks, background=True)`` returns at once with an id per
  task; each finished report is handed back to the parent as a note on the next tool result
  (or on the next user message), never by rewriting a message that was already sent.
* **Nested.** With ``delegation.max_spawn_depth`` above 1 a child that is not yet at the
  bottom may delegate too, so a middle child can orchestrate grandchildren.
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from clite.agent.callbacks import AgentCallbacks
from clite.core.config import get_path
from clite.core.errors import CliteError
from clite.core.threads import start_thread
from clite.plugins.hooks import invoke_hook
from clite.providers.model_switch import parse_model_input
from clite.providers.runtime import resolve_runtime_provider
from clite.tools.toolsets import resolve_toolsets

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent
    from clite.providers.runtime import RuntimeRoute

logger = logging.getLogger("clite.agent.delegation")

# A child never gets these, whatever toolsets were requested: no questions to the user, no
# writes to shared memory, no scheduling. ``delegate_task`` is blocked only at the bottom of
# the depth budget, where a further delegation would be refused anyway.
CHILD_BLOCKED_TOOLS = frozenset({"clarify", "memory", "cronjob"})
DEFAULT_CHILD_TOOLSETS = ["terminal", "file", "web", "skills", "session_search", "todo"]
MAX_TASKS_PER_CALL = 8
# How much of a tool's arguments the parent sees in a progress event. Enough to tell a
# search from a write, short enough never to bloat an event stream.
ARGS_PREVIEW_CHARS = 160


def _preview_args(args: Any) -> str:
    """A one-line, redaction-safe rendering of a tool call's arguments for progress events."""
    if not isinstance(args, dict):
        return ""
    from clite.core.redact import redact

    parts = []
    for key, value in args.items():
        text = value if isinstance(value, str) else repr(value)
        text = str(text).replace("\n", " ").strip()
        if len(text) > 60:
            text = text[:57] + "…"
        parts.append(f"{key}={text}")
    joined = ", ".join(parts)
    if len(joined) > ARGS_PREVIEW_CHARS:
        joined = joined[: ARGS_PREVIEW_CHARS - 1] + "…"
    return redact(joined)


def _child_toolsets(parent: AIAgent, requested: list[str] | None) -> tuple[list[str], list[str]]:
    """``(enabled, disabled)`` for a child: what was asked for, limited to what the parent has."""
    wanted = requested or DEFAULT_CHILD_TOOLSETS
    allowed = [name for name in wanted if set(resolve_toolsets([name])) & parent.tool_names]
    # A middle child needs a toolset that offers delegate_task; the default set does not.
    if (
        may_delegate(parent)
        and "delegation" not in allowed
        and set(resolve_toolsets(["delegation"])) & parent.tool_names
    ):
        allowed.append("delegation")
    blocked_toolsets = [*parent.disabled_toolsets, "clarify", "memory", "cronjob"]
    return allowed, blocked_toolsets


def _max_depth(parent: AIAgent) -> int:
    return int(get_path(parent.config, "delegation.max_spawn_depth", 1) or 1)


def may_delegate(parent: AIAgent) -> bool:
    """Whether an agent one level below ``parent`` could still delegate further."""
    return parent.depth + 1 < _max_depth(parent)


def _child_route(parent: AIAgent, model: str | None = None) -> RuntimeRoute:
    """The route a child runs on.

    A per-task ``model`` (``<model>``, ``<provider>:<model>``, or a provider alias) wins over
    ``delegation.model``/``delegation.provider``, which in turn beat the parent's own route.
    A model whose provider is not configured raises, so the caller can turn it into an error
    for that task alone.
    """
    requested = (model or "").strip()
    if requested:
        provider, name = parse_model_input(requested, parent.config)
        if provider:
            # A named provider must be configured; an unresolvable one raises for this task.
            return resolve_runtime_provider(provider, name, config=parent.config)
        # A bare model name keeps the parent's provider and endpoint.
        return parent.route.with_model(name or requested)

    provider = str(get_path(parent.config, "delegation.provider", "") or "")
    configured_model = str(get_path(parent.config, "delegation.model", "") or "")
    if not provider and not configured_model:
        return parent.route
    try:
        if provider:
            return resolve_runtime_provider(provider, configured_model or None, config=parent.config)
        return parent.route.with_model(configured_model)
    except CliteError as exc:
        logger.warning("delegation route is unusable (%s); children use the parent's model", exc)
        return parent.route


def _build_child(parent: AIAgent, task: dict[str, Any], progress: _Progress) -> AIAgent:
    """A child agent for ``task``, pinned to its route and toolsets. Raises on a bad route."""
    from clite.agent.agent import AIAgent

    enabled, disabled = _child_toolsets(parent, task.get("toolsets"))
    route = _child_route(parent, task.get("model"))
    child = AIAgent(
        route,
        platform=parent.platform,
        cwd=parent.cwd,
        config=parent.config,
        session_db=parent.db,
        persist=parent.db is not None,
        client=parent.client,
        parent=parent,
        enabled_toolsets=enabled,
        disabled_toolsets=disabled,
        max_turns=int(get_path(parent.config, "delegation.max_iterations", 50) or 50),
        skip_memory=True,
        approval_mode=parent.approval_mode,
        stream=False,
        callbacks=AgentCallbacks(
            on_step=progress.step,
            on_tool_start=progress.tool_start,
            approve=parent.callbacks.approve,  # dangerous commands still need the user's yes
        ),
    )
    # A toolset can overlap only partially with the parent's permissions (including aliases
    # and MCP groups). Cap individual tools before the child builds its prompt or dispatches.
    blocked = set(CHILD_BLOCKED_TOOLS)
    if not may_delegate(parent):
        blocked.add("delegate_task")
    allowed_tools = parent.tool_names - blocked
    child.tools = [tool for tool in child.tools if tool["function"]["name"] in allowed_tools]
    child.tool_names = frozenset(tool["function"]["name"] for tool in child.tools)
    return child


class _Progress:
    """Turns a child's tool callbacks into ``on_subagent`` events with the iteration count."""

    def __init__(self, parent: AIAgent, index: int, goal: str, model: str = "", spawn_id: str = "") -> None:
        self._parent = parent
        self._index = index
        self._goal = goal
        self.model = model
        self.spawn_id = spawn_id
        self.iteration = 0

    def _emit(self, event: str, **payload: Any) -> None:
        self._parent.callbacks.emit(
            "on_subagent",
            event,
            {
                "index": self._index,
                "goal": self._goal[:120],
                "iteration": self.iteration,
                "model": self.model,
                "spawn_id": self.spawn_id,
                **payload,
            },
        )

    def step(self, iteration: int) -> None:
        self.iteration = iteration

    def tool_start(self, call_id: str, name: str, args: dict[str, Any]) -> None:
        self._emit("tool", tool=name, args=_preview_args(args))


def _run_child(parent: AIAgent, index: int, task: dict[str, Any], spawn_id: str = "") -> dict[str, Any]:
    goal = str(task.get("goal") or "").strip()
    context = str(task.get("context") or "").strip()
    started = time.monotonic()
    progress = _Progress(parent, index, goal, spawn_id=spawn_id)

    try:
        child = _build_child(parent, task, progress)
    except CliteError as exc:
        # A bad per-task model fails this task only; siblings and the parent carry on.
        progress._emit("complete", status="failed")
        return {"index": index, "goal": goal, "status": "failed", "summary": "", "error": str(exc)}

    progress.model = child.route.model
    parent.register_child(child)
    progress._emit("start")
    invoke_hook("subagent_start", parent_session_id=parent.session_id, session_id=child.session_id, goal=goal)
    try:
        prompt = f"# Task\n\n{goal}" + (f"\n\n# Context\n\n{context}" if context else "")
        result = child.run_conversation(prompt)
        report = {
            "index": index,
            "goal": goal,
            "status": "completed" if result.completed else "interrupted" if result.interrupted else "failed",
            "summary": result.final_response,
            "model": child.route.model,
            "provider": child.route.provider,
            "api_calls": result.api_calls,
            "duration_seconds": round(time.monotonic() - started, 1),
            "session_id": child.session_id,
        }
        if result.error:
            report["error"] = result.error
    except Exception as exc:  # one failed child must not fail its siblings
        logger.warning("subagent %d crashed", index, exc_info=True)
        report = {
            "index": index,
            "goal": goal,
            "status": "failed",
            "summary": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        parent.unregister_child(child)
        child.close("subagent_done")
    progress._emit("complete", status=report["status"])
    invoke_hook(
        "subagent_stop",
        parent_session_id=parent.session_id,
        session_id=child.session_id,
        status=report["status"],
    )
    return report


def _note_report(report: dict[str, Any]) -> str:
    """One line per finished background task, phrased like a ``/steer`` note."""
    headline = "done" if report["status"] == "completed" else report["status"]
    detail = report.get("summary") or report.get("error") or ""
    detail = " ".join(str(detail).split())
    if len(detail) > 400:
        detail = detail[:397] + "…"
    return f"subagent {report['index'] + 1} ({report['goal'][:60]}) {headline}: {detail}"


def _run_background(parent: AIAgent, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Start each task on its own thread and return their ids right away."""
    ids: list[str] = []
    for index, task in enumerate(tasks):
        spawn_id = uuid.uuid4().hex[:12]
        ids.append(spawn_id)

        def work(index: int = index, task: dict[str, Any] = task, spawn_id: str = spawn_id) -> None:
            report = _run_child(parent, index, task, spawn_id=spawn_id)
            parent.queue_note("[Background delegation finished] " + _note_report(report))
            invoke_hook(
                "subagent_result", parent_session_id=parent.session_id, spawn_id=spawn_id, report=report
            )

        thread = start_thread(work, name=f"clite-subagent-{spawn_id}")
        parent.register_background_thread(thread)
    return {
        "background": True,
        "tasks": ids,
        "total": len(ids),
        "note": "Results arrive as a note on your next tool result. Keep working.",
    }


def delegate(parent: AIAgent, tasks: list[dict[str, Any]], *, background: bool = False) -> dict[str, Any]:
    """Run ``tasks`` (each ``{"goal", "context"?, "toolsets"?, "model"?}``) and return their reports.

    With ``background`` the call returns at once with one id per task; the reports come back to
    the parent later as a note on a tool result, so the parent is never left waiting.
    """
    max_depth = _max_depth(parent)
    if parent.depth >= max_depth:
        return {"error": f"Delegation depth limit reached ({max_depth}). Do this task yourself."}
    tasks = [task for task in tasks if isinstance(task, dict) and str(task.get("goal") or "").strip()]
    if not tasks:
        return {"error": "Provide a goal, or a tasks list where each task has a goal."}
    if len(tasks) > MAX_TASKS_PER_CALL:
        return {"error": f"At most {MAX_TASKS_PER_CALL} tasks per call; split the work into several calls."}
    if background:
        return _run_background(parent, tasks)
    workers = max(
        1, min(len(tasks), int(get_path(parent.config, "delegation.max_concurrent_children", 3) or 3))
    )
    if len(tasks) == 1:
        reports = [_run_child(parent, 0, tasks[0])]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clite-subagent") as pool:
            futures = [
                pool.submit(contextvars.copy_context().run, _run_child, parent, index, task)
                for index, task in enumerate(tasks)
            ]
            reports = [future.result() for future in futures]
    return {
        "results": reports,
        "completed": sum(1 for report in reports if report["status"] == "completed"),
        "total": len(reports),
    }
