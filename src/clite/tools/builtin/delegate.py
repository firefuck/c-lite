"""``delegate_task``: hand focused work to subagents with isolated context."""

from __future__ import annotations

from typing import Any

from clite.tools.context import ToolContext
from clite.tools.registry import registry, tool_error, tool_result

DELEGATE_SCHEMA = {
    "name": "delegate_task",
    "description": (
        "Run one or more subagents, each on a focused task, and get back only their final reports. Use it "
        "to keep large intermediate output (research, wide code searches, log analysis) out of your own "
        "context, or to do independent tasks in parallel. A subagent starts with no knowledge of this "
        "conversation: put everything it needs (paths, constraints, what to return) in goal and context. "
        "For one task pass goal; for several pass tasks. Set model to run a task on another configured "
        "model (a bare name keeps this provider; provider:model or an alias switches provider). Set "
        "background=true to return at once and receive the reports later as a note. Subagents cannot ask "
        "the user questions or write memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "What the subagent must accomplish and what to report back.",
            },
            "context": {
                "type": "string",
                "description": "Background the subagent needs: file paths, constraints, findings so far.",
            },
            "toolsets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Toolsets for the subagent (default: terminal, file, web, skills, session_search, todo).",
            },
            "model": {
                "type": "string",
                "description": "Model for this task: a name for the current provider, or provider:model. Must be a configured provider.",
            },
            "background": {
                "type": "boolean",
                "description": "Return immediately with an id per task; the reports arrive later as a note. Use for long tasks you can work alongside.",
            },
            "tasks": {
                "type": "array",
                "description": "Several tasks to run in parallel, each with its own goal, context, toolsets and model.",
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "context": {"type": "string"},
                        "toolsets": {"type": "array", "items": {"type": "string"}},
                        "model": {"type": "string"},
                    },
                    "required": ["goal"],
                },
            },
        },
    },
}


def delegate_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    agent = getattr(ctx, "agent", None)
    if agent is None:
        return tool_error("delegate_task is only available inside an agent session.")
    from clite.agent.delegation import delegate

    tasks = args.get("tasks")
    if not tasks:
        tasks = [
            {
                "goal": args.get("goal"),
                "context": args.get("context"),
                "toolsets": args.get("toolsets"),
                "model": args.get("model"),
            }
        ]
    if not isinstance(tasks, list):
        return tool_error("tasks must be a list of {goal, context?, toolsets?, model?} objects")
    return tool_result(delegate(agent, tasks, background=bool(args.get("background"))))


registry.register("delegate_task", "delegation", DELEGATE_SCHEMA, delegate_tool, emoji="🤝")
