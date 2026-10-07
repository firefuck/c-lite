"""NVIDIA, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://docs.api.nvidia.com/nim/reference/meta-llama-3_3-70b-instruct
- https://docs.api.nvidia.com/nim/reference/meta-llama-3_3-70b-instruct-infer
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="nvidia",
        display_name="NVIDIA",
        description="NVIDIA API",
        env_vars=('NVIDIA_API_KEY',),
        base_url="https://integrate.api.nvidia.com/v1",
        base_url_env="NVIDIA_BASE_URL",
        fallback_models=('meta/llama-3.3-70b-instruct',),
        context_lengths={'meta/llama-3.3-70b-instruct': 128_000},
    )
)
