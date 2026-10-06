"""Windows path spellings must not bypass command policy on any host."""

from pathlib import PureWindowsPath
from types import SimpleNamespace

import pytest

from clite.tools import approval


@pytest.mark.parametrize("command", ["rm -rf ~/*", "rm -rf ~/..", "cd ~; rm -rf .", "rm -rf *"])
def test_windows_home_is_a_hardline_delete_target(monkeypatch, command):
    monkeypatch.setattr(approval, "Path", SimpleNamespace(home=lambda: PureWindowsPath("C:/Users/tester")))
    assert approval.detect_hardline(command, cwd="C:\\Users\\tester")


@pytest.mark.parametrize("tail", [r"\.env", r"\profiles\work\.env", r"\gateway\pairing.json"])
def test_backslash_paths_to_agent_settings_need_approval(clite_home, tail):
    path = str(clite_home).replace("/", "\\") + tail
    assert approval.detect_self_access(f'type "{path}"')


def test_windows_environment_home_spelling_needs_approval():
    assert approval.detect_self_access(r'type "%CLITE_HOME%\.env"')


def test_windows_delete_requires_approval_but_directory_listing_does_not():
    assert approval.detect_dangerous_command('rmdir /s /q "junk"')
    assert approval.detect_dangerous_command('del /f /q "junk.txt"')
    assert not approval.detect_dangerous_command('dir "junk"')
