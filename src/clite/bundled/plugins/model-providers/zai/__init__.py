"""Z.ai, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://docs.z.ai/guides/llm/glm-4.7
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="zai",
        display_name="Z.ai",
        description="Z.ai API",
        env_vars=("ZAI_API_KEY",),
        base_url="https://api.z.ai/api/paas/v4",
        base_url_env="ZAI_BASE_URL",
        fallback_models=("glm-4.7",),
        context_lengths={"glm-4.7": 200_000},
    )
)
