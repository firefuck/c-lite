"""The slash command registry: one table every surface reads.

A command is declared once here. The CLI, the TUI and desktop (through the RPC server) and
the gateway all build their help text, autocomplete and dispatch from this list, so a command
added here appears everywhere at once. The handler lives in ``clite.runtime.slash`` under the
name ``_handle_<command name>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BUSY_ALLOW = "allow"  # safe to run while a turn is active (/stop, /status, /steer)
BUSY_QUEUE = "queue"  # must wait for the running turn to finish


@dataclass(frozen=True)
class CommandDef:
    name: str
    description: str
    category: str = "Session"
    aliases: tuple[str, ...] = ()
    args_hint: str = ""
    subcommands: tuple[str, ...] = ()
    cli_only: bool = False  # needs a local terminal; hidden on messaging platforms
    busy_policy: str = BUSY_QUEUE


COMMAND_REGISTRY: list[CommandDef] = [
    # ── Session ──────────────────────────────────────────────────────────────────────────
    CommandDef("new", "Start a fresh session", aliases=("reset",)),
    CommandDef("image", "Attach an image file to your next message", args_hint="<path>", aliases=("attach",)),
    CommandDef("retry", "Remove the last exchange and send your last message again"),
    CommandDef("undo", "Remove the last exchange"),
    CommandDef("history", "Show the conversation so far", args_hint="[count]"),
    CommandDef("title", "Show or set the session title", args_hint="[title]"),
    CommandDef("sessions", "List recent sessions", args_hint="[count]"),
    CommandDef("resume", "Switch to an earlier session", args_hint="<id | title>"),
    CommandDef("branch", "Copy this conversation into a new session", args_hint="[title]"),
    CommandDef(
        "queue", "Queue a message to run after the running turn", args_hint="<text>", busy_policy=BUSY_ALLOW
    ),
    CommandDef(
        "background",
        "Run one turn in a separate session and report the result",
        args_hint="<text>",
        aliases=("bg",),
        busy_policy=BUSY_ALLOW,
    ),
    CommandDef("export", "Save the transcript as Markdown or JSON", args_hint="[path]"),
    CommandDef("pin", "Mark this session so it is never pruned"),
    CommandDef("archive", "Hide this session from the session list"),
    CommandDef("compress", "Summarise older turns to free context", args_hint="[focus]"),
    CommandDef("rollback", "Undo the files the agent changed in the last turn(s)", args_hint="[turns]"),
    CommandDef("checkpoints", "List the file checkpoints kept for this session"),
    CommandDef("stop", "Interrupt the running turn", busy_policy=BUSY_ALLOW),
    CommandDef(
        "steer", "Guide the running turn without interrupting it", args_hint="<text>", busy_policy=BUSY_ALLOW
    ),
    CommandDef("quit", "Exit", aliases=("exit", "q"), cli_only=True, busy_policy=BUSY_ALLOW),
    # ── Configuration ────────────────────────────────────────────────────────────────────
    CommandDef("model", "Show or switch the model", "Configuration", args_hint="[provider:model] [--global]"),
    CommandDef("provider", "List model providers and whether they are configured", "Configuration"),
    CommandDef(
        "tools",
        "List toolsets, or enable/disable one",
        "Configuration",
        args_hint="[enable|disable <toolset>]",
        subcommands=("enable", "disable"),
    ),
    CommandDef(
        "reasoning",
        "Show or set the reasoning effort",
        "Configuration",
        args_hint="[none|minimal|low|medium|high|xhigh|max]",
    ),
    CommandDef("yolo", "Toggle command approval for this session", "Configuration"),
    CommandDef("config", "Show a setting or the config file path", "Configuration", args_hint="[key]"),
    CommandDef("reload", "Reload config and plugins", "Configuration"),
    CommandDef("profile", "Show the active profile and list the others", "Configuration"),
    CommandDef(
        "verbose",
        "Set how much tool progress is shown",
        "Configuration",
        args_hint="[off|new|all|verbose]",
        subcommands=("off", "new", "all", "verbose"),
    ),
    CommandDef(
        "skin", "Show or change the display skin/theme", "Configuration", args_hint="[name]", cli_only=True
    ),
    # ── Tools and skills ─────────────────────────────────────────────────────────────────
    CommandDef("skills", "List skills", "Tools & Skills", args_hint="[filter]"),
    CommandDef("plugins", "List plugins and their status", "Tools & Skills"),
    CommandDef("hooks", "List shell hooks and which await approval", "Tools & Skills"),
    CommandDef("mcp", "Show the status of the MCP servers", "Tools & Skills", args_hint="[name]"),
    CommandDef("memory", "Show what is in persistent memory", "Tools & Skills"),
    CommandDef("cron", "List scheduled jobs", "Tools & Skills"),
    # ── Info ─────────────────────────────────────────────────────────────────────────────
    CommandDef("help", "List commands", "Info", aliases=("?",), busy_policy=BUSY_ALLOW),
    CommandDef("status", "Show model, session and context usage", "Info", busy_policy=BUSY_ALLOW),
    CommandDef("context", "Break down the context window: prompt tiers, tools, history", "Info"),
    CommandDef("usage", "Show token usage for this session", "Info", busy_policy=BUSY_ALLOW),
    CommandDef("tasks", "Show this session's todo list", "Info"),
    CommandDef("logs", "Show the last lines of the agent log", "Info", args_hint="[count]", cli_only=True),
    CommandDef("copy", "Copy the last answer to the clipboard", "Info", cli_only=True),
    CommandDef("insights", "Show usage insights, tokens and costs", "Info", args_hint="[days]"),
    CommandDef("sethome", "Set this chat as the platform's home channel", "Gateway"),
    CommandDef("debug", "Show prompt and context internals", "Info"),
]

_BY_NAME: dict[str, CommandDef] = {}


def _index() -> dict[str, CommandDef]:
    if len(_BY_NAME) < len(COMMAND_REGISTRY):
        _BY_NAME.clear()
        for command in COMMAND_REGISTRY:
            _BY_NAME[command.name] = command
            for alias in command.aliases:
                _BY_NAME[alias] = command
    return _BY_NAME


def resolve_command(name: str) -> CommandDef | None:
    """The command for ``name`` (with or without the slash), following aliases."""
    return _index().get(name.lstrip("/").lower())


def commands_for(surface: str) -> list[CommandDef]:
    """Commands that make sense on ``surface``: messaging platforms hide terminal-only ones."""
    local = surface in ("cli", "tui", "desktop")
    return [command for command in COMMAND_REGISTRY if local or not command.cli_only]


def split_command(text: str) -> tuple[str, str]:
    """``("/name", "args")`` from raw input. Not a command when it does not start with a slash."""
    stripped = text.strip()
    if not stripped.startswith("/") or len(stripped) < 2 or stripped[1] in "/ ":
        return "", stripped
    head, _, rest = stripped[1:].partition(" ")
    return head.lower(), rest.strip()


def command_catalog(surface: str = "cli", *, cwd: str | None = None) -> list[dict[str, Any]]:
    """Every command available right now, for help and autocomplete: built-in, plugin, quick
    commands from config, and one per skill."""
    from clite.core.config import load_config
    from clite.plugins.manager import get_plugin_manager
    from clite.skills.commands import skill_commands

    catalog: list[dict[str, Any]] = [
        {
            "name": command.name,
            "description": command.description,
            "category": command.category,
            "aliases": list(command.aliases),
            "args_hint": command.args_hint,
            "subcommands": list(command.subcommands),
            "kind": "builtin",
        }
        for command in commands_for(surface)
    ]
    taken = set(_index())
    for name, command in sorted(get_plugin_manager().commands.items()):
        if name not in taken:
            catalog.append(
                {
                    "name": name,
                    "description": command.description,
                    "category": "Plugins",
                    "aliases": [],
                    "args_hint": command.args_hint,
                    "subcommands": [],
                    "kind": "plugin",
                }
            )
            taken.add(name)
    for name, spec in sorted((load_config().get("quick_commands") or {}).items()):
        if name not in taken and isinstance(spec, dict):
            what = spec.get("command") or spec.get("target") or ""
            catalog.append(
                {
                    "name": name,
                    "description": f"Quick command: {what}"[:80],
                    "category": "Quick commands",
                    "aliases": [],
                    "args_hint": "",
                    "subcommands": [],
                    "kind": "quick",
                }
            )
            taken.add(name)
    for name, skill in sorted(skill_commands(cwd=cwd).items()):
        if name not in taken:
            catalog.append(
                {
                    "name": name,
                    "description": skill.description[:80],
                    "category": "Skills",
                    "aliases": [],
                    "args_hint": "[instruction]",
                    "subcommands": [],
                    "kind": "skill",
                }
            )
            taken.add(name)
    from clite.tools.mcp import mcp_prompt_catalog

    for entry in mcp_prompt_catalog():
        if entry["name"] not in taken:
            catalog.append(entry)
            taken.add(entry["name"])
    return catalog
