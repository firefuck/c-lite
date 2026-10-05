"""``clite plugins``: list, enable, disable, install, remove."""

from __future__ import annotations

import argparse

from clite.plugins.manager import get_plugin_manager, install_plugin, remove_plugin, set_plugin_enabled
from clite.plugins.manifest import ManifestError


def run_list(args: argparse.Namespace) -> int:
    manager = get_plugin_manager()
    manager.load_all()
    plugins = manager.list()
    if not plugins:
        print("No plugins found.")
        return 0
    for info in plugins:
        print(f"{info.status:<12} {info.name:<20} {info.manifest.version:<8} {info.manifest.kind:<15} {info.source:<8} "
              f"{info.error or info.manifest.description}")
    return 0


def _toggle(name: str, enabled: bool) -> int:
    manager = get_plugin_manager()
    manager.discover()
    if name not in manager.plugins:
        print(f"No plugin named {name!r}. `clite plugins list` shows what is installed.")
        return 1
    set_plugin_enabled(name, enabled)
    manager.load_all()
    info = manager.plugins[name]
    print(f"{name}: {info.status}" + (f" ({info.error})" if info.error else ""))
    return 0 if info.status in ("loaded", "disabled") else 1


def run_install(args: argparse.Namespace) -> int:
    try:
        info = install_plugin(args.source, force=args.force)
    except (ManifestError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"Not installed: {exc}")
        return 1
    print(f"Installed {info.name} {info.manifest.version} into {info.path}")
    print(f"Review it, then enable it with: clite plugins enable {info.name}")
    return 0


def run_remove(args: argparse.Namespace) -> int:
    if not remove_plugin(args.name):
        print(f"No user-installed plugin named {args.name!r}.")
        return 1
    print(f"Removed {args.name}.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("plugins", help="list, enable, disable, install or remove plugins")
    parser.set_defaults(handler=run_list)
    actions = parser.add_subparsers(dest="plugins_action")
    actions.add_parser("list", help="list plugins").set_defaults(handler=run_list)
    for action, enabled in (("enable", True), ("disable", False)):
        sub = actions.add_parser(action, help=f"{action} a plugin")
        sub.add_argument("name")
        sub.set_defaults(handler=lambda args, enabled=enabled: _toggle(args.name, enabled))
    install = actions.add_parser("install", help="install from a directory or a git URL (does not enable)")
    install.add_argument("source")
    install.add_argument("--force", action="store_true")
    install.set_defaults(handler=run_install)
    remove = actions.add_parser("remove", help="remove a user-installed plugin")
    remove.add_argument("name")
    remove.set_defaults(handler=run_remove)
