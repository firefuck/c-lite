"""Moonshot, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://platform.kimi.ai/docs/quickstart
- https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider


class MoonshotProfile(ProviderProfile):
    def resolve_temperature(self, model: str, requested: float | None) -> float | None:
        # K2.6 fixes sampling by thinking mode; let the server choose its default.
        if model == "kimi-k2.6":
            return None
        return super().resolve_temperature(model, requested)


register_provider(
    MoonshotProfile(
        name="moonshot",
        display_name="Moonshot",
        description="Moonshot API",
        env_vars=("MOONSHOT_API_KEY",),
        base_url="https://api.moonshot.ai/v1",
        base_url_env="MOONSHOT_BASE_URL",
        fallback_models=("kimi-k2.6",),
        context_lengths={"kimi-k2.6": 256_000},
    )
)
