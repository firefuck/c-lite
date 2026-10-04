"""Anthropic, over the native Messages API (prompt caching, thinking).

Thinking has two wire shapes and the API rejects the wrong one:

* current models take adaptive thinking plus an effort level
  (``thinking: {type: adaptive}``, ``output_config: {effort: ...}``);
* models from the 4.5 generation and earlier take a manual token budget
  (``thinking: {type: enabled, budget_tokens: N}``).

Checked against the Anthropic docs on 2026-10-04. When a new model family ships, this file is
the only place that needs to learn about it.
"""

from __future__ import annotations

import re
from typing import Any

from clite.providers.base import API_MODE_ANTHROPIC, ProviderProfile
from clite.providers.registry import register_provider

# Models that still use a manual thinking budget. Everything newer is adaptive.
_MANUAL_BUDGET_MODELS = re.compile(r"claude-(3|(opus|sonnet|haiku)-4-(0|1|5)(-|$)|(opus|sonnet)-4-20)")
_BUDGETS = {"minimal": 1024, "low": 2048, "medium": 8192, "high": 16384, "xhigh": 24000, "max": 30000}
_EFFORTS = {"minimal": "low", "none": "low", "low": "low", "medium": "medium", "high": "high",
            "xhigh": "xhigh", "max": "max"}


class AnthropicProfile(ProviderProfile):
    def build_extra_body(self, *, model: str, reasoning_effort: str = "", session_id: str = "") -> dict[str, Any]:
        if not reasoning_effort:
            return {}  # the model's own default
        if _MANUAL_BUDGET_MODELS.search(model):
            budget = _BUDGETS.get(reasoning_effort)
            return {"thinking": {"type": "enabled", "budget_tokens": budget}} if budget else {}
        effort = _EFFORTS.get(reasoning_effort)
        if effort is None:
            return {}
        # "none" cannot be expressed as disabled thinking (some models reject that), so it
        # maps to the lowest effort and lets the model skip thinking on simple requests.
        return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}

    def wants_cache_markers(self, model: str) -> bool:
        return True


register_provider(
    AnthropicProfile(
        name="anthropic",
        aliases=("claude",),
        display_name="Anthropic",
        description="Claude models through the native Messages API",
        signup_url="https://console.anthropic.com/",
        api_mode=API_MODE_ANTHROPIC,
        env_vars=("ANTHROPIC_API_KEY",),
        base_url="https://api.anthropic.com",
        base_url_env="ANTHROPIC_BASE_URL",
        auth_header="x-api-key",
        auth_scheme="",
        default_max_tokens=32_000,
        # Used only when the live catalog cannot be fetched. Update when models are retired.
        fallback_models=("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5-20251001"),
        default_aux_model="claude-haiku-4-5-20251001",
        context_lengths={"claude-": 200_000},
    )
)
