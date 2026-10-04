"""Runtime provider resolution: from "what the user asked for" to a route that can be called.

Every surface (CLI, RPC, gateway, cron, delegation, auxiliary tasks) resolves through
:func:`resolve_runtime_provider`. Nothing else decides which endpoint or key to use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from clite.core.config import get_path, load_config
from clite.core.env import get_secret
from clite.core.errors import AuthError, ProviderError
from clite.providers.base import API_MODE_ANTHROPIC, ProviderProfile
from clite.providers.credentials import Credential, get_credential_pool
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

    def describe(self) -> dict[str, Any]:
        """The route without secrets, safe to log or send to a UI."""
        return {
            "provider": self.provider, "model": self.model, "api_mode": self.api_mode,
            "base_url": self.base_url, "source": self.source, "has_api_key": bool(self.api_key),
        }

    def with_credential(self, credential: Credential) -> RuntimeRoute:
        """The same route using another key from the pool."""
        profile = self.profile
        headers = profile.get_headers(credential.value) if profile else dict(self.headers)
        return RuntimeRoute(**{**self.__dict__, "api_key": credential.value, "headers": headers, "credential": credential})

    def with_model(self, model: str) -> RuntimeRoute:
        return RuntimeRoute(**{**self.__dict__, "model": model})


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


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
    resolved_base_url = (
        base_url
        or config_base_url
        or (get_secret(profile.base_url_env) if profile.base_url_env else "")
        or profile.base_url
    )
    if not resolved_base_url and profile.api_mode != "mock":
        raise ProviderError(
            f"Provider {profile.name!r} has no base URL. Set model.base_url in config.yaml "
            f"or {profile.base_url_env or 'a base_url'}."
        )
    resolved_base_url = (resolved_base_url or "").rstrip("/")

    credential: Credential | None = None
    key = api_key or ""
    if not key and profile.auth_type == "api_key":
        # A key is only ever sent to the host it was issued for. If the user pointed this
        # provider at another host, the provider's key stays home.
        same_host = not profile.base_url or _host(resolved_base_url) == _host(profile.base_url)
        override_env = str(section.get("api_key_env") or "") if config_applies else ""
        if override_env:
            key = get_secret(override_env) or ""
            credential = Credential(override_env, key) if key else None
        elif same_host:
            credential = get_credential_pool(profile.name, profile.env_vars).current()
            key = credential.value if credential else ""
        if not key:
            names = " or ".join(profile.env_vars) or "an API key"
            hint = "" if same_host else " (the provider's own key is not sent to a different host; set model.api_key_env)"
            raise AuthError(
                f"Provider {profile.display_name!r} needs {names} in .env{hint}. Run `clite setup` to add it.",
                provider=profile.name, code="missing_key",
            )

    resolved_model = (model or (str(section.get("default") or "") if config_applies else "") or profile.default_model).strip()
    if not resolved_model:
        raise ProviderError(
            f"No model selected for provider {profile.name!r}. Choose one with `clite model` "
            "or set model.default in config.yaml."
        )
    resolved_model = profile.model_aliases.get(resolved_model, resolved_model)

    api_mode = (str(section.get("api_mode") or "") if config_applies else "") or profile.api_mode
    if resolved_base_url.endswith("/anthropic"):
        api_mode = API_MODE_ANTHROPIC  # the convention for Anthropic-compatible proxies

    return RuntimeRoute(
        provider=profile.name,
        model=resolved_model,
        api_mode=api_mode,
        base_url=resolved_base_url,
        api_key=key,
        headers=profile.get_headers(key),
        profile=profile,
        source=source if not credential else f"{source} ({credential.name})",
        credential=credential,
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
            routes.append(resolve_runtime_provider(str(entry["provider"]), str(entry.get("model") or "") or None,
                                                   config=cfg))
        except (AuthError, ProviderError):
            continue
    return routes
