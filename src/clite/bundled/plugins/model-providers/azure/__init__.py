"""Azure OpenAI deployment routes, over Chat Completions.

Reference checked 2026-10-07:
https://learn.microsoft.com/en-us/azure/ai-services/openai/reference
The resource URL optionally carries api-version; model is the deployment name.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from clite.core.errors import ProviderError
from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider
from clite.providers.transports.types import HttpRequest


class AzureProfile(ProviderProfile):
    def prepare_request(self, route: Any, request: HttpRequest) -> HttpRequest:
        if route.api_mode != self.api_mode:
            raise ProviderError("This deployment profile supports chat_completions only.")
        parts = urlsplit(route.base_url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if parts.path not in ("", "/") or parts.fragment or parts.username or parts.password:
            raise ProviderError("Use the resource root URL, optionally with ?api-version=VERSION.")
        if set(query) - {"api-version"} or len(query.get("api-version", [])) > 1:
            raise ProviderError("Use only one api-version parameter on the resource URL.")
        version = query.get("api-version", ["2024-10-21"])[0]
        if not version:
            raise ProviderError("api-version cannot be empty.")
        path = "/openai/deployments/" + quote(route.model, safe="") + "/chat/completions"
        return HttpRequest(
            url=urlunsplit((parts.scheme, parts.netloc, path, urlencode({"api-version": version}), "")),
            headers=dict(request.headers),
            body={k: v for k, v in request.body.items() if k != "model"},
        )


register_provider(
    AzureProfile(
        name="azure",
        display_name="Azure OpenAI",
        description="Azure OpenAI deployment (resource URL + API version)",
        env_vars=("AZURE_OPENAI_API_KEY",),
        base_url="",
        base_url_env="AZURE_OPENAI_ENDPOINT",
        auth_header="api-key",
        auth_scheme="",
        auto_select=False,
        supports_model_listing=False,
        fallback_models=(),
        context_lengths={},
    )
)
