"""``WebSearchProvider``: a pluggable backend for the ``web_search`` tool.

The tool is offered only when a provider is configured (``check_fn``), so the model is never
told it can search the web when there is no backend to answer. A plugin registers a provider
factory with :func:`register_web_search_provider`; from a plugin that is
``ctx.register_web_search_provider(name, factory)``.

Results are title, URL, and snippet. The snippet is untrusted text from the web: it enters
the conversation as a tool result, never in the system prompt.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

from clite.core.config import get_path, load_config


class WebSearchProvider(ABC):
    """A search backend. Implementations live in plugins (``kind: backend``)."""

    name: str = ""
    #: When True, the provider only activates if its API key is present in ``.env``.
    requires_api_key: bool = False
    #: The environment variable that holds the API key (for keyed providers).
    api_key_env: str = ""

    @abstractmethod
    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        """Return a list of ``{title, url, snippet}`` dicts. An empty list means no hits.

        Snippets are untrusted text from the web and must not be sanitised or stripped: the
        model needs to see exactly what the backend returned. The tool handler passes them
        through verbatim as a tool result.
        """


# ── registry ───────────────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, Callable[[], WebSearchProvider]] = {}
_LOCK = threading.RLock()


def register_web_search_provider(name: str, factory: Callable[[], WebSearchProvider]) -> None:
    """Register a provider factory. The last registration of a name wins."""
    with _LOCK:
        _PROVIDERS[name] = factory


def unregister_web_search_provider(name: str) -> bool:
    with _LOCK:
        return _PROVIDERS.pop(name, None) is not None


def reset_web_search_providers() -> None:
    """Drop every registration. Called between tests by ``conftest._reset_process_state``."""
    with _LOCK:
        _PROVIDERS.clear()


def provider_names() -> list[str]:
    with _LOCK:
        return sorted(_PROVIDERS)


def has_web_search_provider() -> bool:
    """True when at least one provider is configured and (for keyed ones) its key is set."""
    return get_web_search_provider() is not None


def get_web_search_provider() -> WebSearchProvider | None:
    """The active provider, selected by ``web.search.provider``, or the first available one.

    A keyed provider whose API key is not in ``.env`` is skipped, so a machine without the key
    does not get the tool.
    """
    from clite.core.env import get_secret

    config = load_config()
    preferred = str(get_path(config, "web.search.provider", "") or "").strip()
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


def _search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Run the active provider and return its results. Raises if no provider is configured."""
    provider = get_web_search_provider()
    if provider is None:
        raise RuntimeError(
            "no web search provider is configured; enable a web-search plugin "
            "(e.g. web-search-ddg or web-search-tavily)"
        )
    return provider.search(query, max_results=max_results)
