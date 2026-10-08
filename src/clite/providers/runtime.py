"""Runtime provider resolution: from "what the user asked for" to a route that can be called.

Every surface (CLI, RPC, gateway, cron, delegation, auxiliary tasks) resolves through
:func:`resolve_runtime_provider`. Nothing else decides which endpoint or key to use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from clite.core.config import get_path, load_config
from clite.core.errors import AuthError, ProviderError
from clite.providers.base import API_MODE_ANTHROPIC, ProviderProfile
from clite.providers.credentials import Credential, CredentialPool, get_credential_pool
from clite.providers.registry import get_provider, list_providers


@dataclass
class RuntimeRoute:
    provider: str
    model: str
    api_mode: str
    base_url: str
    api_key: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    profile: ProviderProfile | None = None
    source: str = ""  # where the decision came from, for `clite status` and debugging
    credential: Credential | None = None
    context_length: int | None = None  # explicit override only; lookups live in providers.models
    max_tokens: int | None = None
    credential_env_vars: tuple[str, ...] = ()
    credential_origin: tuple[str, str, int | None] | None = None
    api_mode_override: str = ""

    def __post_init__(self) -> None:
        if self.api_key and self.credential_origin is None:
            self.credential_origin = _origin(self.base_url)

    def validate_credential_origin(self, url: str) -> None:
        """Reject a credential-bearing request outside its resolved origin."""
        if self.api_key and (self.credential_origin is None or _origin(url) != self.credential_origin):
            raise AuthError(
                "The API key is bound to another endpoint origin. Resolve a new provider route.",
                provider=self.provider,
                code="credential_origin_mismatch",
            )

    def credential_pool(self) -> CredentialPool | None:
        """Only the pool selected when this route was resolved can supply replacement keys."""
        if not self.credential_env_vars or self.credential_origin is None:
            return None
        return get_credential_pool(
            self.provider, self.credential_env_vars, origin=str(self.credential_origin)
        )

    def describe(self) -> dict[str, Any]:
        """The route without secrets, safe to log or send to a UI."""
        return {
            "provider": self.provider,
            "model": self.model,
            "api_mode": self.api_mode,
            "base_url": self.base_url,
            "source": self.source,
            "has_api_key": bool(self.api_key),
        }

    def with_credential(self, credential: Credential) -> RuntimeRoute:
        """The same route using another key from the pool."""
        self.validate_credential_origin(self.base_url)
        pool = self.credential_pool()
        if pool is None or credential not in pool.candidates():
            raise AuthError(
                "The replacement API key does not belong to this endpoint's credential pool.",
                provider=self.provider,
                code="credential_pool_mismatch",
            )
        profile = self.profile
        headers = profile.get_headers(credential.value) if profile else dict(self.headers)
        return RuntimeRoute(
            **{**self.__dict__, "api_key": credential.value, "headers": headers, "credential": credential}
        )

    def with_model(self, model: str) -> RuntimeRoute:
        mode = self.api_mode_override or (
            self.profile.resolve_api_mode(model) if self.profile else self.api_mode
        )
        return RuntimeRoute(**{**self.__dict__, "model": model, "api_mode": mode})


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    return (
        scheme,
        (parsed.hostname or "").lower(),
        (parsed.port if parsed.port is not None else {"http": 80, "https": 443}.get(scheme)),
    )


def _auto_select(config: dict[str, Any]) -> ProviderProfile | None:
    for profile in list_providers(config):
        if profile.auto_select and profile.auth_type == "api_key" and profile.is_configured():
            return profile
    return None


def resolve_runtime_provider(
    provider: str | None = None,
    model: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    config: dict[str, Any] | None = None,
) -> RuntimeRoute:
    """Resolve the route. Explicit arguments beat config, config beats auto-detection.

    Raises :class:`AuthError` when a provider is chosen but has no credential, and
    :class:`ProviderError` when the provider or model cannot be determined.
    """
    cfg = config if config is not None else load_config()
    section = cfg.get("model") or {}
    configured_provider = str(section.get("provider") or "").strip()
    requested = (provider or configured_provider).strip()

    if requested and requested != "auto":
        profile = get_provider(requested, cfg)
        if profile is None:
            known = ", ".join(p.name for p in list_providers(cfg))
            raise ProviderError(f"Unknown provider {requested!r}. Known providers: {known}")
        source = "explicit" if provider else "config"
    else:
        profile = _auto_select(cfg)
        if profile is None:
            raise AuthError(
                "No model provider is configured. Run `clite setup`, or put an API key in .env "
                "(for example OPENROUTER_API_KEY) and choose a model with `clite model`.",
                code="no_provider",
            )
        source = "auto"

    # The config's base_url/api_mode/model belong to the provider the config names (or, with
    # no provider configured, the one auto-detection picks). When the caller asks for a
    # different provider, they must not leak onto it.
    if not provider:
        config_applies = True
    else:
        if configured_provider and configured_provider != "auto":
            owner = get_provider(configured_provider, cfg)
        else:
            owner = _auto_select(cfg)
        config_applies = owner is not None and owner.name == profile.name
    config_base_url = str(section.get("base_url") or "") if config_applies else ""
    native_base_url = profile.resolve_base_url()
    resolved_base_url = base_url or config_base_url or native_base_url
    if not resolved_base_url and profile.api_mode != "mock":
        raise ProviderError(
            f"Provider {profile.name!r} has no base URL. Set model.base_url in config.yaml "
            f"or {profile.base_url_env or 'a base_url'}."
        )
    resolved_base_url = (resolved_base_url or "").rstrip("/")

    credential: Credential | None = None
    credential_env_vars: tuple[str, ...] = ()
    key = api_key or ""
    if not key and profile.auth_type == "api_key":
        # A vendor key stays on its original scheme, host and port. A custom endpoint
        # needs an explicitly selected credential pool, including during recovery.
        same_origin = not (profile.base_url or native_base_url) or _origin(resolved_base_url) == _origin(
            profile.base_url or native_base_url
        )
        override_env = str(section.get("api_key_env") or "") if config_applies else ""
        if override_env:
            credential_env_vars = (override_env,)
            credential = get_credential_pool(
                profile.name, credential_env_vars, origin=str(_origin(resolved_base_url))
            ).current()
            key = credential.value if credential else ""
        elif same_origin:
            credential_env_vars = profile.env_vars
            credential = get_credential_pool(
                profile.name, credential_env_vars, origin=str(_origin(resolved_base_url))
            ).current()
            key = credential.value if credential else ""
        if not key:
            names = " or ".join(profile.env_vars) or "an API key"
            hint = (
                ""
                if same_origin
                else " (the provider's own key is not sent to a different host; set model.api_key_env)"
            )
            raise AuthError(
                f"Provider {profile.display_name!r} needs {names} in .env{hint}. Run `clite setup` to add it.",
                provider=profile.name,
                code="missing_key",
            )

    if profile.auth_type not in ("api_key", "none"):
        key = profile.resolve_credential(resolved_base_url, key)

    resolved_model = (
        model or (str(section.get("default") or "") if config_applies else "") or profile.default_model
    ).strip()
    if not resolved_model:
        raise ProviderError(
            f"No model selected for provider {profile.name!r}. Choose one with `clite model` "
            "or set model.default in config.yaml."
        )
    resolved_model = profile.model_aliases.get(resolved_model, resolved_model)

    api_mode_override = str(section.get("api_mode") or "") if config_applies else ""
    if resolved_base_url.endswith("/anthropic"):
        api_mode_override = API_MODE_ANTHROPIC  # the convention for Anthropic-compatible proxies
    api_mode = api_mode_override or profile.resolve_api_mode(resolved_model)

    return RuntimeRoute(
        provider=profile.name,
        model=resolved_model,
        api_mode=api_mode,
        api_mode_override=api_mode_override,
        base_url=resolved_base_url,
        api_key=key,
        headers=profile.get_headers(key),
        profile=profile,
        source=source if not credential else f"{source} ({credential.name})",
        credential=credential,
        credential_env_vars=credential_env_vars,
        context_length=get_path(cfg, "model.context_length") if config_applies else None,
        max_tokens=get_path(cfg, "model.max_tokens") if config_applies else None,
    )


def resolve_fallback_routes(config: dict[str, Any] | None = None) -> list[RuntimeRoute]:
    """Routes for ``fallback_providers``, skipping entries that cannot be resolved right now."""
    cfg = config if config is not None else load_config()
    routes: list[RuntimeRoute] = []
    for entry in cfg.get("fallback_providers") or []:
        if not isinstance(entry, dict) or not entry.get("provider"):
            continue
        try:
            # Resolved as an explicit request so the primary route's base_url never leaks in.
            routes.append(
                resolve_runtime_provider(
                    str(entry["provider"]), str(entry.get("model") or "") or None, config=cfg
                )
            )
        except (AuthError, ProviderError):
            continue
    return routes
