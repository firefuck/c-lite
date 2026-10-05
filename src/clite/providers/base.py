"""``ProviderProfile``: everything about one inference provider, declared in one place.

A profile is declarative. It says where the endpoint is, how to authenticate, which wire
protocol to speak (``api_mode``) and which request quirks apply. It does not own the HTTP
client, retries or streaming; those live in the transport and the agent loop.

Adding a provider is one directory with a profile, never an ``if provider == ...`` branch in
core code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

API_MODE_CHAT_COMPLETIONS = "chat_completions"
API_MODE_ANTHROPIC = "anthropic_messages"
API_MODE_RESPONSES = "responses"
API_MODE_MOCK = "mock"

# Sentinel for ``fixed_temperature``: do not send a temperature at all.
OMIT_TEMPERATURE = object()


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
    auth_type: str = "api_key"  # api_key | none
    auth_header: str = "Authorization"  # header carrying the key
    auth_scheme: str = "Bearer"  # prefix before the key; empty for a bare key
    supports_model_listing: bool = True
    # Picked by `auto` resolution only when explicitly chosen (local or offline providers).
    auto_select: bool = True

    # ── model catalog ────────────────────────────────────────────────────────────────────
    # Shown when the live catalog cannot be fetched. Model ids rot: keep this short and
    # prefer the live list.
    fallback_models: tuple[str, ...] = ()
    model_aliases: dict[str, str] = field(default_factory=dict)
    default_model: str = ""
    default_aux_model: str = ""  # cheap model for side tasks; empty = use the main model
    context_lengths: dict[str, int] = field(default_factory=dict)  # exact id or prefix -> tokens

    # ── request quirks ───────────────────────────────────────────────────────────────────
    default_headers: dict[str, str] = field(default_factory=dict)
    fixed_temperature: Any = None  # None = caller's value; OMIT_TEMPERATURE = never send one
    default_max_tokens: int | None = None
    max_tokens_param: str = "max_tokens"  # some APIs want max_completion_tokens

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name

    # ── hooks: override in a subclass for a provider with real quirks ────────────────────

    def get_hostname(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    def get_headers(self, api_key: str) -> dict[str, str]:
        """Auth plus provider headers for one request."""
        headers = dict(self.default_headers)
        if api_key and self.auth_type == "api_key":
            headers[self.auth_header] = f"{self.auth_scheme} {api_key}".strip()
        return headers

    def prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Last-chance rewrite of the outgoing messages (already a copy). Default: unchanged."""
        return messages

    def build_extra_body(self, *, model: str, reasoning_effort: str = "", session_id: str = "") -> dict[str, Any]:
        """Extra top-level request fields (reasoning config, routing preferences)."""
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

    def get_model_context_length(self, model: str) -> int | None:
        if model in self.context_lengths:
            return self.context_lengths[model]
        matches = [prefix for prefix in self.context_lengths if model.startswith(prefix)]
        return self.context_lengths[max(matches, key=len)] if matches else None

    def resolve_aux_model(self) -> str:
        return self.default_aux_model

    def is_configured(self) -> bool:
        """True when the provider can be used without asking the user for anything."""
        if self.auth_type == "none":
            return True
        from clite.core.env import get_secret

        return any(get_secret(name) for name in self.env_vars)
