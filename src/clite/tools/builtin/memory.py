"""``memory``: persistent notes across sessions (MEMORY.md and USER.md)."""

from __future__ import annotations

from typing import Any

from clite.tools.context import ToolContext
from clite.tools.registry import registry, tool_error, tool_result

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Save durable facts to persistent memory. They are added to the system prompt of future sessions. "
        "target 'memory' is for your own notes (environment facts, project conventions, lessons learned); "
        "target 'user' is for facts about the user (preferences, role, how they like things done). "
        "Actions: 'add' (content), 'replace' (old_text = a unique substring of the entry to replace, "
        "content = the new entry), 'remove' (old_text). There is no read action: current memory is already "
        "in your system prompt, and every write returns the updated entries. Memory is small. When a "
        "write would exceed the limit, merge or remove entries first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "replace", "remove"]},
            "target": {"type": "string", "enum": ["memory", "user"]},
            "content": {"type": "string", "description": "The entry text, for add and replace."},
            "old_text": {"type": "string", "description": "A short unique substring of the entry, for replace and remove."},
        },
        "required": ["action", "target"],
    },
}


def memory_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    agent = getattr(ctx, "agent", None)
    manager = getattr(agent, "memory", None)
    if manager is None:
        return tool_error("Memory is not available in this session.")
    result = manager.handle_memory_tool(
        str(args.get("action") or ""), str(args.get("target") or ""), str(args.get("content") or ""),
        str(args.get("old_text") or ""),
    )
    return tool_result(result)


registry.register("memory", "memory", MEMORY_SCHEMA, memory_tool, emoji="🧠")
