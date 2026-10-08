"""The Windows ACL probe must not inherit incompatible PowerShell 7 modules."""

import json
import subprocess
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("module_path_key", ["PSModulePath", "PSMODULEPATH"])
def test_acl_probe_isolates_module_search_and_stops_on_errors(
    monkeypatch, tmp_path, assert_private_file, module_path_key
):
    environment = {module_path_key: r"C:\Program Files\PowerShell\7\Modules", "SystemRoot": r"C:\Windows"}
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "protected": True,
                    "rules": [{"sid": "S-1-3-4", "rights": 2032127, "inherited": False, "type": 0}],
                }
            ),
        )

    # Replace only the fixture module's OS view, not pathlib/pytest's host platform.
    with monkeypatch.context() as patch:
        patch.setitem(assert_private_file.__globals__, "os", SimpleNamespace(name="nt", environ=environment))
        patch.setattr(subprocess, "run", run)
        assert_private_file(tmp_path / ".env")

    assert len(calls) == 1
    argv, options = calls[0]
    assert not any(key.lower() == "psmodulepath" for key in options["env"])
    assert options["env"]["SystemRoot"] == environment["SystemRoot"]
    assert options["env"]["CLITE_TEST_ACL_PATH"] == str(tmp_path / ".env")
    assert module_path_key in environment  # only the child environment is changed
    assert "$ErrorActionPreference = 'Stop'" in argv[-1]
    assert options["check"] is True
