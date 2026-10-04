"""Toolsets: named groups of tools, composable through ``includes``.

A platform gets a composite toolset (``clite-cli``, ``clite-gateway``, ...). A tool
registered by a plugin or an MCP server under a toolset name not listed here still resolves:
the registry is consulted for any unknown name.
"""

from __future__ import annotations

from typing import Any

from clite.tools.registry import registry

_CORE = ["terminal", "file", "web", "todo", "memory", "skills", "session_search"]

TOOLSETS: dict[str, dict[str, Any]] = {
    "terminal": {"description": "Run shell commands and manage background processes", "tools": ["terminal", "process"]},
    "file": {"description": "Read, write, patch and search files", "tools": ["read_file", "write_file", "patch", "search_files"]},
    "web": {"description": "Fetch web pages as text", "tools": ["web_fetch"]},
    "todo": {"description": "Task list for multi-step work", "tools": ["todo"]},
    "memory": {"description": "Persistent notes across sessions", "tools": ["memory"]},
    "skills": {"description": "List, read and maintain skills", "tools": ["skills_list", "skill_view", "skill_manage"]},
    "session_search": {"description": "Search past conversations", "tools": ["session_search"]},
    "clarify": {"description": "Ask the user a question", "tools": ["clarify"]},
    "delegation": {"description": "Spawn subagents with isolated context", "tools": ["delegate_task"]},
    "cronjob": {"description": "Schedule recurring or one-off agent tasks", "tools": ["cronjob"]},
    # ── platform composites ──────────────────────────────────────────────────────────────
    "clite-cli": {
        "description": "Everything, for the interactive terminal",
        "tools": [],
        "includes": [*_CORE, "clarify", "delegation", "cronjob"],
    },
    "clite-gateway": {
        "description": "Messaging platforms",
        "tools": [],
        "includes": [*_CORE, "clarify", "delegation", "cronjob"],
    },
    # A cron run has no user to ask and must not schedule more cron jobs.
    "clite-cron": {"description": "Scheduled runs", "tools": [], "includes": [*_CORE, "delegation"]},
    # A subagent cannot delegate further, ask the user, write shared memory or schedule work.
    "clite-subagent": {"description": "Delegated workers", "tools": [], "includes": ["terminal", "file", "web", "todo", "skills", "session_search"]},
}

ALL_ALIASES = frozenset({"all", "*"})
PLATFORM_PREFIX = "clite-"
MCP_PREFIX = "mcp-"


def register_toolset(name: str, description: str, tools: list[str] | None = None, includes: list[str] | None = None) -> None:
    """Add or replace a toolset (used by plugins)."""
    TOOLSETS[name] = {"description": description, "tools": list(tools or []), "includes": list(includes or [])}


def toolset_exists(name: str) -> bool:
    return name in ALL_ALIASES or name in TOOLSETS or bool(registry.tools_in_toolset(name))


def resolve_toolset(name: str, _visiting: frozenset[str] = frozenset()) -> list[str]:
    """Tool names in ``name``, following ``includes``. Unknown names resolve to nothing."""
    if name in ALL_ALIASES:
        return registry.names()
    if name in _visiting:
        return []  # cycle: the first visit already contributes the tools
    spec = TOOLSETS.get(name)
    tools: list[str] = []
    if spec is not None:
        tools.extend(spec.get("tools", ()))
        for included in spec.get("includes", ()):
            tools.extend(resolve_toolset(included, _visiting | {name}))
        if name.startswith(PLATFORM_PREFIX):
            # A platform toolset carries every connected MCP server; turn one off with
            # `disabled_toolsets: [mcp-<server>]`.
            for toolset in registry.toolset_names():
                if toolset.startswith(MCP_PREFIX):
                    tools.extend(registry.tools_in_toolset(toolset))
    # Tools registered straight into this toolset name (plugins, MCP servers).
    tools.extend(registry.tools_in_toolset(name))
    return _dedupe(tools)


def resolve_toolsets(names: list[str] | tuple[str, ...]) -> list[str]:
    tools: list[str] = []
    for name in names:
        tools.extend(resolve_toolset(name))
    return _dedupe(tools)


def all_toolsets() -> dict[str, dict[str, Any]]:
    """Static toolsets plus any toolset that exists only because a tool registered into it."""
    merged = {name: dict(spec) for name, spec in TOOLSETS.items()}
    for name in registry.toolset_names():
        merged.setdefault(name, {"description": "Registered by an extension", "tools": [], "includes": []})
    return merged


def toolset_for_tool(tool_name: str) -> str:
    entry = registry.get(tool_name)
    return entry.toolset if entry else ""


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
