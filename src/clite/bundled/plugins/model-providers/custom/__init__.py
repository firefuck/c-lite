"""Any OpenAI-compatible endpoint: set ``model.base_url`` (and ``model.api_key_env`` if it
needs a key) in config.yaml. For several named endpoints use the ``providers:`` section."""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="custom",
        display_name="Custom endpoint",
        description="Any OpenAI-compatible server (vLLM, LM Studio, llama.cpp, a proxy)",
        env_vars=("CUSTOM_API_KEY",),
        base_url_env="CUSTOM_BASE_URL",
        auto_select=False,
    )
)
