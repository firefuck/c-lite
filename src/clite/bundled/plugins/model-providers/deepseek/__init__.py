"""DeepSeek, over Chat Completions."""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="deepseek",
        display_name="DeepSeek",
        description="DeepSeek API",
        signup_url="https://platform.deepseek.com/api_keys",
        env_vars=("DEEPSEEK_API_KEY",),
        base_url="https://api.deepseek.com/v1",
        base_url_env="DEEPSEEK_BASE_URL",
    )
)
