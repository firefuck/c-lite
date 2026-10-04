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
        "For one task pass goal; for several pass tasks. Subagents cannot ask the user questions, write "
        "memory, or delegate further."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What the subagent must accomplish and what to report back."},
            "context": {"type": "string", "description": "Background the subagent needs: file paths, constraints, findings so far."},
            "toolsets": {"type": "array", "items": {"type": "string"},
                         "description": "Toolsets for the subagent (default: terminal, file, web, skills, session_search, todo)."},
            "tasks": {
                "type": "array",
                "description": "Several tasks to run in parallel, each with its own goal, context and toolsets.",
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "context": {"type": "string"},
                        "toolsets": {"type": "array", "items": {"type": "string"}},
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
        tasks = [{"goal": args.get("goal"), "context": args.get("context"), "toolsets": args.get("toolsets")}]
    if not isinstance(tasks, list):
        return tool_error("tasks must be a list of {goal, context?, toolsets?} objects")
    return tool_result(delegate(agent, tasks))


registry.register("delegate_task", "delegation", DELEGATE_SCHEMA, delegate_tool, emoji="🤝")
