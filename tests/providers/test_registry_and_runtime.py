"""Provider discovery and route resolution."""

from __future__ import annotations

import pytest

from clite.core.constants import home_scope
from clite.core.errors import AuthError, ProviderError
from clite.providers.base import ProviderProfile
from clite.providers.registry import get_provider, list_providers, register_provider
from clite.providers.runtime import resolve_fallback_routes, resolve_runtime_provider

PLUGIN = '''
from clite.providers.base import ProviderProfile
from clite.providers.registry import register_provider

register_provider(ProviderProfile(name="{name}", display_name="{display}", env_vars=("ACME_API_KEY",),
                                  base_url="https://api.acme.test/v1", default_model="acme-large"))
'''


def _install_provider(home, name="acme", display="Acme"):
    plugin = home / "plugins" / "model-providers" / name
    plugin.mkdir(parents=True)
    (plugin / "__init__.py").write_text(PLUGIN.format(name=name, display=display))


# ── registry ─────────────────────────────────────────────────────────────────────────────


def test_bundled_providers_are_discovered():
    names = {profile.name for profile in list_providers()}
    assert {"openrouter", "openai", "anthropic", "ollama", "custom", "mock"} <= names


def test_lookup_by_alias_is_case_insensitive():
    assert get_provider("Claude").name == "anthropic"
    assert get_provider("nope") is None
    assert get_provider("") is None


def test_user_plugin_adds_a_provider(clite_home):
    _install_provider(clite_home)
    assert get_provider("acme").default_model == "acme-large"


def test_user_plugin_overrides_a_bundled_provider_for_that_home_only(clite_home, tmp_path):
    _install_provider(clite_home, name="openai", display="My OpenAI")
    assert get_provider("openai").display_name == "My OpenAI"
    with home_scope(tmp_path / "other"):
        assert get_provider("openai").display_name == "OpenAI"


def test_a_broken_provider_plugin_does_not_hide_the_others(clite_home):
    broken = clite_home / "plugins" / "model-providers" / "broken"
    broken.mkdir(parents=True)
    (broken / "__init__.py").write_text("raise RuntimeError('boom')\n")
    _install_provider(clite_home)
    assert get_provider("acme") is not None


def test_config_defines_named_providers(clite_home):
    (clite_home / "config.yaml").write_text(
        "providers:\n"
        "  lab:\n"
        "    base_url: http://gpu-box:8000/v1/\n"
        "    api_key_env: LAB_API_KEY\n"
        "    models:\n"
        "      qwen-coder: {context_length: 65536}\n"
    )
    lab = get_provider("lab")
    assert lab.base_url == "http://gpu-box:8000/v1"
    assert lab.env_vars == ("LAB_API_KEY",)
    assert lab.default_model == "qwen-coder"
    assert lab.get_model_context_length("qwen-coder") == 65536


def test_last_registration_wins():
    list_providers()  # load the bundled layer first
    register_provider(ProviderProfile(name="openrouter", display_name="Replaced", base_url="https://x.test"))
    assert get_provider("openrouter").display_name == "Replaced"


def test_context_length_prefers_the_longest_matching_prefix():
    profile = ProviderProfile(name="p", context_lengths={"big-": 100, "big-mini": 50, "exact-model": 7})
    assert profile.get_model_context_length("big-mini-2") == 50
    assert profile.get_model_context_length("big-pro") == 100
    assert profile.get_model_context_length("exact-model") == 7
    assert profile.get_model_context_length("other") is None


# ── runtime resolution ───────────────────────────────────────────────────────────────────


def test_nothing_configured_explains_what_to_do():
    with pytest.raises(AuthError) as error:
        resolve_runtime_provider()
    assert "clite setup" in str(error.value)
    assert error.value.code == "no_provider"


def test_auto_picks_the_first_provider_with_a_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    route = resolve_runtime_provider(model="vendor/model-x")
    assert (route.provider, route.model, route.api_key) == ("openrouter", "vendor/model-x", "sk-or-test")
    assert route.headers["Authorization"] == "Bearer sk-or-test"
    assert route.source.startswith("auto")


def test_auto_never_picks_keyless_local_providers():
    # ollama and mock need no key, but picking them silently would surprise the user.
    with pytest.raises(AuthError):
        resolve_runtime_provider(model="x")


def test_config_names_the_provider_and_model(clite_home, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    (clite_home / "config.yaml").write_text("model:\n  provider: deepseek\n  default: deepseek-chat\n")
    route = resolve_runtime_provider()
    assert (route.provider, route.model, route.base_url) == ("deepseek", "deepseek-chat", "https://api.deepseek.com/v1")


def test_short_model_form_in_config(clite_home, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k" * 12)
    (clite_home / "config.yaml").write_text("model: vendor/short-form\n")
    assert resolve_runtime_provider().model == "vendor/short-form"


def test_explicit_arguments_beat_config(clite_home, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    (clite_home / "config.yaml").write_text("model:\n  provider: deepseek\n  default: deepseek-chat\n")
    route = resolve_runtime_provider("mock", "mock-2")
    assert (route.provider, route.model, route.api_mode) == ("mock", "mock-2", "mock")


def test_config_for_one_provider_does_not_leak_onto_another(clite_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: custom\n  default: local-model\n  base_url: http://localhost:8080/v1\n"
    )
    route = resolve_runtime_provider("openai", "gpt-x")
    assert route.base_url == "https://api.openai.com/v1"
    with pytest.raises(ProviderError):
        resolve_runtime_provider("openai")  # the config's model belongs to `custom`, not openai


def test_missing_key_names_the_variable(clite_home):
    (clite_home / "config.yaml").write_text("model:\n  provider: anthropic\n  default: claude-x\n")
    with pytest.raises(AuthError) as error:
        resolve_runtime_provider()
    assert "ANTHROPIC_API_KEY" in str(error.value)
    assert error.value.provider == "anthropic"


def test_anthropic_uses_its_own_auth_header(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    route = resolve_runtime_provider("anthropic", "claude-x")
    assert route.headers == {"x-api-key": "sk-ant-test"}
    assert route.api_mode == "anthropic_messages"


def test_a_provider_key_is_not_sent_to_another_host(clite_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: openai\n  default: m\n  base_url: https://proxy.example.com/v1\n"
    )
    with pytest.raises(AuthError) as error:
        resolve_runtime_provider()
    assert "different host" in str(error.value)

    monkeypatch.setenv("PROXY_KEY", "sk-proxy")
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: openai\n  default: m\n  base_url: https://proxy.example.com/v1\n  api_key_env: PROXY_KEY\n"
    )
    route = resolve_runtime_provider()
    assert (route.api_key, route.base_url) == ("sk-proxy", "https://proxy.example.com/v1")


def test_base_url_environment_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434/v1/")
    route = resolve_runtime_provider("ollama", "llama")
    assert route.base_url == "http://gpu-box:11434/v1"
    assert route.api_key == "" and "Authorization" not in route.headers


def test_custom_provider_needs_a_base_url():
    with pytest.raises(ProviderError) as error:
        resolve_runtime_provider("custom", "m", api_key="k")
    assert "base URL" in str(error.value)


def test_anthropic_compatible_proxy_is_detected_by_url(monkeypatch):
    route = resolve_runtime_provider("custom", "m", base_url="https://gateway.example.com/anthropic", api_key="k")
    assert route.api_mode == "anthropic_messages"


def test_unknown_provider_lists_the_known_ones():
    with pytest.raises(ProviderError) as error:
        resolve_runtime_provider("nonsense", "m")
    assert "openrouter" in str(error.value)


def test_describe_never_contains_the_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-value")
    described = resolve_runtime_provider(model="m").describe()
    assert described["has_api_key"] is True
    assert "sk-or-secret-value" not in str(described)


def test_fallback_routes_skip_unusable_entries(clite_home, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    (clite_home / "config.yaml").write_text(
        "fallback_providers:\n"
        "  - {provider: anthropic, model: claude-x}\n"  # no key: skipped
        "  - {provider: deepseek, model: deepseek-chat}\n"
        "  - {provider: mock}\n"
    )
    assert [(r.provider, r.model) for r in resolve_fallback_routes()] == [("deepseek", "deepseek-chat"), ("mock", "mock-1")]
