"""``clite plugins``: list, enable, disable, install, remove, search, info, update."""

from __future__ import annotations

import argparse
import sys

from clite.plugins.hub import (
    PluginError,
    apply_update,
    dependency_commands,
    find_entry,
    installed_plugins,
    plan_update,
    search_plugins,
)
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
        print(
            f"{info.status:<12} {info.name:<20} {info.manifest.version:<8} {info.manifest.kind:<15} {info.source:<8} "
            f"{info.error or info.manifest.description}"
        )
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


def run_search(args: argparse.Namespace) -> int:
    results = search_plugins(args.query, limit=args.limit)
    for problem in results.problems:
        print(f"warning: {problem}", file=sys.stderr)
    if not results.entries:
        if not results.problems:
            print(f"Nothing matches {args.query!r}.")
        return 1
    installed = get_plugin_manager().discover()
    for entry in results.entries:
        mark = "*" if str(entry["name"]) in installed else " "
        print(
            f"{mark} {str(entry['name']):<28} {str(entry.get('kind') or ''):<16} "
            f"{str(entry.get('description') or '')[:70]}"
        )
    print(
        f"\n{len(results.entries)} result(s); * = installed. Install one with: clite plugins install <name>"
    )
    return 0


def _describe(info) -> list[str]:
    """The lines `clite plugins info` prints, provenance included."""
    lines = [
        f"{'name':<12} {info.name}",
        f"{'version':<12} {info.manifest.version}",
        f"{'kind':<12} {info.manifest.kind}",
        f"{'source':<12} {info.source}" + (f" ({info.path})" if info.path else ""),
        f"{'status':<12} {info.status}" + (f" ({info.error})" if info.error else ""),
        f"{'description':<12} {info.manifest.description or '-'}",
    ]
    record = installed_plugins().get(info.name)
    if record:
        where = f"{record.get('source')} {record.get('identifier')}"
        if record.get("commit"):
            where += f" at {str(record['commit'])[:12]}"
        lines.append(f"{'installed':<12} {where}")
    if info.manifest.requires_env:
        lines.append(f"{'requires':<12} {', '.join(info.manifest.requires_env)} (in .env)")
    for command in dependency_commands(info.manifest):
        lines.append(f"{'dependency':<12} {command}   (run it yourself; nothing is installed for you)")
    if info.manifest.provides_hooks:
        lines.append(f"{'hooks':<12} {', '.join(info.manifest.provides_hooks)}")
    return lines


def run_info(args: argparse.Namespace) -> int:
    manager = get_plugin_manager()
    manager.discover()
    info = manager.plugins.get(args.name)
    if info is not None:
        for line in _describe(info):
            print(line)
        return 0
    exact = find_entry(args.name)
    if exact is None:
        print(f"No plugin named {args.name!r} is installed or in the catalog.")
        return 1
    entry = exact
    for key in ("name", "description", "version", "kind", "source", "identifier", "hash"):
        if entry.get(key):
            print(f"{key:<12} {entry[key]}")
    print(f"{'installed':<12} no; install it with: clite plugins install {entry['name']}")
    return 0


def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def run_install(args: argparse.Namespace) -> int:
    try:
        info = install_plugin(args.source, force=args.force)
    except (ManifestError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"Not installed: {exc}")
        return 1
    print(f"Installed {info.name} {info.manifest.version} into {info.path}")
    for command in dependency_commands(info.manifest):
        print(f"It needs a dependency. Run it yourself: {command}")
    print(f"Review it, then enable it with: clite plugins enable {info.name}")
    return 0


def run_update(args: argparse.Namespace) -> int:
    names = [args.name] if args.name else sorted(installed_plugins())
    if not names:
        print("No plugin was installed from a source, so there is nothing to update.")
        return 0
    failed = 0
    for name in names:
        try:
            plan = plan_update(name)
        except PluginError as exc:
            print(f"{name}: {exc}")
            failed += 1
            continue
        print(plan.summary())
        for line in plan.lines():
            print(line)
        if plan.up_to_date:
            continue
        if plan.edited_locally and not args.force:
            print(f"Not updated: {name} was edited since it was installed. --force replaces your changes.")
            failed += 1
            continue
        if not args.yes and not _confirm(f"Replace the installed {name} with this version?"):
            print(f"{name}: skipped.")
            continue
        result = apply_update(plan, force=args.force)
        version = plan.staged.manifest.version
        changed = ", ".join(f"{count} {status}" for status, count in _changed_summary(result["changed"]))
        print(f"Updated {name} to {version} ({changed}).")
        print(f"It is disabled until you enable it: clite plugins enable {name}")
    return 1 if failed else 0


def _changed_summary(changed: dict[str, str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for status in changed.values():
        counts[status] = counts.get(status, 0) + 1
    return [(status, counts[status]) for status in ("added", "removed", "changed") if status in counts]


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
    install = actions.add_parser("install", help="install from a directory, a git URL, or a catalog name")
    install.add_argument("source")
    install.add_argument("--force", action="store_true")
    install.set_defaults(handler=run_install)
    remove = actions.add_parser("remove", help="remove a user-installed plugin")
    remove.add_argument("name")
    remove.set_defaults(handler=run_remove)
    search = actions.add_parser("search", help="search the plugin catalog")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(handler=run_search)
    info = actions.add_parser("info", help="what a plugin is, and where it came from")
    info.add_argument("name")
    info.set_defaults(handler=run_info)
    update = actions.add_parser("update", help="show what changed, then replace the installed copy")
    update.add_argument("name", nargs="?", default="")
    update.add_argument(
        "--force", action="store_true", help="replace a plugin you edited, or one already replaced"
    )
    update.add_argument("-y", "--yes", action="store_true", help="do not ask before replacing")
    update.set_defaults(handler=run_update)
