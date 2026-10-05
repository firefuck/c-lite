"""``clite gateway``: run the messaging gateway and manage who may talk to it."""

from __future__ import annotations

import argparse
import threading
import time

from clite.core.config import get_path, load_config
from clite.gateway.pairing import PairingStore


def run_gateway(args: argparse.Namespace) -> int:
    from clite.gateway.runner import GatewayRunner

    runner = GatewayRunner()
    started = runner.start()
    if not started:
        print("No platform started. Enable one under gateway.platforms in config.yaml (see `clite gateway status`).")
        runner.stop()
        return 1
    print(f"Gateway running: {', '.join(started)}. Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        runner.stop()
    return 0


def run_status(args: argparse.Namespace) -> int:
    import clite.gateway.platforms.local  # noqa: F401
    import clite.gateway.platforms.telegram  # noqa: F401
    from clite.gateway.platforms.base import PLATFORMS
    from clite.plugins.manager import ensure_plugins_loaded

    ensure_plugins_loaded()
    configured = get_path(load_config(), "gateway.platforms", {}) or {}
    print(f"Adapters installed: {', '.join(sorted(PLATFORMS))}")
    if not configured:
        print("No platform is configured. Example:\n\n  gateway:\n    platforms:\n      telegram:\n        enabled: true\n"
              "        allowed_users: [123456789]\n\nand TELEGRAM_BOT_TOKEN in .env.")
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
            print(f"pending   {platform:<10} {code}  {entry['user_name'] or entry['user_id']}  (expires in {minutes} min)")
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


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("gateway", help="run the messaging gateway")
    parser.set_defaults(handler=run_status)
    actions = parser.add_subparsers(dest="gateway_action")
    actions.add_parser("run", help="start the gateway (stays in the foreground)").set_defaults(handler=run_gateway)
    actions.add_parser("status", help="show configured platforms").set_defaults(handler=run_status)
    pair = actions.add_parser("pair", help="approve users who asked for access")
    pair.set_defaults(handler=run_pair_list)
    pair_actions = pair.add_subparsers(dest="pair_action")
    pair_actions.add_parser("list", help="pending codes and approved users").set_defaults(handler=run_pair_list)
    approve = pair_actions.add_parser("approve", help="approve the user holding a code")
    approve.add_argument("platform")
    approve.add_argument("code")
    approve.set_defaults(handler=run_pair_approve)
    revoke = pair_actions.add_parser("revoke", help="remove an approved user")
    revoke.add_argument("platform")
    revoke.add_argument("user_id")
    revoke.set_defaults(handler=run_pair_revoke)
