"""vLLM, over Chat Completions.

Endpoint and catalog references checked 2026-10-07 (not live API validation):
- https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/

Unsecured local server only. Model ids and context limits belong to the deployment;
select a served model explicitly. Use a custom profile for an authenticated server.
"""

from __future__ import annotations

from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(
    ProviderProfile(
        name="vllm",
        display_name="vLLM",
        description="vLLM local server (no authentication)",
        env_vars=(),
        base_url="http://localhost:8000/v1",
        base_url_env="VLLM_BASE_URL",
        auth_type="none",
        auto_select=False,
        fallback_models=(),
        context_lengths={},
    )
)
