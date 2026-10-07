"""Mistral, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://docs.mistral.ai/api/endpoint/chat
- https://docs.mistral.ai/models/mistral-small-4-0-26-03
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="mistral",
        display_name="Mistral",
        description="Mistral API",
        env_vars=('MISTRAL_API_KEY',),
        base_url="https://api.mistral.ai/v1",
        base_url_env="MISTRAL_BASE_URL",
        fallback_models=('mistral-small-2603',),
        context_lengths={'mistral-small-2603': 256_000},
    )
)
