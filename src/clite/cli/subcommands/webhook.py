"""``clite webhook``: manage names and HMAC secrets for inbound webhooks."""

from __future__ import annotations

import argparse
import re
import secrets

from clite.core.config import atomic_config_update, get_path, load_config
from clite.core.env import remove_secret, save_secret
from clite.server.webhooks import webhook_secret_name

_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def run_add(args: argparse.Namespace) -> int:
    if not _NAME.fullmatch(args.name):
        print("Webhook name may contain only letters, numbers, hyphens, and underscores.")
        return 2
    secret = secrets.token_urlsafe(32)

    def update(document: dict) -> None:
        document.setdefault("webhooks", {})[args.name] = {
            "enabled": True,
            "prompt": args.prompt,
            "deliver": args.deliver,
        }
        document.setdefault("server", {})["webhooks_enabled"] = True

    atomic_config_update(update)
    save_secret(webhook_secret_name(args.name), secret)
    print(f"Webhook {args.name!r} added. HMAC secret: {secret}")
    return 0


def run_list(args: argparse.Namespace) -> int:
    hooks = get_path(load_config(), "webhooks", {}) or {}
    if not hooks:
        print("No webhooks are configured.")
    for name, spec in hooks.items():
        print(f"{name}\t{spec.get('deliver') or '(no delivery target)'}")
    return 0


def run_remove(args: argparse.Namespace) -> int:
    removed = False

    def update(document: dict) -> None:
        nonlocal removed
        hooks = document.get("webhooks", {})
        if args.name in hooks:
            del hooks[args.name]
            removed = True

    atomic_config_update(update)
    remove_secret(webhook_secret_name(args.name))
    print(f"Removed webhook {args.name!r}." if removed else "No such webhook.")
    return 0 if removed else 1


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("webhook", help="manage inbound HMAC webhooks")
    actions = parser.add_subparsers(dest="webhook_action", required=True)
    add = actions.add_parser("add", help="add a webhook and print its one-time secret")
    add.add_argument("name")
    add.add_argument("--prompt", default="Process this webhook payload.")
    add.add_argument("--deliver", default="")
    add.set_defaults(handler=run_add)
    actions.add_parser("list", help="list configured webhooks").set_defaults(handler=run_list)
    remove = actions.add_parser("remove", help="remove a webhook")
    remove.add_argument("name")
    remove.set_defaults(handler=run_remove)
