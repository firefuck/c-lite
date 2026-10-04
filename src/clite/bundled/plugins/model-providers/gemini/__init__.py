"""Google Gemini through its OpenAI-compatible endpoint."""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="gemini",
        aliases=("google",),
        display_name="Google Gemini",
        description="Gemini models (OpenAI-compatible endpoint)",
        signup_url="https://aistudio.google.com/apikey",
        env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        base_url_env="GEMINI_BASE_URL",
    )
)
