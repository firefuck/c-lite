"""``clite tools``: see and switch toolsets."""

from __future__ import annotations

import argparse

from clite.core.config import config_set, load_config
from clite.plugins.manager import ensure_plugins_loaded
from clite.tools.dispatch import resolve_enabled_tools
from clite.tools.registry import discover_builtin_tools, registry
from clite.tools.toolsets import all_toolsets, resolve_toolset, toolset_exists


def _prepare() -> None:
    ensure_plugins_loaded()
    discover_builtin_tools()


def run_list(args: argparse.Namespace) -> int:
    _prepare()
    active = set(resolve_enabled_tools())
    for name, spec in sorted(all_toolsets().items()):
        tools = resolve_toolset(name)
        on = sum(1 for tool in tools if tool in active)
        state = "on  " if tools and on == len(tools) else "part" if on else "off "
        print(f"{state} {name:<16} {on}/{len(tools)}  {spec.get('description', '')}")
        if args.verbose:
            for tool in tools:
                entry = registry.get(tool)
                missing = "" if entry and registry.is_available(tool) else "  (unavailable)"
                print(f"       {'*' if tool in active else ' '} {tool}{missing}")
    return 0


def _switch(name: str, disable: bool) -> int:
    _prepare()
    if not toolset_exists(name):
        print(f"Unknown toolset {name!r}. `clite tools list` shows them.")
        return 1
    disabled = [item for item in load_config().get("disabled_toolsets") or [] if item != name]
    if disable:
        disabled.append(name)
    config_set("disabled_toolsets", disabled)
    print(f"{name} {'disabled' if disable else 'enabled'}. New sessions will pick this up.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tools", help="list, enable or disable toolsets")
    parser.set_defaults(handler=run_list, verbose=False)
    actions = parser.add_subparsers(dest="tools_action")
    listing = actions.add_parser("list", help="list toolsets")
    listing.add_argument("-v", "--verbose", action="store_true", help="also list each tool")
    listing.set_defaults(handler=run_list)
    for action, disable in (("enable", False), ("disable", True)):
        sub = actions.add_parser(action, help=f"{action} a toolset")
        sub.add_argument("toolset")
        sub.set_defaults(handler=lambda args, disable=disable: _switch(args.toolset, disable))
