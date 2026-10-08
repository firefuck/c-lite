"""``clite setup``: interactive wizard and non-interactive provider configuration."""

from __future__ import annotations

import argparse
import getpass
import sys

from clite.core.config import load_config
from clite.core.constants import display_home
from clite.core.env import get_secret, mask_secret
from clite.core.errors import CliteError
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


def run_setup(args: argparse.Namespace) -> int:
    current_cfg = load_config()
    current_model_sec = current_cfg.get("model", {})
    curr_provider = current_model_sec.get("provider", "") if isinstance(current_model_sec, dict) else ""
    curr_model = current_model_sec.get("default", "") if isinstance(current_model_sec, dict) else ""

    # Non-interactive mode via command line flags
    if args.provider:
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

    if not sys.stdin.isatty():
        raise CliteError(
            "setup is interactive; in a script use: clite setup --provider NAME --api-key KEY --model MODEL"
        )

    print(f"Setting up {display_home()}\n")

    # Step 1: Choose provider
    providers = list_providers()

    labels = [f"{p.name:<12} {p.description}" for p in providers]
    def_p_idx = 0
    for idx, p in enumerate(providers):
        if p.name == curr_provider:
            def_p_idx = idx
            break

    print("Step 1: Choose an AI provider")
    selected_label = _choose("Provider", labels, default_index=def_p_idx)
    profile = providers[labels.index(selected_label)]

    # Step 2: API Key and Verification
    api_key = None
    key_for_test = ""
    if profile.auth_type == "api_key" and profile.env_vars:
        existing = get_secret(profile.env_vars[0])
        hint = f" [keep {mask_secret(existing)}]" if existing else ""
        if profile.signup_url:
            print(f"\nGet a key at {profile.signup_url}")

        prompt_str = f"Enter {profile.env_vars[0]}{hint}: "
        entered = getpass.getpass(prompt_str).strip()
        if entered:
            api_key = entered
            key_for_test = entered
        elif existing:
            key_for_test = existing
        else:
            raise CliteError("an API key is required for this provider")

    base_url = None
    if not profile.base_url:
        base_url = input("\nBase URL of endpoint (e.g. http://localhost:8000/v1): ").strip() or None

    # Verify key with one real test call
    if key_for_test and profile.api_mode != "mock":
        print("\nVerifying credentials with a test call…")
        ok, err = verify_provider_key(profile.name, key_for_test, base_url=base_url)
        if not ok:
            print(f"Verification failed: {err}")
            raise CliteError(f"API key rejected by {profile.name}: {err}")
        print("✓ Key verified successfully!")

    # Step 3: Choose model
    print("\nStep 2: Choose a model")
    models = fetch_models(profile, api_key=key_for_test, base_url=base_url or "") or []
    names = [m.id for m in models] or list(profile.fallback_models)
    def_m_idx = 0
    if curr_model and curr_model in names:
        def_m_idx = names.index(curr_model)
    elif profile.default_model in names:
        def_m_idx = names.index(profile.default_model)

    if names:
        shown = names[:30]
        model = _choose("Model", shown, default_index=def_m_idx) if len(shown) > 1 else shown[0]
    else:
        model = input(f"Enter model id [{profile.default_model}]: ").strip() or profile.default_model

    # Step 4: Choose toolsets
    print("\nStep 3: Toolsets")
    toolset_options = [
        "clite-cli (all standard tools: files, terminal, web)",
        "file (safe file-only operations)",
        "file terminal (code and terminal without network tools)",
    ]
    toolset_choice = _choose("Toolsets", toolset_options, default_index=0)
    if "safe file-only" in toolset_choice:
        chosen_toolsets = ["file"]
    elif "without network" in toolset_choice:
        chosen_toolsets = ["file", "terminal"]
    else:
        chosen_toolsets = ["clite-cli"]

    # Step 5: Optional approval mode & messaging
    print("\nStep 4: Safety & Approvals")
    approval_options = [
        "manual (ask about dangerous commands)",
        "smart (use AI to classify dangers)",
        "off (yolo mode: run without prompting)",
    ]
    app_choice = _choose("Approval Mode", approval_options, default_index=0)
    chosen_approval = "manual"
    if "smart" in app_choice:
        chosen_approval = "smart"
    elif "off" in app_choice:
        chosen_approval = "off"

    # Step 6: Optional messaging platform
    print("\nStep 5: Optional Telegram Bot (Enter to skip)")
    tg_token = input("Telegram Bot Token [skip]: ").strip() or None

    # Apply setup
    result = apply_setup(
        profile.name,
        api_key=api_key,
        model=model,
        base_url=base_url,
        toolsets=chosen_toolsets,
        approval_mode=chosen_approval,
        telegram_token=tg_token,
    )
    route = resolve_runtime_provider()
    print(f"\n✓ Setup complete! Ready: {route.model} via {result['provider']}.")
    print("Start chatting with `clite`.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
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
