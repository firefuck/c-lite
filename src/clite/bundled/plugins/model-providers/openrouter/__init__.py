"""OpenRouter: an aggregator. One key reaches models from many vendors."""

from __future__ import annotations

from typing import Any

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

_EFFORTS = {"minimal", "low", "medium", "high"}


class OpenRouterProfile(ProviderProfile):
    def build_extra_body(
        self, *, model: str, reasoning_effort: str = "", session_id: str = "", show_reasoning: bool = False
    ) -> dict[str, Any]:
        if reasoning_effort == "none":
            return {"reasoning": {"enabled": False}}
        if reasoning_effort in _EFFORTS:
            return {"reasoning": {"effort": reasoning_effort}}
        return {}

    def wants_cache_markers(self, model: str) -> bool:
        # Anthropic models behind OpenRouter honour cache_control breakpoints; most other
        # vendors cache automatically and reject or ignore the marker.
        return model.startswith("anthropic/") or "claude" in model

    def build_oauth_authorize_url(
        self, *, redirect_uri: str, code_challenge: str, state: str
    ) -> str:
        from urllib.parse import urlencode

        params = {
            "callback_url": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.oauth_authorize_url}?{urlencode(params)}"

    def exchange_oauth_code(
        self, *, code: str, code_verifier: str, redirect_uri: str, http_post: Any
    ) -> dict[str, Any]:
        payload = {
            "code": code,
            "code_verifier": code_verifier,
            "code_challenge_method": "S256",
        }
        resp = http_post(self.oauth_token_url, json_data=payload)
        key = str(resp.get("key") or resp.get("access_token") or "")
        return {"access_token": key, "token_type": "Bearer"}


register_provider(
    OpenRouterProfile(
        name="openrouter",
        display_name="OpenRouter",
        description="One key, many models (routes to the vendor)",
        signup_url="https://openrouter.ai/keys",
        env_vars=("OPENROUTER_API_KEY",),
        base_url="https://openrouter.ai/api/v1",
        base_url_env="OPENROUTER_BASE_URL",
        default_headers={"HTTP-Referer": "https://github.com/", "X-Title": "C-lite"},
        oauth_authorize_url="https://openrouter.ai/auth",
        oauth_token_url="https://openrouter.ai/api/v1/auth/keys",
    )
)
