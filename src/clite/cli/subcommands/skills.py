"""``clite skills``: browse, install and curate skills."""

from __future__ import annotations

import argparse
import sys

from clite.skills import curator, manager
from clite.skills.catalog import discover_skills, get_skill, linked_files, read_skill_file
from clite.skills.hub import (
    SearchResults,
    add_tap,
    apply_update,
    find_entry,
    install_skill,
    installed_skills,
    load_taps,
    plan_update,
    remove_tap,
    search_skills,
)
from clite.skills.manager import SkillError
from clite.skills.scanner import ScanReport


def run_list(args: argparse.Namespace) -> int:
    skills = discover_skills(include_disabled=True)
    if not skills:
        print("No skills installed.")
        return 0
    for skill in skills:
        print(f"{skill.name:<30} {skill.tier:<9} {skill.category or 'general':<22} {skill.description[:70]}")
    return 0


def run_view(args: argparse.Namespace) -> int:
    skill = get_skill(args.name)
    if skill is None:
        print(f"No skill named {args.name!r}.")
        return 1
    print(f"# {skill.name} ({skill.tier}) — {skill.directory}\n")
    print(read_skill_file(skill))
    for kind, files in linked_files(skill).items():
        print(f"\n{kind}: {', '.join(files)}")
    return 0


def _print_report(report: ScanReport) -> None:
    lines = report.lines()
    if not lines:
        print("Scan: nothing to report.")
        return
    print("Scan:")
    for line in lines:
        print(f"  {line}")


def _ask(name: str, report: ScanReport) -> bool:
    """Show the scan and let the user decide. A clean bundle is not worth a question."""
    _print_report(report)
    if report.clean:
        return True
    try:
        answer = input(f"Install {name}? [y/N] ").strip().lower()
    except EOFError:
        print("No answer available; nothing was installed.")
        return False
    return answer in ("y", "yes")


def run_search(args: argparse.Namespace) -> int:
    results: SearchResults = search_skills(args.query, args.limit)
    for problem in results.problems:
        print(f"warning: {problem}", file=sys.stderr)
    if not results.entries:
        if not results.problems:
            print(f"Nothing matches {args.query!r}.")
        return 1
    installed = installed_skills()
    for entry in results.entries:
        mark = "*" if entry["name"] in installed else " "
        category = entry.get("category") or "general"
        print(f"{mark} {entry['name']:<30} {category:<18} {str(entry.get('description', ''))[:70]}")
    print(f"\n{len(results.entries)} result(s); * = installed. Install one with: clite skills install <name>")
    return 0


def run_info(args: argparse.Namespace) -> int:
    entry = find_entry(args.name)
    if entry is None:
        print(f"No skill named {args.name!r} in the index.")
        return 1
    for key in ("name", "description", "category", "version", "source", "identifier", "hash"):
        if entry.get(key):
            print(f"{key:<12} {entry[key]}")
    print(f"{'index':<12} {entry.get('index', '')}")
    record = installed_skills().get(str(entry["name"]))
    if record:
        state = (
            "up to date" if record.get("hash") == entry.get("hash") else "installed (index has another hash)"
        )
        print(f"{'installed':<12} {state}")
    else:
        print(f"{'installed':<12} no")
    return 0


def run_install(args: argparse.Namespace) -> int:
    try:
        result = install_skill(
            args.source,
            source=args.source_type,
            category=args.category,
            force=args.force,
            on_report=(
                (lambda report: True)
                if args.force or args.yes
                else (lambda report: _ask(args.source, report))
            ),
        )
    except SkillError as exc:
        print(f"Not installed: {exc}")
        return 1
    print(f"Installed {result['name']} into {result['path']}")
    for path, finding in result["warnings"].items():
        print(f"  warning: {path}: {finding}")
    return 0


def run_update(args: argparse.Namespace) -> int:
    names = [args.name] if args.name else sorted(installed_skills())
    if not names:
        print("Nothing is installed from a hub.")
        return 0
    failed = 0
    for name in names:
        try:
            plan = plan_update(name)
        except SkillError as exc:
            print(f"{name}: {exc}")
            failed += 1
            continue
        if plan.up_to_date:
            print(f"{name}: up to date.")
            continue
        print(f"{name}: {plan.summary()}")
        for path, status in sorted(plan.changed.items()):
            print(f"  {status:<8} {path}")
        if plan.report.blocked:
            print("  refused: the new version was flagged by the scan; not updated")
            for line in plan.report.lines():
                print(f"  {line}")
            failed += 1
            continue
        replace = args.force
        if plan.edited_locally and not replace:
            try:
                answer = (
                    input(f"{name} was edited since it was installed. Replace it? [y/N] ").strip().lower()
                )
            except EOFError:
                answer = ""
            replace = answer in ("y", "yes")
            if not replace:
                print("  kept your version; run again with --force to replace it")
                continue
        try:
            apply_update(plan, force=replace)
        except SkillError as exc:
            print(f"{name}: {exc}")
            failed += 1
            continue
        print("  updated.")
    return 1 if failed else 0


def run_tap(args: argparse.Namespace) -> int:
    if args.tap_action == "add":
        try:
            tap = add_tap(args.spec)
        except SkillError as exc:
            print(f"Not added: {exc}")
            return 1
        print(f"Added tap {tap['name']} -> {tap['index']}")
        return 0
    if args.tap_action == "remove":
        if not remove_tap(args.spec):
            print(f"No tap named {args.spec!r}.")
            return 1
        print(f"Removed tap {args.spec}.")
        return 0
    taps = load_taps()
    if not taps:
        print("No extra skill indexes. Add one with: clite skills tap add owner/repo")
        return 0
    for tap in taps:
        print(f"{tap['name']:<30} {tap['index']}")
    return 0


def run_remove(args: argparse.Namespace) -> int:
    try:
        manager.delete_skill(args.name, origin="user")
    except SkillError as exc:
        print(str(exc))
        return 1
    print(f"Removed {args.name}.")
    return 0


def run_curate(args: argparse.Namespace) -> int:
    report = curator.run_curator(args.days, dry_run=not args.apply)
    if not report["stale"]:
        print(f"No agent-created skill has been unused for {args.days} days.")
        return 0
    for entry in report["stale"]:
        print(
            f"{'archived' if args.apply else 'stale   '} {entry['name']}  (used {entry['use_count']} times)"
        )
    if not args.apply:
        print("\nNothing was changed. Run with --apply to archive these (they can be restored).")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("skills", help="list, search, install and curate skills")
    parser.set_defaults(handler=run_list)
    actions = parser.add_subparsers(dest="skills_action")
    actions.add_parser("list", help="list skills").set_defaults(handler=run_list)
    search = actions.add_parser("search", help="search the skill index")
    search.add_argument("query", nargs="?", default="", help="text to look for in the name and description")
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(handler=run_search)
    info = actions.add_parser("info", help="show what the index knows about a skill")
    info.add_argument("name")
    info.set_defaults(handler=run_info)
    view = actions.add_parser("view", help="print a skill")
    view.add_argument("name")
    view.set_defaults(handler=run_view)
    install = actions.add_parser(
        "install", help="install by name from the index, from a directory, or owner/repo/path[@ref]"
    )
    install.add_argument("source")
    install.add_argument("--source-type", choices=["local", "github"])
    install.add_argument("--category")
    install.add_argument(
        "--force", action="store_true", help="replace an existing skill / accept scan warnings"
    )
    install.add_argument("--yes", "-y", action="store_true", help="do not ask after the scan")
    install.set_defaults(handler=run_install)
    update = actions.add_parser("update", help="update skills installed from a hub")
    update.add_argument("name", nargs="?")
    update.add_argument("--force", action="store_true", help="replace a skill you edited yourself")
    update.set_defaults(handler=run_update)
    tap = actions.add_parser("tap", help="manage extra skill indexes")
    tap.set_defaults(handler=run_tap)
    tap_actions = tap.add_subparsers(dest="tap_action")
    tap_add = tap_actions.add_parser("add", help="add an index: owner/repo, a path, or a URL")
    tap_add.add_argument("spec")
    tap_add.set_defaults(handler=run_tap)
    tap_list = tap_actions.add_parser("list", help="list the extra indexes")
    tap_list.set_defaults(handler=run_tap)
    tap_remove = tap_actions.add_parser("remove", help="remove an index")
    tap_remove.add_argument("spec")
    tap_remove.set_defaults(handler=run_tap)
    remove = actions.add_parser("remove", help="delete a local skill")
    remove.add_argument("name")
    remove.set_defaults(handler=run_remove)
    curate = actions.add_parser("curate", help="archive agent-created skills that are no longer used")
    curate.add_argument("--days", type=int, default=curator.DEFAULT_STALE_DAYS)
    curate.add_argument("--apply", action="store_true")
    curate.set_defaults(handler=run_curate)
