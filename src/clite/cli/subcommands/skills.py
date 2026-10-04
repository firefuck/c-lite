"""``clite skills``: browse, install and curate skills."""

from __future__ import annotations

import argparse

from clite.skills import curator, manager
from clite.skills.catalog import discover_skills, get_skill, linked_files, read_skill_file
from clite.skills.hub import install_skill
from clite.skills.manager import SkillError


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


def run_install(args: argparse.Namespace) -> int:
    try:
        result = install_skill(args.source, source=args.source_type, category=args.category, force=args.force)
    except SkillError as exc:
        print(f"Not installed: {exc}")
        return 1
    print(f"Installed {result['name']} into {result['path']}")
    for path, finding in result["warnings"].items():
        print(f"  warning: {path}: {finding}")
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
        print(f"{'archived' if args.apply else 'stale   '} {entry['name']}  (used {entry['use_count']} times)")
    if not args.apply:
        print("\nNothing was changed. Run with --apply to archive these (they can be restored).")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("skills", help="list, view, install and curate skills")
    parser.set_defaults(handler=run_list)
    actions = parser.add_subparsers(dest="skills_action")
    actions.add_parser("list", help="list skills").set_defaults(handler=run_list)
    view = actions.add_parser("view", help="print a skill")
    view.add_argument("name")
    view.set_defaults(handler=run_view)
    install = actions.add_parser("install", help="install from a directory or owner/repo/path on GitHub")
    install.add_argument("source")
    install.add_argument("--source-type", choices=["local", "github"])
    install.add_argument("--category")
    install.add_argument("--force", action="store_true", help="replace an existing skill / accept scan warnings")
    install.set_defaults(handler=run_install)
    remove = actions.add_parser("remove", help="delete a local skill")
    remove.add_argument("name")
    remove.set_defaults(handler=run_remove)
    curate = actions.add_parser("curate", help="archive agent-created skills that are no longer used")
    curate.add_argument("--days", type=int, default=curator.DEFAULT_STALE_DAYS)
    curate.add_argument("--apply", action="store_true")
    curate.set_defaults(handler=run_curate)
