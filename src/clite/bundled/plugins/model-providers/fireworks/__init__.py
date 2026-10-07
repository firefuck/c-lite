"""Fireworks, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://docs.fireworks.ai/getting-started/quickstart
- https://fireworks.ai/models/fireworks/llama-v3p3-70b-instruct
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="fireworks",
        display_name="Fireworks",
        description="Fireworks API",
        env_vars=('FIREWORKS_API_KEY',),
        base_url="https://api.fireworks.ai/inference/v1",
        base_url_env="FIREWORKS_BASE_URL",
        fallback_models=('accounts/fireworks/models/llama-v3p3-70b-instruct',),
        context_lengths={'accounts/fireworks/models/llama-v3p3-70b-instruct': 131_072},
    )
)
