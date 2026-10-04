"""terminal and process tools against a real shell."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from clite.core.env import load_env
from clite.plugins.hooks import get_hook_bus
from clite.tools.builtin.process import process_tool
from clite.tools.builtin.terminal import clip_lines, terminal_tool
from clite.tools.context import ToolContext
from clite.tools.environments import get_environment

pytestmark = pytest.mark.platforms("posix")


def _run(command, ctx=None, **args):
    return json.loads(terminal_tool({"command": command, **args}, ctx or ToolContext(task_id="t1")))


def test_output_and_exit_code():
    assert _run("echo hello") == {"output": "hello\n", "exit_code": 0}
    assert _run("echo oops >&2; exit 3") == {"output": "oops\n", "exit_code": 3}


def test_command_is_required():
    assert "error" in json.loads(terminal_tool({}, ToolContext()))


def test_cd_persists_between_calls(tmp_path):
    (tmp_path / "sub").mkdir()
    ctx = ToolContext(task_id="t1", cwd=str(tmp_path))
    _run("cd sub", ctx)
    assert _run("pwd", ctx)["output"].strip().endswith("/sub")
    assert get_environment("t1").cwd.endswith("/sub")


def test_each_task_has_its_own_working_directory(tmp_path):
    (tmp_path / "a").mkdir()
    one, two = ToolContext(task_id="one", cwd=str(tmp_path)), ToolContext(task_id="two", cwd=str(tmp_path))
    _run("cd a", one)
    assert _run("pwd", two)["output"].strip() == str(tmp_path.resolve())


def test_workdir_overrides_without_moving_the_session(tmp_path):
    (tmp_path / "other").mkdir()
    ctx = ToolContext(task_id="t1", cwd=str(tmp_path))
    assert _run("pwd", ctx, workdir="other")["output"].strip().endswith("/other")
    assert _run("pwd", ctx)["output"].strip() == str(tmp_path.resolve())


def test_timeout_kills_the_command():
    started = time.monotonic()
    result = _run("sleep 30", timeout=1)
    assert time.monotonic() - started < 10
    assert result["exit_code"] == 124 and "timed out" in result["error"]


def test_interrupt_stops_a_running_command():
    interrupt = threading.Event()
    threading.Timer(0.3, interrupt.set).start()
    started = time.monotonic()
    result = _run("sleep 30", ToolContext(task_id="t1", interrupt=interrupt))
    assert time.monotonic() - started < 10
    assert result["error"] == "interrupted"


def test_secrets_from_dotenv_do_not_reach_the_command(clite_home):
    (clite_home / ".env").write_text("OPENROUTER_API_KEY=sk-or-very-secret-value-123456\nPUBLIC_SETTING=visible-value\n")
    load_env()
    assert _run("echo [$OPENROUTER_API_KEY]")["output"].strip() == "[]"

    assert _run("echo [${#PUBLIC_SETTING}]")["output"].strip() == "[0]"
    (clite_home / "config.yaml").write_text("terminal:\n  env_passthrough: [PUBLIC_SETTING]\n")
    # Passed through on request: the command can use it, the transcript still never shows it.
    assert _run("echo [${#PUBLIC_SETTING}]")["output"].strip() == "[13]"
    assert _run("echo [$PUBLIC_SETTING]")["output"].strip() == "[[REDACTED]]"


def test_key_shaped_output_is_redacted():
    assert "[REDACTED]" in _run("echo token=sk-abcdefghijklmnopqrstuvwxyz123456")["output"]


def test_dangerous_command_needs_approval(tmp_path):
    target = tmp_path / "keep"
    target.mkdir()
    result = _run(f"rm -rf {target}", ToolContext(task_id="t1"))
    assert result["status"] == "blocked"
    assert target.exists()

    approving = ToolContext(task_id="t1", callbacks=SimpleNamespace(approve=lambda **kw: "once"))
    assert _run(f"rm -rf {target}", approving)["exit_code"] == 0
    assert not target.exists()


def test_transform_terminal_output_hook():
    get_hook_bus().register("transform_terminal_output", lambda output: output.upper())
    assert _run("echo quiet")["output"] == "QUIET\n"


def test_long_output_keeps_head_and_tail():
    clipped = clip_lines("\n".join(str(n) for n in range(100)), 30)
    lines = clipped.splitlines()
    assert lines[0] == "0" and lines[-1] == "99"
    assert "lines omitted" in clipped and len(lines) == 31


def test_background_process_lifecycle():
    ctx = ToolContext(task_id="t1")
    started = _run("echo ready; sleep 30", ctx, background=True)
    process_id = started["process_id"]
    assert started["status"] == "running"

    listed = json.loads(process_tool({"action": "list"}, ctx))["processes"]
    assert [p["process_id"] for p in listed] == [process_id]

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        polled = json.loads(process_tool({"action": "poll", "process_id": process_id}, ctx))
        if "ready" in polled["output"]:
            break
        time.sleep(0.05)
    assert "ready" in polled["output"] and polled["status"] == "running"

    killed = json.loads(process_tool({"action": "kill", "process_id": process_id}, ctx))
    assert killed["status"] == "exited"


def test_background_process_wait_and_stdin():
    ctx = ToolContext(task_id="t1")
    process_id = _run("read line; echo got:$line", ctx, background=True)["process_id"]
    assert json.loads(process_tool({"action": "write", "process_id": process_id, "data": "ping\n"}, ctx))["written"]
    waited = json.loads(process_tool({"action": "wait", "process_id": process_id, "timeout": 5}, ctx))
    assert waited["finished"] is True and waited["exit_code"] == 0
    assert "got:ping" in json.loads(process_tool({"action": "log", "process_id": process_id}, ctx))["output"]


def test_unknown_process_id():
    assert "error" in json.loads(process_tool({"action": "poll", "process_id": "proc_missing"}, ToolContext()))
