"""Plugin loading: discovery, opt-in gating, the registration ledger, isolation."""

from __future__ import annotations

import json

import pytest

from clite.core.config import load_config
from clite.core.constants import home_scope
from clite.plugins.hooks import invoke_hook
from clite.plugins.manager import (
    ensure_plugins_loaded,
    get_plugin_manager,
    install_plugin,
    remove_plugin,
    set_plugin_enabled,
)
from clite.plugins.manifest import ManifestError, parse_manifest
from clite.tools.dispatch import handle_function_call
from clite.tools.registry import registry

PLUGIN = '''
def register(ctx):
    ctx.register_tool(
        "{tool}", "{name}-tools", {{"description": "says hello", "parameters": {{"type": "object", "properties": {{}}}}}},
        lambda args: '{{"greeting": "hello from {name}", "setting": "%s"}}' % ctx.settings.get("flavour", "plain"),
    )
    ctx.register_hook("transform_tool_result", lambda result: None)
    ctx.register_command("{name}", lambda args, session=None: "ran {name} with " + args, description="demo")
    ctx.register_prompt_section("note", "Plugin {name} is active.")
'''


def _write_plugin(root, name, *, tool=None, body=None, manifest=""):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "plugin.yaml").write_text(f"name: {name}\nversion: 1.2.3\ndescription: test plugin\n{manifest}")
    (directory / "__init__.py").write_text(body or PLUGIN.format(name=name, tool=tool or f"{name}_hello"))
    return directory


def _enable(home, *names, extra=""):
    (home / "config.yaml").write_text("plugins:\n  enabled: [" + ", ".join(names) + "]\n" + extra)


@pytest.fixture
def plugins_dir(clite_home):
    return clite_home / "plugins"


def test_manifest_validation():
    assert parse_manifest({"name": "ok-plugin", "kind": "platform"}).kind == "platform"
    for bad in ({"name": "Bad Name"}, {"name": "ok", "kind": "mystery"}, {"name": "ok", "manifest_version": 99}, "text"):
        with pytest.raises(ManifestError):
            parse_manifest(bad)


def test_a_discovered_plugin_does_nothing_until_enabled(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "greeter")
    manager = ensure_plugins_loaded()
    info = manager.plugins["greeter"]
    assert (info.status, info.source, info.manifest.version) == ("not_enabled", "user", "1.2.3")
    assert registry.get("greeter_hello") is None

    _enable(clite_home, "greeter")
    manager.load_all()
    assert manager.plugins["greeter"].status == "loaded"
    assert json.loads(handle_function_call("greeter_hello", {}))["greeting"] == "hello from greeter"
    assert registry.get("greeter_hello").origin == "plugin:greeter"


def test_disabled_wins_over_enabled(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "greeter")
    _enable(clite_home, "greeter", extra="  disabled: [greeter]\n")
    assert ensure_plugins_loaded().plugins["greeter"].status == "disabled"
    assert registry.get("greeter_hello") is None


def test_everything_a_plugin_registered_is_removed_on_unload(plugins_dir, clite_home):
    from clite.plugins.hooks import get_hook_bus

    _write_plugin(plugins_dir, "greeter")
    _enable(clite_home, "greeter")
    manager = ensure_plugins_loaded()
    assert "greeter" in manager.commands and get_hook_bus().has("transform_tool_result")
    assert get_hook_bus().render_prompt_sections() == ["Plugin greeter is active."]

    assert manager.unload("greeter") is True
    assert registry.get("greeter_hello") is None and "greeter" not in manager.commands
    assert not get_hook_bus().has("transform_tool_result") and get_hook_bus().render_prompt_sections() == []


def test_turning_a_plugin_off_in_config_unloads_it(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "greeter")
    _enable(clite_home, "greeter")
    manager = ensure_plugins_loaded()
    set_plugin_enabled("greeter", False)
    assert load_config()["plugins"] == {**load_config()["plugins"], "enabled": [], "disabled": ["greeter"]}
    manager.load_all()
    assert manager.plugins["greeter"].status == "disabled" and registry.get("greeter_hello") is None
    set_plugin_enabled("greeter", True)
    manager.load_all()
    assert manager.plugins["greeter"].status == "loaded"


def test_a_broken_plugin_is_reported_and_leaves_nothing_behind(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "half", body=(
        "def register(ctx):\n"
        "    ctx.register_tool('half_tool', 'half', {'description': 'x'}, lambda args: '{}')\n"
        "    raise RuntimeError('failed halfway')\n"))
    _write_plugin(plugins_dir, "syntax", body="def register(ctx)\n")
    _write_plugin(plugins_dir, "noregister", body="x = 1\n")
    _write_plugin(plugins_dir, "greeter")
    _enable(clite_home, "half", "syntax", "noregister", "greeter")
    manager = ensure_plugins_loaded()
    assert manager.plugins["half"].status == "error" and "failed halfway" in manager.plugins["half"].error
    assert manager.plugins["syntax"].status == "error" and manager.plugins["noregister"].status == "error"
    assert registry.get("half_tool") is None  # the partial registration was rolled back
    assert manager.plugins["greeter"].status == "loaded"  # the others still load


def test_required_environment_is_checked_before_any_code_runs(plugins_dir, clite_home, monkeypatch):
    _write_plugin(plugins_dir, "needs-key", manifest="requires_env: [ACME_API_KEY]\n", body="raise SystemExit('must not run')\n")
    _enable(clite_home, "needs-key")
    manager = ensure_plugins_loaded()
    assert manager.plugins["needs-key"].status == "error" and "ACME_API_KEY" in manager.plugins["needs-key"].error


def test_a_plugin_cannot_replace_a_builtin_tool_without_consent(plugins_dir, clite_home):
    from clite.tools.registry import discover_builtin_tools

    discover_builtin_tools()
    _write_plugin(plugins_dir, "hijack", tool="read_file")
    _enable(clite_home, "hijack")
    manager = ensure_plugins_loaded()
    assert manager.plugins["hijack"].status == "error" and "already registered" in manager.plugins["hijack"].error
    assert registry.get("read_file").origin == "builtin"

    _enable(clite_home, "hijack", extra="  entries:\n    hijack: {allow_tool_override: true}\n")
    manager.load_all()
    assert registry.get("read_file").origin == "plugin:hijack"
    manager.unload("hijack")
    assert registry.get("read_file").origin == "builtin"  # unloading restores what was replaced


def test_plugin_settings_come_from_config(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "greeter")
    _enable(clite_home, "greeter", extra="  entries:\n    greeter:\n      settings: {flavour: spicy}\n")
    ensure_plugins_loaded()
    assert json.loads(handle_function_call("greeter_hello", {}))["setting"] == "spicy"


def test_plugins_can_import_their_own_modules(plugins_dir, clite_home):
    directory = _write_plugin(plugins_dir, "multi", body=(
        "from . import helper\n\n"
        "def register(ctx):\n"
        "    ctx.register_command('multi', lambda args, session=None: helper.VALUE)\n"))
    (directory / "helper.py").write_text("VALUE = 'from a sibling module'\n")
    _enable(clite_home, "multi")
    assert ensure_plugins_loaded().commands["multi"].handler("") == "from a sibling module"


def test_each_profile_has_its_own_plugins(plugins_dir, clite_home, tmp_path):
    _write_plugin(plugins_dir, "greeter")
    _enable(clite_home, "greeter")
    assert "greeter" in ensure_plugins_loaded().commands
    with home_scope(tmp_path / "other-profile"):
        other = ensure_plugins_loaded()
        assert "greeter" not in other.plugins and "greeter" not in other.commands
    assert get_plugin_manager() is not other


def test_install_copies_but_does_not_enable(clite_home, tmp_path, plugins_dir):
    source = _write_plugin(tmp_path / "downloads", "greeter")
    info = install_plugin(str(source))
    assert info.path == plugins_dir / "greeter" and (plugins_dir / "greeter" / "plugin.yaml").is_file()
    assert ensure_plugins_loaded().plugins["greeter"].status == "not_enabled"
    with pytest.raises(FileExistsError):
        install_plugin(str(source))
    install_plugin(str(source), force=True)
    assert remove_plugin("greeter") is True and not (plugins_dir / "greeter").exists()
    assert remove_plugin("greeter") is False
    with pytest.raises(ValueError):
        install_plugin("not-a-path-or-url")


def test_bundled_audit_log_plugin(clite_home):
    manager = ensure_plugins_loaded()
    assert manager.plugins["audit-log"].source == "bundled" and manager.plugins["audit-log"].status == "not_enabled"
    _enable(clite_home, "audit-log")
    manager.load_all()
    invoke_hook("post_tool_call", tool_name="terminal", args={"command": "echo hi"}, result='{"output": "hi"}',
                duration=0.012, session_id="s1", platform="cli", tool_call_id="c1")
    entries = [json.loads(line) for line in (clite_home / "logs" / "tool-audit.jsonl").read_text().splitlines()]
    assert entries[0]["tool"] == "terminal" and entries[0]["duration_ms"] == 12
    assert "terminal" in manager.commands["audit"].handler("5")
    assert "audit" in manager.cli_commands
