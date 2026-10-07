"""Together, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://docs.together.ai/docs/openai-api-compatibility
- https://docs.together.ai/docs/serverless/models
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="together",
        display_name="Together",
        description="Together API",
        env_vars=('TOGETHER_API_KEY',),
        base_url="https://api.together.ai/v1",
        base_url_env="TOGETHER_BASE_URL",
        fallback_models=('meta-llama/Llama-3.3-70B-Instruct-Turbo',),
        context_lengths={'meta-llama/Llama-3.3-70B-Instruct-Turbo': 131_072},
    )
)
