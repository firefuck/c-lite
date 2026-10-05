"""Model switching: one pipeline for ``/model`` in the CLI, the TUI, the desktop app and the
gateway. Each surface only renders the result.

Accepted input:

``<model>``                 keep the provider, change the model
``<provider>:<model>``      change both
``<provider>:``             change the provider, use its default model
``<alias>``                 a provider's ``model_aliases`` entry
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clite.core.config import atomic_config_update, load_config
from clite.core.errors import CliteError
from clite.providers.registry import get_provider
from clite.providers.runtime import RuntimeRoute, resolve_runtime_provider


@dataclass
class ModelSwitchResult:
    success: bool
    route: RuntimeRoute | None = None
    message: str = ""
    persisted: bool = False


def parse_model_input(text: str, config: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    """``(provider, model)``; either may be ``None`` meaning "keep the current one".

    A ``provider:`` prefix is only recognised when it names a known provider, because model
    ids legitimately contain colons (``qwen2.5:14b``, ``vendor/model:free``).
    """
    raw = text.strip()
    if not raw:
        return None, None
    head, separator, tail = raw.partition(":")
    if separator and get_provider(head, config) is not None:
        return get_provider(head, config).name, tail.strip() or None  # type: ignore[union-attr]
    if get_provider(raw, config) is not None and "/" not in raw:
        return get_provider(raw, config).name, None  # type: ignore[union-attr]
    return None, raw


def switch_model(
    text: str,
    *,
    current: RuntimeRoute | None = None,
    provider: str | None = None,
    persist: bool = False,
    config: dict[str, Any] | None = None,
) -> ModelSwitchResult:
    """Resolve a new route. With ``persist`` the choice is saved as the default."""
    cfg = config if config is not None else load_config()
    parsed_provider, model = parse_model_input(text, cfg)
    target_provider = provider or parsed_provider or (current.provider if current else None)
    if model is None and target_provider and current and target_provider == current.provider and not parsed_provider:
        return ModelSwitchResult(False, current, "Give a model name, or provider:model.")
    try:
        route = resolve_runtime_provider(target_provider, model, config=cfg)
    except CliteError as exc:
        return ModelSwitchResult(False, current, str(exc))

    persisted = False
    if persist:
        def mutate(document: dict[str, Any]) -> None:
            section = document.get("model")
            if not isinstance(section, dict):
                section = document["model"] = {"default": section} if isinstance(section, str) else {}
            previous_provider = section.get("provider")
            section["default"] = route.model
            section["provider"] = route.provider
            if previous_provider != route.provider:
                # These belonged to the previous provider's endpoint.
                for stale in ("base_url", "api_mode", "api_key_env", "context_length", "max_tokens"):
                    section.pop(stale, None)

        atomic_config_update(mutate)
        persisted = True
    scope = "saved as default" if persisted else "this session only"
    return ModelSwitchResult(True, route, f"Model: {route.model} via {route.provider} ({scope})", persisted)
