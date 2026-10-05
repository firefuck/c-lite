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
    CommandDef("retry", "Remove the last exchange and send your last message again"),
    CommandDef("undo", "Remove the last exchange"),
    CommandDef("history", "Show the conversation so far", args_hint="[count]"),
    CommandDef("title", "Show or set the session title", args_hint="[title]"),
    CommandDef("sessions", "List recent sessions", args_hint="[count]"),
    CommandDef("resume", "Switch to an earlier session", args_hint="<id | title>"),
    CommandDef("compress", "Summarise older turns to free context", args_hint="[focus]"),
    CommandDef("stop", "Interrupt the running turn", busy_policy=BUSY_ALLOW),
    CommandDef("steer", "Guide the running turn without interrupting it", args_hint="<text>", busy_policy=BUSY_ALLOW),
    CommandDef("quit", "Exit", aliases=("exit", "q"), cli_only=True, busy_policy=BUSY_ALLOW),
    # ── Configuration ────────────────────────────────────────────────────────────────────
    CommandDef("model", "Show or switch the model", "Configuration", args_hint="[provider:model] [--global]"),
    CommandDef("provider", "List model providers and whether they are configured", "Configuration"),
    CommandDef("tools", "List toolsets, or enable/disable one", "Configuration", args_hint="[enable|disable <toolset>]",
               subcommands=("enable", "disable")),
    CommandDef("reasoning", "Show or set the reasoning effort", "Configuration",
               args_hint="[none|minimal|low|medium|high|xhigh|max]"),
    CommandDef("yolo", "Toggle command approval for this session", "Configuration"),
    CommandDef("config", "Show a setting or the config file path", "Configuration", args_hint="[key]"),
    CommandDef("reload", "Reload config and plugins", "Configuration"),
    CommandDef("profile", "Show the active profile and list the others", "Configuration"),
    # ── Tools and skills ─────────────────────────────────────────────────────────────────
    CommandDef("skills", "List skills", "Tools & Skills", args_hint="[filter]"),
    CommandDef("plugins", "List plugins and their status", "Tools & Skills"),
    CommandDef("memory", "Show what is in persistent memory", "Tools & Skills"),
    CommandDef("cron", "List scheduled jobs", "Tools & Skills"),
    # ── Info ─────────────────────────────────────────────────────────────────────────────
    CommandDef("help", "List commands", "Info", aliases=("?",), busy_policy=BUSY_ALLOW),
    CommandDef("status", "Show model, session and context usage", "Info", busy_policy=BUSY_ALLOW),
    CommandDef("usage", "Show token usage for this session", "Info", busy_policy=BUSY_ALLOW),
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
        {"name": command.name, "description": command.description, "category": command.category,
         "aliases": list(command.aliases), "args_hint": command.args_hint, "subcommands": list(command.subcommands),
         "kind": "builtin"}
        for command in commands_for(surface)
    ]
    taken = set(_index())
    for name, command in sorted(get_plugin_manager().commands.items()):
        if name not in taken:
            catalog.append({"name": name, "description": command.description, "category": "Plugins", "aliases": [],
                            "args_hint": command.args_hint, "subcommands": [], "kind": "plugin"})
            taken.add(name)
    for name, spec in sorted((load_config().get("quick_commands") or {}).items()):
        if name not in taken and isinstance(spec, dict):
            what = spec.get("command") or spec.get("target") or ""
            catalog.append({"name": name, "description": f"Quick command: {what}"[:80], "category": "Quick commands",
                            "aliases": [], "args_hint": "", "subcommands": [], "kind": "quick"})
            taken.add(name)
    for name, skill in sorted(skill_commands(cwd=cwd).items()):
        if name not in taken:
            catalog.append({"name": name, "description": skill.description[:80], "category": "Skills", "aliases": [],
                            "args_hint": "[instruction]", "subcommands": [], "kind": "skill"})
    return catalog
