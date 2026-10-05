"""Shared fixtures.

Every test runs against a throwaway home. Nothing in the suite may read or write the real
``~/.clite``, and nothing may depend on credentials in the developer's shell.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
_HOST = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)


def _reset_process_state() -> None:
    """Drop every process-global cache so one test cannot leak state into the next."""
    from clite.core import config, env
    from clite.core import logging as clite_logging
    from clite.state import db

    config.reset_config_cache()
    clite_logging.reset_logging()
    db.close_all_session_dbs()
    env._LOADED.clear()

    # Later layers register their own reset hooks here as they are imported.
    for module_name, function_name in (
        ("clite.plugins.hooks", "reset_hook_buses"),
        ("clite.tools.registry", "reset_check_cache"),
        ("clite.tools.dispatch", "reset_definition_cache"),
        ("clite.tools.approval", "reset_approval_state"),
        ("clite.tools.builtin.process", "reset_process_registry"),
        ("clite.tools.environments", "cleanup_all_environments"),
        ("clite.tools.mcp.client", "shutdown_mcp_servers"),
        ("clite.providers.registry", "reset_providers"),
        ("clite.providers.credentials", "reset_credential_pools"),
        ("clite.plugins.manager", "reset_plugin_managers"),
        ("clite.skills.catalog", "reset_skill_cache"),
        ("clite.cron.jobs", "reset_job_stores"),
        ("clite.rpc.server", "reset_server_state"),
        ("clite.runtime.maintenance", "reset_maintenance_state"),
    ):
        module = sys.modules.get(module_name)
        reset = getattr(module, function_name, None) if module else None
        if reset is not None:
            reset()
    # Tools a test registered (origin "test") never outlive that test.
    tool_registry = sys.modules.get("clite.tools.registry")
    if tool_registry is not None:
        tool_registry.registry.deregister_origin("test")


@pytest.fixture(autouse=True)
def clite_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty home under ``tmp_path``; ``Path.home()`` is redirected too so the default
    root and every profile land in the same sandbox."""
    saved_environ = dict(os.environ)
    home = tmp_path / ".clite"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("CLITE_HOME", str(home))
    monkeypatch.setenv("TZ", "UTC")
    for name in list(os.environ):
        if name.endswith(_CREDENTIAL_SUFFIXES) or name.startswith("CLITE_") and name != "CLITE_HOME":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    _reset_process_state()
    yield home
    _reset_process_state()
    # Code under test writes to os.environ directly (load_env, save_secret); undo all of it.
    os.environ.clear()
    os.environ.update(saved_environ)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Honour ``@pytest.mark.platforms("linux", "macos")``: skip on any other host."""
    for item in items:
        markers = list(item.iter_markers(name="platforms"))
        if len(markers) > 1:
            raise pytest.UsageError(f"{item.nodeid}: use ONE platforms() marker with several specs")
        if not markers:
            continue
        specs = set(markers[0].args)
        if "posix" in specs:
            specs |= {"linux", "macos"}
        if _HOST not in specs:
            item.add_marker(pytest.mark.skip(reason=f"runs only on {sorted(markers[0].args)}"))
