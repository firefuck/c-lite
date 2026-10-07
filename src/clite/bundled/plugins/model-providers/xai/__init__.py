"""xAI, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://docs.x.ai/developers/models
- https://docs.x.ai/developers/model-capabilities/legacy/chat-completions
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="xai",
        display_name="xAI",
        description="xAI API",
        env_vars=('XAI_API_KEY',),
        base_url="https://api.x.ai/v1",
        base_url_env="XAI_BASE_URL",
        fallback_models=('grok-4.7',),
        context_lengths={'grok-4.7': 500_000},
    )
)
