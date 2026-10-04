"""Offline provider: no network, no key. See ``clite.providers.transports.mock``."""

from __future__ import annotations

from clite.providers.base import API_MODE_MOCK, ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="mock",
        display_name="Mock (offline)",
        description="Deterministic offline replies for demos and end-to-end tests",
        api_mode=API_MODE_MOCK,
        auth_type="none",
        supports_model_listing=False,
        auto_select=False,
        default_model="mock-1",
        fallback_models=("mock-1",),
        context_lengths={"mock-": 32_000},
    )
)
