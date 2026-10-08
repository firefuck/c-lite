"""Windows path spellings must not bypass command policy on any host."""

from pathlib import PureWindowsPath
from types import SimpleNamespace

import pytest

from clite.tools import approval


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ~/*",
        "rm -rf ~/..",
        "cd ~; rm -rf .",
        "rm -rf *",
        r"rm -rf C:\Users\tester",
        r'rm -rf "C:\Users\tester"',
        r"rm -rf C:\Users/",
        r"rm -rf C:\Users\tester\*",
        r"cd C:\Users\tester; rm -rf .",
    ],
)
def test_windows_home_is_a_hardline_delete_target(monkeypatch, command):
    monkeypatch.setattr(approval, "Path", SimpleNamespace(home=lambda: PureWindowsPath("C:/Users/tester")))
    assert approval.detect_hardline(command, cwd="C:\\Users\\tester")
    decision = approval.check_command(
        command, approval.ToolContext(approval_mode="off"), cwd="C:\\Users\\tester"
    )
    assert not decision.approved and decision.choice == "hardline"


@pytest.mark.parametrize("command", [r"rm -rf C:\Users\tester\build", r"rm -rf C:\Users\tester-backup"])
def test_windows_home_children_and_similar_names_are_not_hardline_targets(monkeypatch, command):
    monkeypatch.setattr(approval, "Path", SimpleNamespace(home=lambda: PureWindowsPath("C:/Users/tester")))
    assert approval.detect_hardline(command) is None


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
