"""``clite setup``: choose a provider, store its key, pick a model."""

from __future__ import annotations

import argparse
import getpass
import sys

from clite.core.constants import display_home
from clite.core.env import get_secret, mask_secret
from clite.core.errors import CliteError
from clite.providers.models import fetch_models
from clite.providers.registry import list_providers
from clite.providers.runtime import resolve_runtime_provider
from clite.runtime.setup import apply_setup


def _choose(prompt: str, options: list[str]) -> str:
    for number, option in enumerate(options, start=1):
        print(f"  {number}. {option}")
    while True:
        answer = input(f"{prompt} [1-{len(options)}]: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        if answer in options:
            return answer
        print("  Please enter one of the numbers above.")


def run_setup(args: argparse.Namespace) -> int:
    if args.provider:
        result = apply_setup(args.provider, api_key=args.api_key, model=args.model, base_url=args.base_url)
        print(f"Saved: provider {result['provider']}, model {result['model'] or '(not chosen yet)'}")
        return 0
    if not sys.stdin.isatty():
        raise CliteError("setup is interactive; in a script use: clite setup --provider NAME --api-key KEY --model MODEL")

    print(f"Setting up {display_home()}\n\nWhich provider?")
    providers = [profile for profile in list_providers() if profile.name != "mock"]
    labels = [f"{profile.name:<12} {profile.description}" for profile in providers]
    profile = providers[labels.index(_choose("Provider", labels))]

    api_key = None
    if profile.auth_type == "api_key" and profile.env_vars:
        existing = get_secret(profile.env_vars[0])
        hint = f" [keep {mask_secret(existing)}]" if existing else ""
        if profile.signup_url:
            print(f"\nGet a key at {profile.signup_url}")
        api_key = getpass.getpass(f"{profile.env_vars[0]}{hint}: ").strip() or None
        if not api_key and not existing:
            raise CliteError("an API key is required for this provider")

    base_url = None
    if not profile.base_url:
        base_url = input("Base URL of the OpenAI-compatible endpoint (e.g. http://localhost:8000/v1): ").strip()

    key = api_key or (get_secret(profile.env_vars[0]) if profile.env_vars else "") or ""
    print("\nFetching the model list…")
    models = fetch_models(profile, api_key=key, base_url=base_url or "") or []
    names = [model.id for model in models] or list(profile.fallback_models)
    if names:
        shown = names[:30]
        model = _choose("Model", shown) if len(shown) > 1 else shown[0]
    else:
        model = input("Could not list models. Enter the model id: ").strip()

    result = apply_setup(profile.name, api_key=api_key, model=model, base_url=base_url)
    route = resolve_runtime_provider()
    print(f"\nReady: {route.model} via {result['provider']}. Start with `clite`.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("setup", help="choose a provider, store its API key and pick a model")
    parser.add_argument("--provider", help="provider name (skips the questions)")
    parser.add_argument("--api-key", help="API key to store in .env")
    parser.add_argument("--model", help="default model id")
    parser.add_argument("--base-url", help="endpoint for a custom provider")
    parser.set_defaults(handler=run_setup)
