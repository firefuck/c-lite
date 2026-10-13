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
    from clite.core.redact import reset_redact_state

    reset_redact_state()

    # Later layers register their own reset hooks here as they are imported.
    for module_name, function_name in (
        ("clite.plugins.hooks", "reset_hook_buses"),
        ("clite.tools.registry", "reset_check_cache"),
        ("clite.tools.dispatch", "reset_definition_cache"),
        ("clite.tools.web_search", "reset_web_search_providers"),
        ("clite.tools.image_gen", "reset_image_providers"),
        ("clite.tools.speech", "reset_speech_registries"),
        ("clite.tools.checkpoints", "reset_turn_tracking"),
        ("clite.tools.approval", "reset_approval_state"),
        ("clite.tools.self_access", "reset_own_command_cache"),
        ("clite.tools.builtin.process", "reset_process_registry"),
        ("clite.tools.environments", "cleanup_all_environments"),
        ("clite.tools.mcp.client", "shutdown_mcp_servers"),
        ("clite.providers.registry", "reset_providers"),
        ("clite.providers.credentials", "reset_credential_pools"),
        ("clite.providers.oauth", "reset_oauth_state"),
        ("clite.plugins.manager", "reset_plugin_managers"),
        ("clite.plugins.pages", "reset_plugin_origin"),
        ("clite.skills.catalog", "reset_skill_cache"),
        ("clite.cron.jobs", "reset_job_stores"),
        ("clite.gateway.runner", "reset_active_runners"),
        ("clite.rpc.server", "reset_server_state"),
        ("clite.runtime.maintenance", "reset_maintenance_state"),
        ("clite.agent.review", "reset_review_state"),
        ("clite.agent.context.engine", "reset_context_engines"),
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
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    home = local / "clite" if sys.platform == "win32" else tmp_path / ".clite"
    home.mkdir(parents=True)
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


@pytest.fixture
def assert_private_file():
    """Check the native security model, not Windows' synthetic POSIX mode bits."""

    def check(path):
        if os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600
            return
        import json
        import subprocess

        script = (
            "$ErrorActionPreference = 'Stop'; "
            "$a = Get-Acl -LiteralPath $env:CLITE_TEST_ACL_PATH; "
            "$rules = @($a.Access | ForEach-Object { "
            "@{sid=$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value; "
            "rights=[int]$_.FileSystemRights; inherited=$_.IsInherited; type=[int]$_.AccessControlType} }); "
            "@{protected=$a.AreAccessRulesProtected; rules=$rules} | ConvertTo-Json -Depth 4 -Compress"
        )
        # CI starts Python under pwsh 7; its module path breaks powershell.exe 5.1 autoloading.
        child_env = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}
        child_env["CLITE_TEST_ACL_PATH"] = str(path)
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        acl = json.loads(result.stdout)
        assert acl["protected"] is True
        assert acl["rules"] == [{"sid": "S-1-3-4", "rights": 2032127, "inherited": False, "type": 0}]

    return check


def _docker_available() -> bool:
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False).returncode == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Honour ``@pytest.mark.platforms("linux", "macos")``, and keep ``network`` tests opt-in.

    A ``network`` test runs only when the marker is selected (``-m network``), so neither CI nor
    a plain ``pytest tests`` ever reaches a real service. A ``docker`` test is skipped unless a
    working Docker daemon answers, so the suite stays green on a machine without Docker.
    """
    wants_network = "network" in (config.option.markexpr or "")
    docker_ready = None
    for item in items:
        if not wants_network and item.get_closest_marker("network") is not None:
            item.add_marker(pytest.mark.skip(reason="needs the network; run with -m network"))
        if item.get_closest_marker("docker") is not None:
            if docker_ready is None:
                docker_ready = _docker_available()
            if not docker_ready:
                item.add_marker(pytest.mark.skip(reason="needs a working Docker daemon"))
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
