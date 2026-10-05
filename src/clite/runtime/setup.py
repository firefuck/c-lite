"""Applying a provider choice: shared by ``clite setup`` and the setup screens of the UIs."""

from __future__ import annotations

from typing import Any

from clite.core.config import atomic_config_update
from clite.core.env import save_secret
from clite.core.errors import CliteError
from clite.providers.registry import get_provider, list_providers


def apply_setup(provider_name: str, *, api_key: str | None = None, model: str | None = None,
                base_url: str | None = None) -> dict[str, str]:
    """Store the key in ``.env`` and the provider and model in ``config.yaml``."""
    profile = get_provider(provider_name)
    if profile is None:
        raise CliteError(f"unknown provider {provider_name!r}; choose from: {', '.join(p.name for p in list_providers())}")
    if api_key:
        if not profile.env_vars:
            raise CliteError(f"provider {profile.name!r} does not take an API key")
        save_secret(profile.env_vars[0], api_key)
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

    atomic_config_update(mutate)
    return {"provider": profile.name, "model": chosen_model}
