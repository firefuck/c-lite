"""OpenAI image generation: a keyed ``ImageProvider`` over the Images API.

Requires ``OPENAI_API_KEY`` in ``.env``; get one at https://platform.openai.com/api-keys. The
key is registered as a credential so it is stripped from commands the agent runs and redacted
from what the model reads.

This is a backend plugin (``kind: backend``): it is auto-loaded, but the ``image_generate``
tool's ``check_fn`` checks whether the key is actually present before offering the tool.

Endpoint and request shape checked 2026-10-08:
https://developers.openai.com/api/docs/guides/image-generation (``POST /v1/images/generations``
with ``model``, ``prompt``, ``size`` and ``n``; the reply carries base64 images under
``data[].b64_json`` next to a ``revised_prompt``). The default model id ``gpt-image-1`` is the
documented GPT Image generation model; ``dall-e-3`` remains available through ``image.model``.
"""

from __future__ import annotations

import base64
import json
import urllib.request

from clite.core.env import SecretSpec, get_secret, register_secret
from clite.tools.image_gen import GeneratedImage, ImageProvider

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
IMAGES_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_MODEL = "gpt-image-1"
# Sizes the Images API documents. gpt-image-1 accepts 1024x1024, 1536x1024 and 1024x1536.
SUPPORTED_SIZES = ("1024x1024", "1536x1024", "1024x1536")
_USER_AGENT = "clite (+image_generate; openai)"

register_secret(SecretSpec(
    OPENAI_API_KEY_ENV,
    "OpenAI API key: image generation (image_generate)",
    category="tool",
    url="https://platform.openai.com/api-keys",
))


class OpenAIImageProvider(ImageProvider):
    name = "openai-images"
    requires_api_key = True
    api_key_env = OPENAI_API_KEY_ENV
    supported_sizes = SUPPORTED_SIZES

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "") -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._base_url = (base_url or IMAGES_URL).rstrip("/")

    def generate(self, prompt: str, *, size: str = "", count: int = 1) -> list[GeneratedImage]:
        key = self._api_key or get_secret(OPENAI_API_KEY_ENV) or ""
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set; add it to .env to generate images")
        payload: dict[str, object] = {"model": self._model, "prompt": prompt, "n": count}
        if size:
            payload["size"] = size
        request = urllib.request.Request(  # noqa: S310 - https is enforced
            self._base_url, data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - https
            body = json.loads(response.read())
        return _parse_images(body)


def _parse_images(body: dict) -> list[GeneratedImage]:
    """Turn an Images API reply into :class:`GeneratedImage` objects."""
    images: list[GeneratedImage] = []
    for item in body.get("data") or []:
        encoded = item.get("b64_json")
        if not encoded:
            continue
        metadata: dict[str, str] = {}
        revised = str(item.get("revised_prompt") or "").strip()
        if revised:
            metadata["revised_prompt"] = revised
        images.append(GeneratedImage(
            media_type=str(item.get("output_format") and f"image/{item['output_format']}" or "image/png"),
            data=base64.b64decode(encoded),
            metadata=metadata,
        ))
    return images


def register(ctx) -> None:
    ctx.register_image_provider("openai-images", OpenAIImageProvider)
