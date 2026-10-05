"""OpenAI, over Chat Completions."""

from __future__ import annotations

from typing import Any

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

_EFFORTS = {"minimal", "low", "medium", "high"}


class OpenAIProfile(ProviderProfile):
    def build_extra_body(self, *, model: str, reasoning_effort: str = "", session_id: str = "") -> dict[str, Any]:
        return {"reasoning_effort": reasoning_effort} if reasoning_effort in _EFFORTS else {}


register_provider(
    OpenAIProfile(
        name="openai",
        display_name="OpenAI",
        description="OpenAI API",
        signup_url="https://platform.openai.com/api-keys",
        env_vars=("OPENAI_API_KEY",),
        base_url="https://api.openai.com/v1",
        base_url_env="OPENAI_BASE_URL",
        max_tokens_param="max_completion_tokens",
    )
)
