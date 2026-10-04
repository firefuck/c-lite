"""``clite profile``: separate homes with their own config, keys, memory and sessions."""

from __future__ import annotations

import argparse

from clite.core.constants import display_home
from clite.core.profiles import (
    create_profile,
    delete_profile,
    get_active_profile_name,
    get_sticky_profile,
    list_profiles,
    set_sticky_profile,
)


def run_list(args: argparse.Namespace) -> int:
    sticky = get_sticky_profile()
    for profile in list_profiles():
        marks = ("*" if profile.active else " ") + ("  (default for new shells)" if profile.name == sticky else "")
        print(f"{marks[0]} {profile.name:<20} {display_home(profile.home)}{marks[1:]}")
    return 0


def run_show(args: argparse.Namespace) -> int:
    print(f"{get_active_profile_name()}  {display_home()}")
    return 0


def run_create(args: argparse.Namespace) -> int:
    home = create_profile(args.name, clone_from=args.clone_from)
    print(f"Created profile {args.name} at {display_home(home)}")
    print(f"Use it once with `clite -p {args.name}`, or make it the default with `clite profile use {args.name}`.")
    return 0


def run_use(args: argparse.Namespace) -> int:
    set_sticky_profile(args.name)
    print(f"New shells now start in profile {args.name}.")
    return 0


def run_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        print(f"This deletes profile {args.name!r} with its sessions, memory and keys. Re-run with --yes to confirm.")
        return 1
    delete_profile(args.name)
    print(f"Deleted profile {args.name}.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("profile", help="manage profiles (separate homes)")
    parser.set_defaults(handler=run_list)
    actions = parser.add_subparsers(dest="profile_action")
    actions.add_parser("list", help="list profiles").set_defaults(handler=run_list)
    actions.add_parser("show", help="print the active profile").set_defaults(handler=run_show)
    create = actions.add_parser("create", help="create a profile")
    create.add_argument("name")
    create.add_argument("--clone-from", metavar="PROFILE", help="copy config, SOUL.md and skills (never secrets)")
    create.set_defaults(handler=run_create)
    use = actions.add_parser("use", help="make a profile the default for new shells")
    use.add_argument("name")
    use.set_defaults(handler=run_use)
    delete = actions.add_parser("delete", help="delete a profile and everything in it")
    delete.add_argument("name")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(handler=run_delete)
