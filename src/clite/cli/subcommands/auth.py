"""``clite auth``: log in, inspect, and log out of OAuth model providers.

Tokens are persisted in ``<home>/auth.json`` with restricted permissions (0600) and refreshed
automatically. Access tokens are registered as credentials and redacted from command logs.

    clite auth login openrouter
    clite auth status
    clite auth logout openrouter
"""

from __future__ import annotations

import argparse
import json

from clite.core.errors import CliteError
from clite.providers.oauth import delete_provider_tokens, list_auth_statuses, login


def run_login(args: argparse.Namespace) -> int:
    provider = args.provider.strip()
    if not provider:
        raise CliteError("provider name is required")

    def _on_url(url: str) -> None:
        print(f"Opening browser for authorization. If it does not open, visit:\n  {url}\n")

    def _on_prompt(verification_uri: str, user_code: str, verification_uri_complete: str) -> None:
        print(f"\nTo authenticate with {provider}:")
        print(f"  1. Visit: {verification_uri}")
        print(f"  2. Enter code: {user_code}\n")
        if verification_uri_complete:
            print(f"Or open directly: {verification_uri_complete}\n")

    try:
        login(
            provider,
            flow=args.flow,
            open_browser=not args.no_browser,
            on_auth_url=_on_url,
            on_device_prompt=_on_prompt,
        )
    except Exception as exc:
        raise CliteError(f"Authentication failed: {exc}") from exc

    print(f"Successfully authenticated with {provider}!")
    return 0


def run_status(args: argparse.Namespace) -> int:
    statuses = list_auth_statuses()
    if getattr(args, "json", False):
        print(json.dumps(statuses, indent=2))
        return 0

    if not statuses:
        print("No OAuth providers authenticated.")
        print("Use `clite auth login <provider>` to log in.")
        return 0

    print("Authenticated OAuth providers:")
    for name, info in sorted(statuses.items()):
        status_str = "expired" if info.get("expired") else "logged in"
        refresh_str = "refresh token available" if info.get("has_refresh_token") else "no refresh token"
        print(f"  {name}: {status_str} ({refresh_str})")
    return 0


def run_logout(args: argparse.Namespace) -> int:
    provider = args.provider.strip()
    if not provider:
        raise CliteError("provider name is required")

    removed = delete_provider_tokens(provider)
    if removed:
        print(f"Logged out from {provider}.")
    else:
        print(f"Provider {provider!r} was not logged in.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("auth", help="manage OAuth authentication for model providers")
    parser.set_defaults(handler=run_status)
    actions = parser.add_subparsers(dest="auth_action")

    login_parser = actions.add_parser("login", help="authenticate with an OAuth provider")
    login_parser.add_argument("provider", help="provider name (e.g. openrouter)")
    login_parser.add_argument(
        "--flow", choices=("pkce", "device_code", "device-code"), default=None, help="OAuth flow to use"
    )
    login_parser.add_argument("--no-browser", action="store_true", help="do not open browser automatically")
    login_parser.set_defaults(handler=run_login)

    status_parser = actions.add_parser("status", help="show OAuth authentication status")
    status_parser.add_argument("--json", action="store_true", help="output status as JSON")
    status_parser.set_defaults(handler=run_status)

    logout_parser = actions.add_parser("logout", help="log out and clear OAuth credentials")
    logout_parser.add_argument("provider", help="provider name to log out from")
    logout_parser.set_defaults(handler=run_logout)
