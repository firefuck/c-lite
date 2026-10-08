"""Groq, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://console.groq.com/docs/models
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="groq",
        display_name="Groq",
        description="Groq API",
        env_vars=("GROQ_API_KEY",),
        base_url="https://api.groq.com/openai/v1",
        base_url_env="GROQ_BASE_URL",
        fallback_models=("llama-3.3-70b-versatile",),
        context_lengths={"llama-3.3-70b-versatile": 131_072},
    )
)
