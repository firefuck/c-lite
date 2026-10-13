"""Google Vertex OpenAI-compatible endpoint using scoped service-account OAuth tokens.

References checked 2026-10-07:
https://cloud.google.com/vertex-ai/generative-ai/docs/migrate/openai/examples
https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.service_account.html
Credentials are JSON in .env, never an SDK default credential chain or external key file.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from clite.core.env import get_secret
from clite.core.errors import AuthError, ProviderError
from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider
from clite.providers.transports.types import HttpRequest

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _account(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("type") != "service_account":
            raise ValueError
        if any(not isinstance(value.get(k), str) or not value[k] for k in ("client_email", "private_key")):
            raise ValueError
        if value.get("token_uri") != TOKEN_URL:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise AuthError(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON to a service-account JSON with the standard OAuth token_uri."
        ) from None


def _validate_endpoint(url: str) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or not re.fullmatch(r"(?:[a-z0-9-]+-)?aiplatform\.googleapis\.com", parts.hostname or "")
        or not re.fullmatch(r"/v1(?:beta1)?/projects/[^/]+/locations/[^/]+/endpoints/[^/]+", parts.path)
    ):
        raise AuthError(
            "Use a Vertex regional OpenAI-compatible endpoint; "
            "a different endpoint requires explicit service-account JSON."
        )


class VertexProfile(ProviderProfile):
    def resolve_credential(self, base_url: str, explicit: str) -> str:
        if not explicit:
            _validate_endpoint(base_url)
        raw = explicit or get_secret("GOOGLE_SERVICE_ACCOUNT_JSON") or ""
        _account(raw)
        return raw

    def authenticate_request(
        self, route: Any, request: HttpRequest, http: Any, *, timeout: float, cancel: Any
    ) -> HttpRequest:
        if route.api_mode != self.api_mode:
            raise ProviderError("This profile supports the OpenAI-compatible chat_completions endpoint only.")
        try:
            from google.oauth2 import service_account
        except ImportError:
            raise ProviderError("Install c-lite[vertex] to use service-account authentication.") from None

        def exchange(
            url: str,
            method: str = "GET",
            body: bytes | None = None,
            headers: dict[str, str] | None = None,
            **kwargs: Any,
        ) -> Any:
            if url != TOKEN_URL or method != "POST":
                raise AuthError("Refusing an unexpected service-account token endpoint.")
            # The SDK signs and parses only. All network I/O stays in the shared HTTP seam,
            # including cancellation, proxy handling and redirect rejection.
            payload = http.request_json(method, url, body, headers, timeout=timeout, cancel=cancel)
            return SimpleNamespace(status=200, data=json.dumps(payload).encode(), headers={})

        try:
            credentials = service_account.Credentials.from_service_account_info(
                _account(route.api_key), scopes=[SCOPE]
            )
            credentials.refresh(exchange)
            token = credentials.token
            if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
                raise ValueError("missing token")
        except Exception:  # noqa: BLE001 - any SDK failure becomes one error that cannot leak the key
            if getattr(cancel, "cancelled", False):
                raise InterruptedError("model call cancelled") from None
            # SDK and HTTP errors may echo the assertion or key; never propagate their text.
            raise AuthError(
                "Service-account token exchange failed. Check the credential and network, then retry."
            ) from None
        return HttpRequest(
            url=request.url,
            headers={**request.headers, "Authorization": "Bearer " + token},
            body=request.body,
        )


register_provider(
    VertexProfile(
        name="vertex",
        display_name="Google Vertex",
        description="Google Vertex service-account JSON (c-lite[vertex])",
        env_vars=("GOOGLE_SERVICE_ACCOUNT_JSON",),
        base_url="",
        auth_type="service_account",
        auto_select=False,
        supports_model_listing=False,
        fallback_models=(),
        context_lengths={},
    )
)
