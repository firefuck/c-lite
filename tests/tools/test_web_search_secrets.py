"""Web-search provider plugins register their API key as a credential."""

from __future__ import annotations

import importlib.util

from clite.core.constants import bundled_dir
from clite.core.env import SECRET_REGISTRY, secret_names

_PLUGIN_PATH = bundled_dir() / "plugins" / "web-search-tavily" / "__init__.py"


def _load_tavily_plugin():
    """Load the bundled Tavily plugin module from its file path (how the plugin manager does
    it), so its module-level ``register_secret`` call runs."""
    spec = importlib.util.spec_from_file_location(
        "clite_test_tavily_plugin", _PLUGIN_PATH,
        submodule_search_locations=[str(_PLUGIN_PATH.parent)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_keyed_provider_registers_its_api_key_as_a_secret(clite_home):
    """Importing the Tavily provider plugin registers its key in the secret registry,
    so it is stripped from commands the agent runs and redacted from what the model reads."""
    _load_tavily_plugin()
    assert "TAVILY_API_KEY" in SECRET_REGISTRY
    spec = SECRET_REGISTRY["TAVILY_API_KEY"]
    assert spec.category == "tool"
    assert "Tavily" in spec.description or "search" in spec.description.lower()
    # The key name is included in the set that gets stripped from child environments.
    assert "TAVILY_API_KEY" in secret_names()
