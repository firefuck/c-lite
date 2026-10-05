"""``clite model``: show, list and choose models."""

from __future__ import annotations

import argparse

from clite.core.errors import CliteError
from clite.providers.model_switch import switch_model
from clite.providers.models import get_context_length, list_models
from clite.providers.registry import list_providers
from clite.providers.runtime import resolve_runtime_provider


def run_show(args: argparse.Namespace) -> int:
    try:
        route = resolve_runtime_provider()
    except CliteError as exc:
        print(f"No model configured: {exc}")
        return 1
    print(f"Model:    {route.model}")
    print(f"Provider: {route.provider} ({route.api_mode})")
    print(f"Endpoint: {route.base_url or '(local)'}")
    print(f"Context:  {get_context_length(route):,} tokens")
    print(f"Source:   {route.source}")
    return 0


def run_list(args: argparse.Namespace) -> int:
    names = [args.provider] if args.provider else [p.name for p in list_providers() if p.is_configured()]
    if not names:
        print("No provider is configured. Run `clite setup`.")
        return 1
    for name in names:
        models = list_models(name, refresh=args.refresh)
        print(f"{name}: {len(models)} models")
        for model in models:
            window = f"  {model.context_length:,} tokens" if model.context_length else ""
            print(f"  {model.id}{window}")
    return 0


def run_set(args: argparse.Namespace) -> int:
    result = switch_model(args.model, provider=args.provider, persist=True)
    print(result.message)
    return 0 if result.success else 1


def run_providers(args: argparse.Namespace) -> int:
    for profile in list_providers():
        state = "ready" if profile.is_configured() else f"needs {' or '.join(profile.env_vars) or 'setup'}"
        print(f"{profile.name:<12} {state:<34} {profile.description}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("model", help="show, list or set the model")
    parser.set_defaults(handler=run_show)
    actions = parser.add_subparsers(dest="model_action")
    actions.add_parser("show", help="show the current model").set_defaults(handler=run_show)
    listing = actions.add_parser("list", help="list models from configured providers")
    listing.add_argument("provider", nargs="?")
    listing.add_argument("--refresh", action="store_true", help="ignore the cached catalog")
    listing.set_defaults(handler=run_list)
    setter = actions.add_parser("set", help="set the default model")
    setter.add_argument("model", help="model id, or provider:model")
    setter.add_argument("--provider")
    setter.set_defaults(handler=run_set)
    actions.add_parser("providers", help="list providers").set_defaults(handler=run_providers)
