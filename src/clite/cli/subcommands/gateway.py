"""``clite gateway``: run the messaging gateway and manage who may talk to it."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time

from clite.core.config import get_path, load_config
from clite.gateway.pairing import PairingStore


def run_gateway(args: argparse.Namespace) -> int:
    from clite.gateway.runner import GatewayRunner
    from clite.gateway.service import run_service

    return run_service(GatewayRunner())


def _service_command(action: str) -> int:
    from clite.core.profiles import get_active_profile_name
    from clite.gateway.service import service_name, service_path

    path = service_path()
    if sys.platform == "darwin":
        command = ["launchctl", action, str(path)]
    else:
        command = ["systemctl", "--user", action, f"{service_name(get_active_profile_name())}.service"]
    if shutil.which(command[0]) is None:
        print(f"{command[0]} is not available on this system.")
        return 1
    return subprocess.run(command, check=False).returncode  # noqa: S603 - fixed service-manager argv, no shell


def run_install(args: argparse.Namespace) -> int:
    from clite.gateway.service import install

    path = install(sys.executable)
    print(f"Installed {path}. Start it with `clite gateway start`.")
    return 0


def run_uninstall(args: argparse.Namespace) -> int:
    from clite.gateway.service import uninstall

    path = uninstall()
    print(f"Removed {path}.")
    return 0


def run_start(args: argparse.Namespace) -> int:
    return _service_command("start")


def run_stop(args: argparse.Namespace) -> int:
    return _service_command("stop")


def run_restart(args: argparse.Namespace) -> int:
    return _service_command("restart")


def run_logs(args: argparse.Namespace) -> int:
    if sys.platform == "darwin":
        print("Use Console.app to view the LaunchAgent log.")
        return 0
    from clite.core.profiles import get_active_profile_name
    from clite.gateway.service import service_name

    command = [
        "journalctl",
        "--user-unit",
        f"{service_name(get_active_profile_name())}.service",
        "--no-pager",
    ]
    if shutil.which(command[0]) is None:
        print("journalctl is not available on this system.")
        return 1
    return subprocess.run(command, check=False).returncode  # noqa: S603 - fixed journalctl argv, no shell


def run_status(args: argparse.Namespace) -> int:
    import clite.gateway.platforms.local
    import clite.gateway.platforms.telegram  # noqa: F401
    from clite.gateway.platforms.base import PLATFORMS
    from clite.plugins.manager import ensure_plugins_loaded

    ensure_plugins_loaded()
    configured = get_path(load_config(), "gateway.platforms", {}) or {}
    print(f"Adapters installed: {', '.join(sorted(PLATFORMS))}")
    if not configured:
        print(
            "No platform is configured. Example:\n\n  gateway:\n    platforms:\n      telegram:\n        enabled: true\n"
            "        allowed_users: [123456789]\n\nand TELEGRAM_BOT_TOKEN in .env."
        )
        return 0
    for name, settings in configured.items():
        enabled = isinstance(settings, dict) and settings.get("enabled", True)
        state = "enabled" if enabled else "disabled"
        note = "" if name in PLATFORMS else "  (no adapter installed for this name)"
        print(f"{name:<12} {state}{note}")
    return 0


def run_pair_list(args: argparse.Namespace) -> int:
    listing = PairingStore().list()
    for platform, codes in listing["pending"].items():
        for code, entry in codes.items():
            minutes = max(0, int((entry["expires_at"] - time.time()) / 60))
            print(
                f"pending   {platform:<10} {code}  {entry['user_name'] or entry['user_id']}  (expires in {minutes} min)"
            )
    for platform, users in listing["approved"].items():
        for user_id, entry in users.items():
            print(f"approved  {platform:<10} {user_id}  {entry.get('user_name', '')}")
    if not any(listing["pending"].values()) and not any(listing["approved"].values()):
        print("No pairing requests and no approved users.")
    return 0


def run_pair_approve(args: argparse.Namespace) -> int:
    try:
        user = PairingStore().approve(args.platform, args.code)
    except PermissionError as exc:
        print(str(exc))
        return 1
    if user is None:
        print("That code is not valid (wrong, expired or already used).")
        return 1
    print(f"Approved {user['user_name'] or user['user_id']} on {args.platform}.")
    return 0


def run_pair_revoke(args: argparse.Namespace) -> int:
    if not PairingStore().revoke(args.platform, args.user_id):
        print("No such approved user.")
        return 1
    print(f"Revoked {args.user_id} on {args.platform}.")
    return 0


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("gateway", help="run the messaging gateway")
    parser.set_defaults(handler=run_status)
    actions = parser.add_subparsers(dest="gateway_action")
    actions.add_parser("run", help="start the gateway (stays in the foreground)").set_defaults(
        handler=run_gateway
    )
    actions.add_parser("install", help="install the user service").set_defaults(handler=run_install)
    actions.add_parser("uninstall", help="remove the user service").set_defaults(handler=run_uninstall)
    actions.add_parser("start", help="start the installed service").set_defaults(handler=run_start)
    actions.add_parser("stop", help="stop the installed service").set_defaults(handler=run_stop)
    actions.add_parser("restart", help="restart the installed service").set_defaults(handler=run_restart)
    actions.add_parser("logs", help="show service logs").set_defaults(handler=run_logs)
    actions.add_parser("status", help="show configured platforms").set_defaults(handler=run_status)
    pair = actions.add_parser("pair", help="approve users who asked for access")
    pair.set_defaults(handler=run_pair_list)
    pair_actions = pair.add_subparsers(dest="pair_action")
    pair_actions.add_parser("list", help="pending codes and approved users").set_defaults(
        handler=run_pair_list
    )
    approve = pair_actions.add_parser("approve", help="approve the user holding a code")
    approve.add_argument("platform")
    approve.add_argument("code")
    approve.set_defaults(handler=run_pair_approve)
    revoke = pair_actions.add_parser("revoke", help="remove an approved user")
    revoke.add_argument("platform")
    revoke.add_argument("user_id")
    revoke.set_defaults(handler=run_pair_revoke)
