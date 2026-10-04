"""The terminal UI as shipped: the bundle inside the Python package.

`clite tui` runs ``src/clite/tui_dist/clite-tui.mjs``, which is built from TypeScript in
``ui-tui/`` and ``apps/shared/``. These tests check that the committed bundle matches its
sources and that it runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from clite.cli.main import main
from clite.cli.repl import Repl
from clite.cli.subcommands import tui

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGED = REPO_ROOT / "src" / "clite" / "tui_dist"
# Keep in sync with SOURCE_DIRS in ui-tui/build.mjs.
BUNDLE_SOURCE_DIRS = ("apps/shared/src", "ui-tui/src")
MOCK = "model:\n  provider: mock\n  default: mock-1\n"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def source_hash() -> str:
    """The same hash ui-tui/build.mjs records: sorted relative paths and file contents."""
    files = sorted(
        (path.relative_to(REPO_ROOT).as_posix(), path)
        for directory in BUNDLE_SOURCE_DIRS
        for path in (REPO_ROOT / directory).rglob("*.ts")
    )
    digest = hashlib.sha256()
    for name, path in files:
        digest.update(name.encode() + b"\0")
        digest.update(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode() + b"\0")
    return digest.hexdigest()


def test_the_bundle_ships_inside_the_package():
    assert tui.find_tui_bundle() == PACKAGED / tui.BUNDLE_NAME
    assert (PACKAGED / "build-info.json").is_file()


def test_the_committed_bundle_was_built_from_the_current_sources():
    if not (REPO_ROOT / "ui-tui" / "src").is_dir():
        pytest.skip("not a source checkout")
    recorded = json.loads((PACKAGED / "build-info.json").read_text())["source_hash"]
    assert recorded == source_hash(), (
        "ui-tui/src or apps/shared/src changed after the TUI bundle was built. "
        "Run `npm run build` in ui-tui/ and commit src/clite/tui_dist/."
    )


@needs_node
def test_the_bundle_prints_its_help():
    result = subprocess.run(["node", str(PACKAGED / tui.BUNDLE_NAME), "--help"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "Usage: clite tui" in result.stdout


@needs_node
def test_clite_tui_runs_a_turn_with_the_packaged_bundle(clite_home, tmp_path):
    (clite_home / "config.yaml").write_text(MOCK)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", "")])),
           "NO_COLOR": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "clite", "tui", "--cwd", str(tmp_path)], input="hello bundle\n/quit\n",
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "You said: hello bundle" in result.stdout


# ── choosing the interface ───────────────────────────────────────────────────────────────


@pytest.fixture
def interface(clite_home, monkeypatch):
    """Record which interface `clite` starts, without starting either."""
    (clite_home / "config.yaml").write_text(MOCK)
    started: list[tuple[str, object]] = []
    monkeypatch.setattr(tui, "launch_tui", lambda arguments, fallback_options=None: started.append(("tui", arguments)) or 0)
    monkeypatch.setattr(Repl, "run", lambda self: started.append(("cli", self)) or 0)
    return started


def _terminal(monkeypatch, attached: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: attached, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: attached, raising=False)


def test_the_classic_cli_is_the_default(interface, monkeypatch):
    _terminal(monkeypatch, True)
    assert main([]) == 0
    assert [kind for kind, _ in interface] == ["cli"]


def test_display_interface_tui_applies_on_a_terminal_only(interface, clite_home, monkeypatch):
    (clite_home / "config.yaml").write_text(MOCK + "display:\n  interface: tui\n")
    _terminal(monkeypatch, False)
    assert main([]) == 0  # piped input: stay in the classic CLI
    _terminal(monkeypatch, True)
    assert main(["chat"]) == 0
    assert main(["--classic"]) == 0
    assert main(["-t", "file"]) == 0  # an option the TUI does not take
    assert [kind for kind, _ in interface] == ["cli", "tui", "cli", "cli"]


def test_the_tui_flag_forwards_the_chat_options(interface, monkeypatch):
    _terminal(monkeypatch, False)
    assert main(["--tui", "-m", "mock:mock-2", "--yolo"]) == 0
    assert interface == [("tui", ["--model", "mock-2", "--provider", "mock", "--yolo"])]


def test_without_node_the_tui_falls_back_to_the_classic_cli(clite_home, monkeypatch, capsys):
    (clite_home / "config.yaml").write_text(MOCK)
    seen = {}

    def fake_run(self):
        seen["yolo"] = self.session.agent.approval_mode
        return 0

    monkeypatch.setattr(Repl, "run", fake_run)
    monkeypatch.setattr(tui.shutil, "which", lambda name: None)
    assert main(["--tui", "--yolo"]) == 0
    assert "Starting the classic CLI instead" in capsys.readouterr().err
    assert seen["yolo"] == "off"  # the options given on the command line survive the fallback


def test_arguments_after_tui_reach_the_tui_untouched(clite_home, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(tui, "launch_tui", lambda arguments, fallback_options=None: seen.append(arguments) or 0)
    assert main(["tui", "--resume", "abc", "-m", "mock-2", "--help"]) == 0
    assert seen == [["--resume", "abc", "-m", "mock-2", "--help"]]
    with pytest.raises(SystemExit):  # every other command still rejects unknown options
        main(["sessions", "list", "--no-such-option"])
    assert "unrecognized arguments: --no-such-option" in capsys.readouterr().err
