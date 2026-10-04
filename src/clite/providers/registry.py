"""Provider registry with lazy, layered discovery.

Layers, later ones winning on a name clash:

1. bundled plugins shipped in the package (``bundled/plugins/model-providers/<name>/``)
2. general plugins that call ``ctx.register_provider(profile)`` from their ``register(ctx)``
3. the active home's ``plugins/model-providers/<name>/`` (per profile)
4. named providers in ``config.yaml`` under ``providers:`` (per profile)

A provider plugin is a directory whose ``__init__.py`` calls ``register_provider(profile)``
at import time.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from clite.core.brand import PLUGIN_NAMESPACE
from clite.core.config import load_config
from clite.core.constants import bundled_dir, get_plugins_dir, home_key
from clite.providers.base import ProviderProfile

logger = logging.getLogger("clite.providers.registry")

_LOCK = threading.RLock()
_BASE: dict[str, ProviderProfile] = {}
_USER: dict[str, dict[str, ProviderProfile]] = {}  # home key -> providers from that home's plugins
_BASE_LOADED = False
_TARGET: ContextVar[dict[str, ProviderProfile] | None] = ContextVar("clite_provider_target", default=None)


def register_provider(profile: ProviderProfile) -> None:
    """Register ``profile``. The last registration of a name wins."""
    if not profile.name:
        raise ValueError("a provider profile needs a name")
    target = _TARGET.get()
    with _LOCK:
        (target if target is not None else _BASE)[profile.name] = profile


def _load_directory(directory: Path, target: dict[str, ProviderProfile], label: str) -> None:
    if not directory.is_dir():
        return
    for plugin_dir in sorted(p for p in directory.iterdir() if (p / "__init__.py").is_file()):
        slug = plugin_dir.name.replace("-", "_")
        module_name = f"{PLUGIN_NAMESPACE}.model_providers.{label}.{slug}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_dir / "__init__.py",
                                                      submodule_search_locations=[str(plugin_dir)])
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        token = _TARGET.set(target)
        try:
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:  # noqa: BLE001 - one broken provider must not hide the others
            sys.modules.pop(module_name, None)
            logger.warning("could not load provider plugin %s", plugin_dir, exc_info=True)
        finally:
            _TARGET.reset(token)


def _ensure_base() -> None:
    global _BASE_LOADED
    with _LOCK:
        if _BASE_LOADED:
            return
        _BASE_LOADED = True
        _load_directory(bundled_dir() / "plugins" / "model-providers", _BASE, "bundled")


def _user_layer() -> dict[str, ProviderProfile]:
    key = home_key()
    with _LOCK:
        layer = _USER.get(key)
        if layer is None:
            layer = {}
            _load_directory(get_plugins_dir() / "model-providers", layer, "user_" + str(abs(hash(key))))
            _USER[key] = layer
        return layer


def _config_layer(config: dict[str, Any] | None = None) -> dict[str, ProviderProfile]:
    """Named providers from ``config.yaml``: any OpenAI-compatible endpoint without a plugin."""
    section = (config if config is not None else load_config()).get("providers") or {}
    profiles: dict[str, ProviderProfile] = {}
    for name, spec in section.items():
        if not isinstance(spec, dict) or not spec.get("base_url"):
            continue
        models = spec.get("models") or []
        names = tuple(models) if isinstance(models, list) else tuple(models.keys())
        lengths = {
            model: int(meta["context_length"])
            for model, meta in (models.items() if isinstance(models, dict) else ())
            if isinstance(meta, dict) and meta.get("context_length")
        }
        key_env = str(spec.get("api_key_env") or "")
        profiles[str(name)] = ProviderProfile(
            name=str(name),
            display_name=str(spec.get("display_name") or name),
            description="Custom endpoint from config.yaml",
            api_mode=str(spec.get("api_mode") or "chat_completions"),
            base_url=str(spec["base_url"]).rstrip("/"),
            env_vars=(key_env,) if key_env else (),
            auth_type="api_key" if key_env else "none",
            fallback_models=names,
            default_model=str(spec.get("default_model") or (names[0] if names else "")),
            context_lengths=lengths,
            default_headers=dict(spec.get("headers") or {}),
            auto_select=False,
        )
    return profiles


def _merged(config: dict[str, Any] | None = None) -> dict[str, ProviderProfile]:
    _ensure_base()
    with _LOCK:
        merged = dict(_BASE)
    merged.update(_user_layer())
    merged.update(_config_layer(config))
    return merged


def list_providers(config: dict[str, Any] | None = None) -> list[ProviderProfile]:
    """Every known provider, in registration order (bundled first)."""
    return list(_merged(config).values())


def get_provider(name: str, config: dict[str, Any] | None = None) -> ProviderProfile | None:
    """A provider by name or alias; ``None`` when unknown."""
    wanted = (name or "").strip().lower()
    if not wanted:
        return None
    merged = _merged(config)
    if wanted in merged:
        return merged[wanted]
    for profile in merged.values():
        if wanted in (alias.lower() for alias in profile.aliases):
            return profile
    return None


def reset_providers() -> None:
    """Forget every layer (tests, and ``/reload`` after a plugin was installed)."""
    global _BASE_LOADED
    with _LOCK:
        _BASE.clear()
        _USER.clear()
        _BASE_LOADED = False
    for name in [name for name in sys.modules if name.startswith(f"{PLUGIN_NAMESPACE}.model_providers.")]:
        sys.modules.pop(name, None)


def reset_user_layers() -> None:
    with _LOCK:
        _USER.clear()
