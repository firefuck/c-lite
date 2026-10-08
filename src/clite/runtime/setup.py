"""Applying a provider choice: shared by ``clite setup`` and the setup screens of the UIs."""

from __future__ import annotations

from typing import Any

from clite.core.config import atomic_config_update
from clite.core.env import save_secret
from clite.core.errors import CliteError
from clite.providers.registry import get_provider, list_providers
from clite.providers.runtime import RuntimeRoute


def verify_provider_key(
    provider_name: str,
    api_key: str = "",
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> tuple[bool, str]:
    """Test the provider credentials with one real model call.

    Returns ``(True, "ok")`` on success, or ``(False, error_message)`` if the key or
    connection is rejected.
    """
    profile = get_provider(provider_name)
    if profile is None:
        return False, f"unknown provider {provider_name!r}"
    if profile.api_mode == "mock":
        return True, "ok"

    chosen_model = (
        model
        or profile.default_model
        or (profile.fallback_models[0] if profile.fallback_models else "default")
    )
    route = RuntimeRoute(
        provider=profile.name,
        model=chosen_model,
        api_mode=profile.api_mode,
        base_url=base_url or profile.base_url,
        api_key=api_key,
        profile=profile,
    )
    try:
        from clite.providers.client import LLMClient

        client = LLMClient()
        client.complete(
            route,
            messages=[{"role": "user", "content": "ping"}],
            stream=False,
        )
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def apply_setup(
    provider_name: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    toolsets: list[str] | None = None,
    approval_mode: str | None = None,
    telegram_token: str | None = None,
) -> dict[str, Any]:
    """Store the key in ``.env`` and the provider, model, and preferences in ``config.yaml``."""
    profile = get_provider(provider_name)
    if profile is None:
        raise CliteError(
            f"unknown provider {provider_name!r}; choose from: {', '.join(p.name for p in list_providers())}"
        )
    if api_key:
        if not profile.env_vars:
            raise CliteError(f"provider {profile.name!r} does not take an API key")
        save_secret(profile.env_vars[0], api_key)
    if telegram_token:
        save_secret("TELEGRAM_BOT_TOKEN", telegram_token)

    chosen_model = model or profile.default_model

    def mutate(document: dict[str, Any]) -> None:
        existing = document.get("model")
        section: dict[str, Any] = existing if isinstance(existing, dict) else {}
        section["provider"] = profile.name
        if chosen_model:
            section["default"] = chosen_model
        if base_url:
            section["base_url"] = base_url
        else:
            section.pop("base_url", None)
        document["model"] = section

        if toolsets is not None:
            document["toolsets"] = toolsets

        if approval_mode is not None:
            approvals = document.get("approvals")
            app_section: dict[str, Any] = approvals if isinstance(approvals, dict) else {}
            app_section["mode"] = approval_mode
            document["approvals"] = app_section

    atomic_config_update(mutate)
    result: dict[str, Any] = {"provider": profile.name, "model": chosen_model}
    if toolsets is not None:
        result["toolsets"] = toolsets
    if approval_mode is not None:
        result["approval_mode"] = approval_mode
    return result
