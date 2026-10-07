"""``ImageProvider``: a pluggable backend for the ``image_generate`` tool.

The tool is offered only when a provider is configured (``check_fn``), so the model is never
told it can draw a picture when there is no backend to answer. A plugin registers a provider
factory with :func:`register_image_provider`; from a plugin that is
``ctx.register_image_provider(name, factory)``.

A provider returns raw image bytes plus their media type. Saving those bytes to a file, and
redacting the result, is the tool's job, not the provider's.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from clite.core.config import get_path, load_config


@dataclass
class GeneratedImage:
    """One picture from a provider: its bytes and media type. ``data`` is never a URL."""

    media_type: str
    data: bytes
    #: Provider-specific extras worth reporting to the model (a revised prompt, a seed). Not
    #: sent back verbatim; the tool copies only the keys it knows are safe.
    metadata: dict[str, str] = field(default_factory=dict)


class ImageProvider(ABC):
    """An image-generation backend. Implementations live in plugins (``kind: backend``)."""

    name: str = ""
    #: When True, the provider only activates if its API key is present in ``.env``.
    requires_api_key: bool = False
    #: The environment variable that holds the API key (for keyed providers).
    api_key_env: str = ""
    #: Sizes the backend accepts at all; used to validate the ``size`` argument before a call.
    supported_sizes: tuple[str, ...] = ()

    @abstractmethod
    def generate(self, prompt: str, *, size: str = "", count: int = 1) -> list[GeneratedImage]:
        """Return ``count`` images for ``prompt``. Raises on failure; the tool reports it.

        ``size`` is an empty string when the caller did not ask for one, letting the backend
        pick its own default. A provider that cannot honour a requested size raises rather
        than silently returning something else.
        """


# ── registry ───────────────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, Callable[[], ImageProvider]] = {}
_LOCK = threading.RLock()


def register_image_provider(name: str, factory: Callable[[], ImageProvider]) -> None:
    """Register a provider factory. The last registration of a name wins."""
    with _LOCK:
        _PROVIDERS[name] = factory


def unregister_image_provider(name: str) -> bool:
    with _LOCK:
        return _PROVIDERS.pop(name, None) is not None


def reset_image_providers() -> None:
    """Drop every registration. Called between tests by ``conftest._reset_process_state``."""
    with _LOCK:
        _PROVIDERS.clear()


def provider_names() -> list[str]:
    with _LOCK:
        return sorted(_PROVIDERS)


def has_image_provider() -> bool:
    """True when at least one provider is configured and (for keyed ones) its key is set."""
    return get_image_provider() is not None


def get_image_provider() -> ImageProvider | None:
    """The active provider, selected by ``image.provider``, or the first available one.

    A keyed provider whose API key is not in ``.env`` is skipped, so a machine without the key
    does not get the tool.
    """
    from clite.core.env import get_secret

    config = load_config()
    preferred = str(get_path(config, "image.provider", "") or "").strip()
    names = provider_names()
    ordered = [preferred] + [n for n in names if n != preferred] if preferred else names
    with _LOCK:
        factories = [(n, _PROVIDERS[n]) for n in ordered if n in _PROVIDERS]
    for _name, factory in factories:
        try:
            provider = factory()
        except Exception:  # noqa: BLE001 - a broken factory is skipped, not fatal
            continue
        if provider.requires_api_key and provider.api_key_env and not get_secret(provider.api_key_env):
            continue
        return provider
    return None
