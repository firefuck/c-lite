"""DeepSeek, over Chat Completions.

Vision: the image-input model is a separate id (``deepseek-v4-flash-vision-exp``); the chat
and reasoner models are text-only. Source checked 2026-10-07:
https://api-docs.deepseek.com/guides/vision/ (``deepseek-v4-flash-vision-exp`` "accepts images
alongside text") and https://api-docs.deepseek.com/api/create-chat-completion (content parts
for image input). An empty ``vision_models`` would wrongly tell the agent every DeepSeek model
sees, so the vision model is named here and everything else is treated as blind.
"""

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
        vision_models=("deepseek-v4-flash-vision-exp",),
    )
)
