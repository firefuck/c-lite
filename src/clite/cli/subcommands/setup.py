"""``clite setup``: interactive wizard and non-interactive provider configuration."""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Any

from clite.core.config import load_config
from clite.core.constants import display_home
from clite.core.env import get_secret, mask_secret
from clite.core.errors import CliteError
from clite.providers.base import ProviderProfile
from clite.providers.models import fetch_models
from clite.providers.registry import get_provider, list_providers
from clite.providers.runtime import resolve_runtime_provider
from clite.runtime.setup import apply_setup, verify_provider_key


def _choose(prompt: str, options: list[str], default_index: int = 0) -> str:
    for number, option in enumerate(options, start=1):
        is_def = " (default)" if number - 1 == default_index else ""
        print(f"  {number}. {option}{is_def}")
    while True:
        def_hint = f" [{default_index + 1}]" if 0 <= default_index < len(options) else ""
        answer = input(f"{prompt}{def_hint}: ").strip()
        if not answer and 0 <= default_index < len(options):
            return options[default_index]
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        if answer in options:
            return answer
        print("  Please enter one of the numbers above.")


# Wizard choices: the label shown, then the value stored.
_TOOLSET_CHOICES = (
    ("clite-cli (all standard tools: files, terminal, web)", ["clite-cli"]),
    ("file (safe file-only operations)", ["file"]),
    ("file terminal (code and terminal without network tools)", ["file", "terminal"]),
)
_APPROVAL_CHOICES = (
    ("manual (ask about dangerous commands)", "manual"),
    ("smart (use AI to classify dangers)", "smart"),
    ("off (yolo mode: run without prompting)", "off"),
)


def run_setup(args: argparse.Namespace) -> int:
    if args.provider:
        return _setup_from_flags(args)
    if not sys.stdin.isatty():
        raise CliteError(
            "setup is interactive; in a script use: clite setup --provider NAME --api-key KEY --model MODEL"
        )

    model_section = load_config().get("model", {})
    if not isinstance(model_section, dict):
        model_section = {}
    print(f"Setting up {display_home()}\n")

    print("Step 1: Choose an AI provider")
    profile = _ask_provider(model_section.get("provider", ""))
    api_key, key_for_test = _ask_api_key(profile)
    base_url = None
    if not profile.base_url:
        base_url = input("\nBase URL of endpoint (e.g. http://localhost:8000/v1): ").strip() or None
    if key_for_test and profile.api_mode != "mock":
        print("\nVerifying credentials with a test call…")
        ok, err = verify_provider_key(profile.name, key_for_test, base_url=base_url)
        if not ok:
            print(f"Verification failed: {err}")
            raise CliteError(f"API key rejected by {profile.name}: {err}")
        print("✓ Key verified successfully!")

    print("\nStep 2: Choose a model")
    model = _ask_model(profile, key_for_test, base_url, current=model_section.get("default", ""))

    print("\nStep 3: Toolsets")
    toolsets = _ask_from_table("Toolsets", _TOOLSET_CHOICES)

    print("\nStep 4: Safety & Approvals")
    approval_mode = _ask_from_table("Approval Mode", _APPROVAL_CHOICES)

    print("\nStep 5: Optional Telegram Bot (Enter to skip)")
    telegram_token = input("Telegram Bot Token [skip]: ").strip() or None

    result = apply_setup(
        profile.name,
        api_key=api_key,
        model=model,
        base_url=base_url,
        toolsets=toolsets,
        approval_mode=approval_mode,
        telegram_token=telegram_token,
    )
    route = resolve_runtime_provider()
    print(f"\n✓ Setup complete! Ready: {route.model} via {result['provider']}.")
    print("Start chatting with `clite`.")
    return 0


def _setup_from_flags(args: argparse.Namespace) -> int:
    """``clite setup --provider NAME ...``: configure without asking anything."""
    profile = get_provider(args.provider)
    if profile is None:
        raise CliteError(f"unknown provider {args.provider!r}")

    key = args.api_key or (get_secret(profile.env_vars[0]) if profile.env_vars else "") or ""
    if not args.skip_verify and key and profile.api_mode != "mock":
        ok, err = verify_provider_key(profile.name, key, model=args.model, base_url=args.base_url)
        if not ok:
            raise CliteError(f"API key rejected by {profile.name}: {err}")

    result = apply_setup(
        args.provider,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        toolsets=args.toolsets,
        approval_mode=args.approval_mode,
        telegram_token=args.telegram_token,
    )
    print(f"Saved: provider {result['provider']}, model {result['model'] or '(default)'}")
    return 0


def _ask_provider(current: str) -> ProviderProfile:
    providers = list_providers()
    labels = [f"{p.name:<12} {p.description}" for p in providers]
    default = next((index for index, p in enumerate(providers) if p.name == current), 0)
    return providers[labels.index(_choose("Provider", labels, default_index=default))]


def _ask_api_key(profile: ProviderProfile) -> tuple[str | None, str]:
    """``(key to store, key to verify with)``. Enter keeps a stored key: nothing new to store."""
    if profile.auth_type != "api_key" or not profile.env_vars:
        return None, ""
    existing = get_secret(profile.env_vars[0])
    hint = f" [keep {mask_secret(existing)}]" if existing else ""
    if profile.signup_url:
        print(f"\nGet a key at {profile.signup_url}")
    entered = getpass.getpass(f"Enter {profile.env_vars[0]}{hint}: ").strip()
    if entered:
        return entered, entered
    if existing:
        return None, existing
    raise CliteError("an API key is required for this provider")


def _ask_model(profile: ProviderProfile, api_key: str, base_url: str | None, *, current: str) -> str:
    models = fetch_models(profile, api_key=api_key, base_url=base_url or "") or []
    names = [m.id for m in models] or list(profile.fallback_models)
    if not names:
        return input(f"Enter model id [{profile.default_model}]: ").strip() or profile.default_model
    default = 0
    if current and current in names:
        default = names.index(current)
    elif profile.default_model in names:
        default = names.index(profile.default_model)
    shown = names[:30]
    return _choose("Model", shown, default_index=default) if len(shown) > 1 else shown[0]


def _ask_from_table(prompt: str, table: tuple[tuple[str, Any], ...]) -> Any:
    labels = [label for label, _value in table]
    return table[labels.index(_choose(prompt, labels, default_index=0))][1]


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("setup", help="choose a provider, store its API key and pick a model")
    parser.add_argument("--provider", help="provider name (skips the questions)")
    parser.add_argument("--api-key", help="API key to store in .env")
    parser.add_argument("--model", help="default model id")
    parser.add_argument("--base-url", help="endpoint for a custom provider")
    parser.add_argument("--toolsets", nargs="+", help="enabled toolsets (e.g. clite-cli)")
    parser.add_argument("--approval-mode", choices=["manual", "smart", "off"], help="command approval mode")
    parser.add_argument("--telegram-token", help="optional Telegram bot token")
    parser.add_argument("--skip-verify", action="store_true", help="skip live API verification")
    parser.set_defaults(handler=run_setup)
