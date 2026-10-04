"""Config contracts: defaults merge under the user file, and writes go through one seam."""

import pytest
import yaml

from clite.core import config
from clite.core.config_defaults import CONFIG_VERSION, DEFAULT_CONFIG
from clite.core.constants import get_config_path
from clite.core.errors import ConfigError


def test_missing_file_yields_defaults():
    loaded = config.load_config()
    assert loaded["compression"]["threshold"] == DEFAULT_CONFIG["compression"]["threshold"]
    assert config.load_user_config_raw() == {}


def test_user_values_override_defaults_and_keep_sibling_keys():
    get_config_path().write_text("compression:\n  threshold: 0.8\n")
    loaded = config.load_config()
    assert loaded["compression"]["threshold"] == 0.8
    assert loaded["compression"]["protect_last_n"] == DEFAULT_CONFIG["compression"]["protect_last_n"]


def test_short_model_form_is_lifted():
    get_config_path().write_text("model: vendor/some-model\n")
    assert config.load_config()["model"]["default"] == "vendor/some-model"
    assert "provider" in config.load_config()["model"]


def test_callers_cannot_poison_the_cache():
    first = config.load_config()
    first["agent"]["api_max_retries"] = 99
    assert config.load_config()["agent"]["api_max_retries"] == DEFAULT_CONFIG["agent"]["api_max_retries"]


def test_set_then_get_round_trips_and_keeps_other_keys():
    get_config_path().write_text("display:\n  skin: mono\n")
    config.config_set("terminal.timeout", 42)
    assert config.config_get("terminal.timeout") == 42
    assert config.config_get("display.skin") == "mono"
    raw = yaml.safe_load(get_config_path().read_text())
    assert raw["_config_version"] == DEFAULT_CONFIG["_config_version"]


def test_unset_removes_only_the_named_key():
    config.config_set("terminal.timeout", 42)
    config.config_set("terminal.cwd", "/work")
    assert config.config_unset("terminal.timeout") is True
    assert config.config_unset("terminal.timeout") is False
    assert config.load_user_config_raw()["terminal"] == {"cwd": "/work"}


def test_broken_file_is_never_overwritten():
    get_config_path().write_text("model: [unclosed\n")
    with pytest.raises(ConfigError):
        config.load_config()
    with pytest.raises(ConfigError):
        config.config_set("terminal.timeout", 1)
    assert get_config_path().read_text() == "model: [unclosed\n"


def test_environment_references_expand(monkeypatch):
    monkeypatch.setenv("MY_ENDPOINT", "http://localhost:1234/v1")
    get_config_path().write_text("model:\n  base_url: ${MY_ENDPOINT}\n")
    assert config.config_get("model.base_url") == "http://localhost:1234/v1"


def test_migrations_run_up_to_the_current_version(monkeypatch):
    monkeypatch.setattr(config, "CONFIG_VERSION", CONFIG_VERSION + 1)

    def rename(raw):
        raw["renamed"] = raw.pop("legacy")

    monkeypatch.setitem(config.MIGRATIONS, CONFIG_VERSION, rename)
    get_config_path().write_text(f"legacy: 7\n_config_version: {CONFIG_VERSION}\n")
    assert config.load_config()["renamed"] == 7
    assert config.migrate_config_file() is True
    raw = config.load_user_config_raw()
    assert raw["_config_version"] == config.CONFIG_VERSION and "legacy" not in raw
    assert config.migrate_config_file() is False


@pytest.mark.parametrize(("text", "expected"), [("true", True), ("3", 3), ("[a, b]", ["a", "b"]), ("plain", "plain")])
def test_cli_values_are_typed(text, expected):
    assert config.parse_cli_value(text) == expected
