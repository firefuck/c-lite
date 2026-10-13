"""The terminal UI as shipped: the bundle inside the Python package.

`clite tui` runs ``src/clite/tui_dist/clite-tui.mjs``, which is built from TypeScript in
``apps/tui/`` and ``packages/shared/``. These tests check that the committed bundle matches its
sources and that it runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from clite.cli.main import main
from clite.cli.repl import Repl
from clite.cli.subcommands import tui

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGED = REPO_ROOT / "src" / "clite" / "tui_dist"
# Keep in sync with SOURCE_DIRS in apps/tui/build.mjs.
BUNDLE_SOURCE_DIRS = ("packages/shared/src", "apps/tui/src")
MOCK = "model:\n  provider: mock\n  default: mock-1\n"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def source_hash() -> str:
    """The same hash apps/tui/build.mjs records: sorted relative paths and file contents."""
    files = sorted(
        (path.relative_to(REPO_ROOT).as_posix(), path)
        for directory in BUNDLE_SOURCE_DIRS
        for path in (REPO_ROOT / directory).rglob("*")
        if path.suffix in (".ts", ".tsx")
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
    if not (REPO_ROOT / "apps" / "tui" / "src").is_dir():
        pytest.skip("not a source checkout")
    recorded = json.loads((PACKAGED / "build-info.json").read_text())["source_hash"]
    assert recorded == source_hash(), (
        "apps/tui/src or packages/shared/src changed after the TUI bundle was built. "
        "Run `npm run build` in apps/tui/ and commit src/clite/tui_dist/."
    )


def test_the_bundle_is_self_contained_with_no_external_npm_imports():
    """Importing the bundle must not pull external packages from node_modules at runtime."""
    bundle_code = (PACKAGED / tui.BUNDLE_NAME).read_text(encoding="utf-8")
    # Scan all top-level static import specifiers (e.g. from 'xyz' or from "xyz")
    imports = re.findall(r"""(?:^|\n)\s*import\s+.*?from\s*["']([^"']+)["']""", bundle_code)
    for specifier in imports:
        # Allowed runtime imports: Node built-ins (node:*) or relative imports
        assert specifier.startswith("node:") or specifier.startswith("./") or specifier.startswith("../"), (
            f"Bundle has unbundled external npm dependency: {specifier}"
        )


@needs_node
def test_the_bundle_size_and_help_startup_time_stay_within_budget():
    bundle_path = PACKAGED / tui.BUNDLE_NAME
    # Size budget: must remain under 3MB (React+Ink bundle is currently ~1.4MB)
    size = bundle_path.stat().st_size
    assert size < 3_000_000, f"Bundle size {size} exceeds 3MB budget"

    t0 = time.monotonic()
    result = subprocess.run(["node", str(bundle_path), "--help"], capture_output=True, text=True, timeout=10)
    elapsed = time.monotonic() - t0
    assert result.returncode == 0
    assert elapsed < 5.0, f"--help took {elapsed:.2f}s, exceeding 5.0s budget"


@needs_node
def test_the_bundle_prints_its_help():
    result = subprocess.run(
        ["node", str(PACKAGED / tui.BUNDLE_NAME), "--help"], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0 and "Usage: clite tui" in result.stdout


@needs_node
def test_clite_tui_runs_a_turn_with_the_packaged_bundle(clite_home, tmp_path):
    (clite_home / "config.yaml").write_text(MOCK)
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", "")])
        ),
        "NO_COLOR": "1",
    }
    result = subprocess.run(
        [sys.executable, "-m", "clite", "tui", "--cwd", str(tmp_path)],
        input="hello bundle\n/quit\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "You said: hello bundle" in result.stdout


@needs_node
def test_clite_tui_stays_open_and_shows_the_created_session_model_in_a_real_pty(clite_home, tmp_path):
    """A real terminal must remain interactive after Ink's first frame."""
    if os.name != "posix":
        pytest.skip("PTY test requires POSIX")

    import fcntl
    import pty
    import struct
    import termios

    (clite_home / "config.yaml").write_text(MOCK)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))

    def make_controlling_terminal() -> None:
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", "")])
        ),
        "TERM": "xterm-256color",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "clite", "tui", "--cwd", str(tmp_path)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        preexec_fn=make_controlling_terminal,
    )
    os.close(slave)
    output = ""
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and process.poll() is None and "mock-1" not in output:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    output += os.read(master, 65536).decode("utf-8", errors="replace")
                except OSError:
                    break

        assert process.poll() is None, f"TUI exited before accepting input:\n{output}"
        assert "mock-1" in output
        # Wait through the trailing Ink render; a closed PTY becomes readable before this timeout.
        select.select([master], [], [], 0.5)
        assert process.poll() is None, f"TUI exited after its initial Ink frame:\n{output}"
    finally:
        if process.poll() is None:
            process.terminate()
            assert process.wait(timeout=15) == -signal.SIGTERM
        os.close(master)


# ── choosing the interface ───────────────────────────────────────────────────────────────


@pytest.fixture
def interface(clite_home, monkeypatch):
    """Record which interface `clite` starts, without starting either."""
    (clite_home / "config.yaml").write_text(MOCK)
    started: list[tuple[str, object]] = []
    monkeypatch.setattr(
        tui, "launch_tui", lambda arguments, fallback_options=None: started.append(("tui", arguments)) or 0
    )
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
    monkeypatch.setattr(
        tui, "launch_tui", lambda arguments, fallback_options=None: seen.append(arguments) or 0
    )
    assert main(["tui", "--resume", "abc", "-m", "mock-2", "--help"]) == 0
    assert seen == [["--resume", "abc", "-m", "mock-2", "--help"]]
    with pytest.raises(SystemExit):  # every other command still rejects unknown options
        main(["sessions", "list", "--no-such-option"])
    assert "unrecognized arguments: --no-such-option" in capsys.readouterr().err
