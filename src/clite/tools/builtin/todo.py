"""``todo``: the agent's task list for multi-step work."""

from __future__ import annotations

from typing import Any

from clite.tools.context import ToolContext
from clite.tools.registry import registry, tool_error, tool_result

TODO_SCHEMA = {
    "name": "todo",
    "description": (
        "Read or update your task list for the current session. Call with no arguments to read it. "
        "Pass todos to write it: by default the list is replaced; with merge=true items are updated by id "
        "and new ones appended. Use it for any task with three or more steps: write the plan first, keep "
        "exactly one item in_progress, and mark items completed as you finish them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The task items to write.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Short unique id, e.g. '1'."},
                        "content": {"type": "string", "description": "What to do."},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                    },
                    "required": ["id", "content", "status"],
                },
            },
            "merge": {"type": "boolean", "description": "Update by id instead of replacing the whole list."},
        },
    },
}


def todo_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    agent = getattr(ctx, "agent", None)
    if agent is None:
        return tool_error("The todo tool is only available inside an agent session.")
    todos = args.get("todos")
    if todos is None:
        return tool_result(todos=agent.todos.read(), summary=agent.todos.summary())
    if not isinstance(todos, list):
        return tool_error("todos must be a list of {id, content, status} objects")
    try:
        items = agent.todos.write(todos, merge=bool(args.get("merge")))
    except ValueError as exc:
        return tool_error(str(exc))
    return tool_result(todos=items, summary=agent.todos.summary())


registry.register("todo", "todo", TODO_SCHEMA, todo_tool, emoji="📋")
