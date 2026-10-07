"""OpenAI, with profile-selected Chat Completions or Responses.

Sources checked 2026-10-07: https://developers.openai.com/api/docs/models/gpt-5-codex
(Responses-only), https://developers.openai.com/api/docs/guides/reasoning and
https://developers.openai.com/api/docs/guides/migrate-to-responses (stateless reasoning
replay and reasoning effort). Unknown model IDs keep the configured protocol; callers can
select Responses explicitly without expanding an unverified model-name heuristic.
"""

from __future__ import annotations

from typing import Any

from clite.providers.base import API_MODE_RESPONSES, ProviderProfile
from clite.providers.registry import register_provider

_EFFORTS = {"minimal", "low", "medium", "high"}


class OpenAIProfile(ProviderProfile):
    def resolve_api_mode(self, model: str) -> str:
        if model == "gpt-5-codex" or model.startswith("gpt-5-codex-"):
            return API_MODE_RESPONSES
        return super().resolve_api_mode(model)

    def replay_is_prefix_bound(self, model: str) -> bool:
        # Explicit Responses routes also need opaque reasoning dropped after compression.
        return True

    def build_extra_body(self, *, model: str, reasoning_effort: str = "", session_id: str = "",
                         show_reasoning: bool = False) -> dict[str, Any]:
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
