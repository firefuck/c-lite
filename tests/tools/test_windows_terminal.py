"""Real cmd.exe and Git Bash execution; neither backend is optional on Windows CI."""

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from clite.tools.environments import local


@pytest.fixture(params=["cmd", "bash"])
def windows_shell(request, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("cmd.exe and Git for Windows require a Windows host")
    if request.param == "cmd":
        shell = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"]
    else:
        shell = local.find_shell()
        assert Path(shell[0]).name.lower() == "bash.exe", "Windows CI must install Git Bash"
    monkeypatch.setattr(local, "find_shell", lambda: shell)
    return request.param


def test_both_shells_track_cd_and_preserve_exit_status(windows_shell, tmp_path):
    child = tmp_path / "space ü"
    child.mkdir()
    env = local.LocalEnvironment(str(tmp_path))
    result = env.execute('cd "space ü"')
    assert result.exit_code == 0, result.output
    assert Path(env.cwd).resolve() == child.resolve()
    assert result.output == ""  # completion bookkeeping is not model output
    failed = env.execute("cmd /c exit 7" if windows_shell == "cmd" else "false")
    assert failed.exit_code == (7 if windows_shell == "cmd" else 1)
    result = env.execute("echo hello", cwd=str(tmp_path))
    assert result.output.strip() == "hello" and result.exit_code == 0
    assert Path(env.cwd).resolve() == child.resolve()


def test_both_shells_handle_stdin_and_output_without_a_newline(windows_shell, tmp_path):
    script = tmp_path / "io.py"
    script.write_text("import sys; sys.stdout.write(sys.stdin.readline().strip())", encoding="utf-8")
    env = local.LocalEnvironment(str(tmp_path))
    result = env.execute(f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"', stdin_data="hello\n")
    assert result.exit_code == 0 and result.output == "hello"


def test_both_shells_support_background_stdin_and_completion(windows_shell, tmp_path, monkeypatch):
    from clite.tools.builtin import process

    monkeypatch.setattr(process, "find_shell", local.find_shell)
    script = tmp_path / "background io.py"
    script.write_text("import sys; print('got:' + sys.stdin.readline().strip())", encoding="utf-8")
    managed = process.process_registry.spawn(
        f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"', cwd=str(tmp_path), task_id="win",
    )
    managed.process.stdin.write("ping\n")
    managed.process.stdin.flush()
    assert process.process_registry.wait(managed, 10)
    assert managed.exit_code == 0 and managed.output().strip() == "got:ping"


@pytest.mark.parametrize("interrupt_command", [False, True])
def test_both_shells_kill_the_child_tree(windows_shell, tmp_path, interrupt_command):
    script = tmp_path / "tree.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(60)\n", encoding="utf-8",
    )
    interrupt = threading.Event()
    child_pid = []

    def output(text):
        if text.strip().isdigit():
            child_pid.append(int(text.strip()))
            if interrupt_command:
                interrupt.set()

    env = local.LocalEnvironment(str(tmp_path))
    result = env.execute(f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"',
                         timeout=3, interrupt=interrupt, on_output=output)
    assert result.exit_code == (130 if interrupt_command else 124)
    assert child_pid, result.output
    # Query the actual descendant, not just the shell return code.
    check = subprocess.run(["tasklist", "/FI", f"PID eq {child_pid[0]}", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=10, check=True)
    assert f'"{child_pid[0]}"' not in check.stdout
