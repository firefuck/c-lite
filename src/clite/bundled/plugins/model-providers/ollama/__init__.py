"""Ollama: models running on this machine. No key."""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="ollama",
        display_name="Ollama (local)",
        description="Models served locally by Ollama",
        signup_url="https://ollama.com/download",
        auth_type="none",
        base_url="http://localhost:11434/v1",
        base_url_env="OLLAMA_BASE_URL",
        auto_select=False,
    )
)
