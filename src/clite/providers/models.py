"""Model catalog: which models a provider offers, and how large their context windows are.

The live ``/models`` endpoint is the source of truth. Hardcoded ids rot, so the bundled
profiles keep ``fallback_models`` short and this module caches the live list on disk.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from clite.core.config import get_path, load_config
from clite.core.constants import ensure_dir, get_cache_dir
from clite.core.io import atomic_write_json, read_json
from clite.providers.base import ProviderProfile
from clite.providers.http import HttpClient, ProviderHTTPError
from clite.providers.registry import get_provider
from clite.providers.runtime import RuntimeRoute

logger = logging.getLogger("clite.providers.models")

CACHE_TTL_SECONDS = 6 * 3600
# Used when nothing knows the window. Deliberately conservative: guessing too large makes
# compression fire too late and the request fail; guessing too small only compresses early.
DEFAULT_CONTEXT_LENGTH = 128_000
MIN_CONTEXT_LENGTH = 16_000
_CONTEXT_KEYS = ("context_length", "context_window", "max_context_length", "max_input_tokens", "input_token_limit")


@dataclass
class ModelInfo:
    id: str
    context_length: int | None = None
    name: str = ""


def _cache_path(provider: str):
    return get_cache_dir() / "models" / f"{provider}.json"


def _parse_catalog(payload: dict[str, Any]) -> list[ModelInfo]:
    entries = payload.get("data") or payload.get("models") or []
    models: list[ModelInfo] = []
    for entry in entries:
        if isinstance(entry, str):
            models.append(ModelInfo(entry))
            continue
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id") or entry.get("name") or "").removeprefix("models/")
        if not model_id:
            continue
        length = next((int(entry[key]) for key in _CONTEXT_KEYS if isinstance(entry.get(key), (int, float))), None)
        models.append(ModelInfo(model_id, length, str(entry.get("display_name") or entry.get("name") or "")))
    return models


def fetch_models(profile: ProviderProfile, *, api_key: str = "", base_url: str = "", timeout: float = 10.0,
                 http: HttpClient | None = None) -> list[ModelInfo] | None:
    """The provider's live catalog, or ``None`` when it cannot be fetched."""
    if not profile.supports_model_listing or profile.api_mode == "mock":
        return None
    url = profile.models_url or ((base_url or profile.base_url).rstrip("/") + "/models")
    if profile.api_mode == "anthropic_messages" and not profile.models_url:
        base = (base_url or profile.base_url).rstrip("/")
        url = base + "/models" if base.endswith("/v1") else base + "/v1/models"
    headers = profile.get_headers(api_key)
    if profile.api_mode == "anthropic_messages":
        headers.setdefault("anthropic-version", "2023-06-01")
    try:
        payload = (http or HttpClient()).get_json(url, headers, timeout=timeout)
    except (ProviderHTTPError, OSError, ValueError) as exc:
        logger.debug("model listing for %s failed: %s", profile.name, exc)
        return None
    return _parse_catalog(payload)


def _cached(provider: str, *, max_age: float | None = CACHE_TTL_SECONDS) -> list[ModelInfo] | None:
    data = read_json(_cache_path(provider), None)
    if not isinstance(data, dict):
        return None
    if max_age is not None and time.time() - float(data.get("fetched_at") or 0) > max_age:
        return None
    return [ModelInfo(**entry) for entry in data.get("models") or []]


def list_models(provider: str, *, route: RuntimeRoute | None = None, refresh: bool = False,
                http: HttpClient | None = None) -> list[ModelInfo]:
    """Models for ``provider``: fresh cache, else live fetch, else stale cache, else fallbacks."""
    profile = get_provider(provider)
    if profile is None:
        return []
    if not refresh:
        cached = _cached(profile.name)
        if cached is not None:
            return cached
    api_key, base_url = (route.api_key, route.base_url) if route and route.provider == profile.name else ("", "")
    if not api_key and profile.auth_type == "api_key":
        from clite.providers.credentials import get_credential_pool

        credential = get_credential_pool(profile.name, profile.env_vars).current()
        api_key = credential.value if credential else ""
    live = fetch_models(profile, api_key=api_key, base_url=base_url, http=http)
    if live:
        ensure_dir(_cache_path(profile.name).parent)
        atomic_write_json(_cache_path(profile.name), {
            "fetched_at": time.time(), "models": [model.__dict__ for model in live],
        })
        return live
    stale = _cached(profile.name, max_age=None)
    if stale:
        return stale
    return [ModelInfo(model, profile.get_model_context_length(model)) for model in profile.fallback_models]


def get_context_length(route: RuntimeRoute, config: dict[str, Any] | None = None) -> int:
    """The context window for ``route``, in tokens.

    Order: the user's explicit override, the provider profile, the cached live catalog, then
    a conservative default. An explicit override always wins: the user knows their endpoint.
    """
    cfg = config if config is not None else load_config()
    explicit = route.context_length or get_path(cfg, "model.context_length")
    if isinstance(explicit, int) and explicit > 0 and (route.context_length or _config_owns(route, cfg)):
        return max(explicit, MIN_CONTEXT_LENGTH)
    if route.profile is not None:
        declared = route.profile.get_model_context_length(route.model)
        if declared:
            return declared
    for info in _cached(route.provider, max_age=None) or []:
        if info.id == route.model and info.context_length:
            return info.context_length
    return DEFAULT_CONTEXT_LENGTH


def _config_owns(route: RuntimeRoute, config: dict[str, Any]) -> bool:
    configured = str(get_path(config, "model.provider", "") or "")
    return not configured or configured == route.provider
