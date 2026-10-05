"""``clite config``: read and write config.yaml."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess

import yaml

from clite.core.config import (
    config_set,
    config_unset,
    get_path,
    load_config,
    load_user_config_raw,
    migrate_config_file,
    parse_cli_value,
)
from clite.core.constants import get_config_path, get_env_path
from clite.core.env import mask_secret, read_env_file

_MISSING = object()


def run_show(args: argparse.Namespace) -> int:
    data = load_config() if args.all else load_user_config_raw()
    print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip() or "# (empty: every setting is at its default)")
    return 0


def run_get(args: argparse.Namespace) -> int:
    value = get_path(load_config(), args.key, _MISSING)
    if value is _MISSING:
        print(f"{args.key} is not a known setting")
        return 1
    print(yaml.safe_dump(value, sort_keys=False).rstrip() if isinstance(value, (dict, list)) else value)
    return 0


def run_set(args: argparse.Namespace) -> int:
    config_set(args.key, parse_cli_value(args.value))
    print(f"{args.key} = {get_path(load_config(), args.key)!r}")
    return 0


def run_unset(args: argparse.Namespace) -> int:
    removed = config_unset(args.key)
    print(f"{args.key} reset to its default" if removed else f"{args.key} was not set")
    return 0


def run_path(args: argparse.Namespace) -> int:
    print(get_config_path())
    return 0


def run_env(args: argparse.Namespace) -> int:
    values = read_env_file()
    print(f"# {get_env_path()}")
    for name in sorted(values):
        print(f"{name}={mask_secret(values[name])}")
    return 0


def run_edit(args: argparse.Namespace) -> int:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
    return subprocess.call([*shlex.split(editor), str(path)])  # noqa: S603


def run_migrate(args: argparse.Namespace) -> int:
    print("config.yaml upgraded" if migrate_config_file() else "config.yaml is already current")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("config", help="show or change settings")
    parser.set_defaults(handler=run_show, all=False)
    actions = parser.add_subparsers(dest="config_action")
    show = actions.add_parser("show", help="print the settings you changed")
    show.add_argument("--all", action="store_true", help="include defaults")
    show.set_defaults(handler=run_show)
    get = actions.add_parser("get", help="print one value")
    get.add_argument("key")
    get.set_defaults(handler=run_get)
    setter = actions.add_parser("set", help="set a value (dotted key)")
    setter.add_argument("key")
    setter.add_argument("value")
    setter.set_defaults(handler=run_set)
    unset = actions.add_parser("unset", help="return a value to its default")
    unset.add_argument("key")
    unset.set_defaults(handler=run_unset)
    actions.add_parser("path", help="print the config file path").set_defaults(handler=run_path)
    actions.add_parser("env", help="list stored secrets (masked)").set_defaults(handler=run_env)
    actions.add_parser("edit", help="open config.yaml in $EDITOR").set_defaults(handler=run_edit)
    actions.add_parser("migrate", help="upgrade config.yaml to the current version").set_defaults(handler=run_migrate)
