"""``clite uninstall``: remove the package and optionally purge the home directory."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from clite.cli.subcommands.update import detect_install_method
from clite.core.constants import get_home


def run_uninstall(args: argparse.Namespace) -> int:
    method = detect_install_method()
    print(f"Uninstalling c-lite (installed via {method})…")

    if method == "pipx":
        pipx_bin = shutil.which("pipx") or "pipx"
        subprocess.run([pipx_bin, "uninstall", "c-lite"])  # noqa: S603 - fixed pipx argv, no shell
    elif method == "pip":
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "c-lite"])
    else:
        print("Running from a git checkout. Remove the directory manually to uninstall.")

    if args.purge:
        home = get_home()
        if not args.yes:
            answer = input(f"Permanently remove all agent data in {home}? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print("Purge skipped.")
                return 0

        if home.exists():
            shutil.rmtree(home)
            print(f"Purged home directory: {home}")

    print("Uninstallation complete.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("uninstall", help="uninstall c-lite and optionally purge data")
    parser.add_argument("--purge", action="store_true", help="also remove the home directory and data")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation before purging")
    parser.set_defaults(handler=run_uninstall)
