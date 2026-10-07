"""AWS Bedrock Chat Completions with per-request SigV4 (no SDK credential chain).

Reference checked 2026-10-07:
https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html
Only models supported by the OpenAI-compatible runtime endpoint are covered.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from clite.core.env import get_secret
from clite.core.errors import AuthError, ProviderError
from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider
from clite.providers.transports.types import HttpRequest


def _region(url: str) -> str:
    parts = urlsplit(url)
    match = re.fullmatch(r"bedrock-runtime\.([a-z0-9-]+)\.amazonaws\.com", parts.hostname or "")
    if (not match or parts.scheme != "https" or parts.port not in (None, 443)
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path.rstrip("/") != "/openai/v1"):
        raise AuthError("Use https://bedrock-runtime.REGION.amazonaws.com/openai/v1; "
                        "a different endpoint requires an explicit credential JSON.")
    return match[1]


def _credentials(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k]
                                             for k in ("access_key", "secret_key", "region")):
            raise ValueError
        if not re.fullmatch(r"[a-z0-9-]+", value["region"]):
            raise ValueError
        if "session_token" in value and not isinstance(value["session_token"], str):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise AuthError("Provide credential JSON with access_key, secret_key, region and optional session_token.") from None


class BedrockProfile(ProviderProfile):
    def is_configured(self) -> bool:
        return bool(get_secret("AWS_ACCESS_KEY_ID") and get_secret("AWS_SECRET_ACCESS_KEY"))

    def resolve_credential(self, base_url: str, explicit: str) -> str:
        if explicit:
            _credentials(explicit)
            return explicit
        region = _region(base_url)
        access, secret = get_secret("AWS_ACCESS_KEY_ID"), get_secret("AWS_SECRET_ACCESS_KEY")
        if not access or not secret:
            raise AuthError("Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env; "
                            "temporary credentials also need AWS_SESSION_TOKEN.")
        return json.dumps({"access_key": access, "secret_key": secret, "region": region,
                           "session_token": get_secret("AWS_SESSION_TOKEN") or ""})

    def authenticate_request(self, route: Any, request: HttpRequest,
                             http: Any, *, timeout: float, cancel: Any) -> HttpRequest:
        if route.api_mode != self.api_mode:
            raise ProviderError("This profile supports chat_completions only, not native Converse/InvokeModel.")
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            from botocore.credentials import Credentials
        except ImportError:
            raise ProviderError("Install c-lite[bedrock] to use SigV4 authentication.") from None
        values = _credentials(route.api_key)
        credentials = Credentials(values["access_key"], values["secret_key"], values.get("session_token") or None)
        signed = AWSRequest(method="POST", url=request.url, headers=request.headers,
                            data=json.dumps(request.body, ensure_ascii=False).encode("utf-8"))
        SigV4Auth(credentials, "bedrock", values["region"]).add_auth(signed)
        return HttpRequest(url=request.url, headers=dict(signed.headers.items()), body=request.body)


register_provider(BedrockProfile(
    name="bedrock", display_name="AWS Bedrock", description="AWS Bedrock Chat Completions (SigV4; c-lite[bedrock])",
    env_vars=("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"),
    base_url="", auth_type="signed", auto_select=False, supports_model_listing=False,
    fallback_models=(), context_lengths={},
))
