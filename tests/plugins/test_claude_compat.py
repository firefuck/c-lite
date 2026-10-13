import importlib

from clite.plugins.manager import get_plugin_manager


def test_claude_compat_plugin_is_bundled():
    manager = get_plugin_manager()
    manager.discover()
    assert "claude-compat" in manager.plugins
    meta = manager.plugins["claude-compat"]
    assert meta.source == "bundled"
    assert meta.manifest.kind == "standalone"


def test_claude_compat_injects_prompt_when_file_exists(tmp_path):
    claude_file = tmp_path / "CLAUDE.md"
    claude_file.write_text("Use concise code and run pytest.", encoding="utf-8")

    mod = importlib.import_module("clite.bundled.plugins.claude-compat")

    hooks = {}

    class DummyCtx:
        settings = {}

        def register_hook(self, name, fn):
            hooks[name] = fn

    mod.register(DummyCtx())
    assert "system_prompt" in hooks

    transformed = hooks["system_prompt"]("Base prompt", cwd=str(tmp_path))
    assert "Base prompt" in transformed
    assert "Use concise code and run pytest." in transformed
    assert "via claude-compat plugin" in transformed


def test_claude_compat_noop_when_no_file(tmp_path):
    mod = importlib.import_module("clite.bundled.plugins.claude-compat")
    hooks = {}

    class DummyCtx:
        settings = {}

        def register_hook(self, name, fn):
            hooks[name] = fn

    mod.register(DummyCtx())
    transformed = hooks["system_prompt"]("Base prompt", cwd=str(tmp_path))
    assert transformed == "Base prompt"
