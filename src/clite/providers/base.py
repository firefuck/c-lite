"""``ProviderProfile``: everything about one inference provider, declared in one place.

A profile is declarative. It says where the endpoint is, how to authenticate, which wire
protocol to speak (``api_mode``) and which request quirks apply. It does not own the HTTP
client, retries or streaming; those live in the transport and the agent loop.

Adding a provider is one directory with a profile, never an ``if provider == ...`` branch in
core code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from clite.providers.pricing import ModelPricing

if TYPE_CHECKING:
    from clite.providers.runtime import RuntimeRoute
    from clite.providers.transports.types import HttpRequest

API_MODE_CHAT_COMPLETIONS = "chat_completions"
API_MODE_ANTHROPIC = "anthropic_messages"
API_MODE_RESPONSES = "responses"
API_MODE_MOCK = "mock"

# Sentinel for ``fixed_temperature``: do not send a temperature at all.
OMIT_TEMPERATURE = object()


# Posts a form to a URL and returns the decoded JSON body (``oauth._http_post``).
FormPost = Callable[..., dict[str, Any]]


@dataclass
class ProviderProfile:
    # ── identity ─────────────────────────────────────────────────────────────────────────
    name: str
    api_mode: str = API_MODE_CHAT_COMPLETIONS
    aliases: tuple[str, ...] = ()
    display_name: str = ""
    description: str = ""
    signup_url: str = ""

    # ── auth and endpoints ───────────────────────────────────────────────────────────────
    env_vars: tuple[str, ...] = ()  # API key variables, highest priority first
    base_url: str = ""
    base_url_env: str = ""  # variable that overrides base_url (self-hosted, proxies)
    models_url: str = ""  # defaults to {base_url}/models
    auth_type: str = "api_key"  # api_key | none | oauth
    auth_header: str = "Authorization"  # header carrying the key
    auth_scheme: str = "Bearer"  # prefix before the key; empty for a bare key
    supports_model_listing: bool = True
    # Picked by `auto` resolution only when explicitly chosen (local or offline providers).
    auto_select: bool = True

    # ── oauth configuration ──────────────────────────────────────────────────────────────
    oauth_flow: str = "pkce"  # pkce | device_code
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_authorize_url: str = ""
    oauth_token_url: str = ""
    oauth_device_code_url: str = ""
    oauth_scopes: tuple[str, ...] = ()
    oauth_redirect_path: str = "/callback"
    oauth_callback_port: int = 0
    oauth_audience: str = ""

    # ── model catalog ────────────────────────────────────────────────────────────────────
    # Shown when the live catalog cannot be fetched. Model ids rot: keep this short and
    # prefer the live list.
    fallback_models: tuple[str, ...] = ()
    model_aliases: dict[str, str] = field(default_factory=dict)
    default_model: str = ""
    default_aux_model: str = ""  # cheap model for side tasks; empty = use the main model
    context_lengths: dict[str, int] = field(default_factory=dict)  # exact id or prefix -> tokens
    model_pricing: dict[str, ModelPricing] = field(default_factory=dict)  # exact id or prefix -> ModelPricing
    # Model ids or id prefixes that accept image content. Empty = the whole profile accepts
    # images (the common case); a profile whose non-vision models share an id prefix lists it
    # in ``no_vision_prefixes`` instead.
    vision_models: tuple[str, ...] = ()
    no_vision_prefixes: tuple[str, ...] = ()

    # ── request quirks ───────────────────────────────────────────────────────────────────
    default_headers: dict[str, str] = field(default_factory=dict)
    fixed_temperature: Any = None  # None = caller's value; OMIT_TEMPERATURE = never send one
    default_max_tokens: int | None = None
    max_tokens_param: str = "max_tokens"  # some APIs want max_completion_tokens

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name

    # ── hooks: override in a subclass for a provider with real quirks ────────────────────

    def resolve_base_url(self) -> str:
        """The configured endpoint before explicit route overrides."""
        from clite.core.env import get_secret

        return (get_secret(self.base_url_env) if self.base_url_env else "") or self.base_url

    def prepare_request(self, route: RuntimeRoute, request: HttpRequest) -> HttpRequest:
        """Pure final wire shaping; authentication happens only after origin validation."""
        return request

    def resolve_credential(self, base_url: str, explicit: str) -> str:
        """Snapshot non-API-key credentials without network access."""
        return explicit

    def authenticate_request(
        self, route: RuntimeRoute, request: HttpRequest, http: Any, *, timeout: float, cancel: Any
    ) -> HttpRequest:
        """Authenticate the final, origin-validated request immediately before sending."""
        return request

    def resolve_api_mode(self, model: str) -> str:
        """Select the wire protocol for a model unless the route explicitly overrides it."""
        return self.api_mode

    def get_hostname(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    def get_headers(self, api_key: str) -> dict[str, str]:
        """Auth plus provider headers for one request."""
        headers = dict(self.default_headers)
        if api_key and self.auth_type in ("api_key", "oauth"):
            headers[self.auth_header] = f"{self.auth_scheme} {api_key}".strip()
        return headers

    def prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Last-chance rewrite of the outgoing messages (already a copy). Default: unchanged."""
        return messages

    def build_extra_body(
        self, *, model: str, reasoning_effort: str = "", session_id: str = "", show_reasoning: bool = False
    ) -> dict[str, Any]:
        """Extra top-level request fields (reasoning config, routing preferences).

        ``show_reasoning`` is true when the user will see reasoning text; a provider that
        hides it by default asks for it here."""
        return {}

    def wants_cache_markers(self, model: str) -> bool:
        """True when this route honours Anthropic-style ``cache_control`` breakpoints."""
        return False

    def resolve_temperature(self, model: str, requested: float | None) -> float | None:
        """The sampling temperature to send for ``model``, or ``None`` to send none."""
        if self.fixed_temperature is OMIT_TEMPERATURE:
            return None
        return self.fixed_temperature if self.fixed_temperature is not None else requested

    def replay_is_prefix_bound(self, model: str) -> bool:
        """True when replayed ``provider_data`` (signed reasoning) is valid only while every
        message before it is unchanged. The agent then drops it whenever it rewrites the
        conversation's prefix on purpose (compression, a model switch)."""
        return False

    def get_max_tokens(self, model: str) -> int | None:
        return self.default_max_tokens

    def supports_vision(self, model: str) -> bool:
        """Whether ``model`` accepts image content parts.

        Declared by the profile, never guessed from the model id in core code. A listed
        ``no_vision_prefixes`` match means no; otherwise a non-empty ``vision_models`` is an
        allow-list, and an empty one means the profile's models all accept images. A wrong
        "yes" is caught by the provider's own error and reported to the user; the cost of a
        wrong "no" is a picture the model never sees, so unknown leans towards yes.
        """
        if any(model.startswith(prefix) for prefix in self.no_vision_prefixes):
            return False
        if self.vision_models:
            return any(model == mid or model.startswith(mid) for mid in self.vision_models)
        return True

    def get_model_context_length(self, model: str) -> int | None:
        if model in self.context_lengths:
            return self.context_lengths[model]
        matches = [prefix for prefix in self.context_lengths if model.startswith(prefix)]
        return self.context_lengths[max(matches, key=len)] if matches else None

    def get_model_pricing(self, model: str) -> ModelPricing | None:
        if model in self.model_pricing:
            return self.model_pricing[model]
        matches = [prefix for prefix in self.model_pricing if model.startswith(prefix)]
        return self.model_pricing[max(matches, key=len)] if matches else None

    def resolve_aux_model(self) -> str:
        return self.default_aux_model

    def supports_oauth(self) -> bool:
        """True when this provider can authenticate via OAuth."""
        return self.auth_type == "oauth" or bool(self.oauth_authorize_url or self.oauth_device_code_url)

    def is_configured(self) -> bool:
        """True when the provider can be used without asking the user for anything."""
        if self.auth_type == "none":
            return True
        from clite.core.env import get_secret

        if any(get_secret(name) for name in self.env_vars):
            return True
        if self.supports_oauth():
            from clite.providers.oauth import has_valid_token

            return has_valid_token(self.name)
        return False

    def build_oauth_authorize_url(self, *, redirect_uri: str, code_challenge: str, state: str) -> str:
        """Construct the authorization URL for PKCE."""
        from urllib.parse import urlencode

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.oauth_client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        if self.oauth_scopes:
            params["scope"] = " ".join(self.oauth_scopes)
        if self.oauth_audience:
            params["audience"] = self.oauth_audience
        return f"{self.oauth_authorize_url}?{urlencode(params)}"

    def exchange_oauth_code(
        self, *, code: str, code_verifier: str, redirect_uri: str, http_post: FormPost
    ) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "client_id": self.oauth_client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        if self.oauth_client_secret:
            data["client_secret"] = self.oauth_client_secret
        return http_post(self.oauth_token_url, form_data=data)

    def refresh_oauth_token(self, *, refresh_token: str, http_post: FormPost) -> dict[str, Any]:
        """Exchange a refresh token for a new access token."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self.oauth_client_id,
            "refresh_token": refresh_token,
        }
        if self.oauth_client_secret:
            data["client_secret"] = self.oauth_client_secret
        return http_post(self.oauth_token_url, form_data=data)

    def request_device_code(self, *, http_post: FormPost) -> dict[str, Any]:
        """Request device and user codes for device authorization flow."""
        data: dict[str, str] = {
            "client_id": self.oauth_client_id,
        }
        if self.oauth_scopes:
            data["scope"] = " ".join(self.oauth_scopes)
        return http_post(self.oauth_device_code_url, form_data=data)

    def poll_device_token(self, *, device_code: str, http_post: FormPost) -> dict[str, Any]:
        """Poll the token endpoint with a device code."""
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self.oauth_client_id,
            "device_code": device_code,
        }
        return http_post(self.oauth_token_url, form_data=data)
