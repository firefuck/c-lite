"""``execute_code``: a short Python program run through the session's environment.

The tool is a *command like any other*: it goes through the approval gate, the credentials
are stripped from the interpreter's environment, and the output is redacted. Running it
through ``BaseEnvironment`` means it inherits whatever sandbox the active backend provides.
The names below are the specification: each one states a behaviour that must fail if the
behaviour is removed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from types import SimpleNamespace

import pytest

from clite.core.env import load_env
from clite.tools.builtin.code import MAX_CODE_CHARS, execute_code_tool
from clite.tools.context import ToolContext
from clite.tools.environments import get_environment

pytestmark = pytest.mark.platforms("posix")


def _run(code, ctx=None, **args):
    return json.loads(execute_code_tool({"code": code, **args}, ctx or ToolContext(task_id="code")))


# ── what the model asked for ────────────────────────────────────────────────────────────


def test_stdout_stderr_and_exit_code_come_back_separately():
    result = _run("import sys\nprint('to stdout')\nprint('to stderr', file=sys.stderr)\nsys.exit(0)")
    assert result["stdout"] == "to stdout\n"
    assert result["stderr"] == "to stderr\n"
    assert result["exit_code"] == 0


def test_a_failing_program_reports_its_traceback_and_exit_code():
    result = _run("print('before')\nraise ValueError('boom')")
    assert result["exit_code"] == 1
    assert result["stdout"] == "before\n"
    assert "ValueError: boom" in result["stderr"]
    assert "Traceback" in result["stderr"]


def test_the_program_runs_as_the_main_module(tmp_path):
    result = _run("print(__name__)")
    assert result["stdout"] == "__main__\n"


def test_code_is_required_and_bounded():
    assert "error" in json.loads(execute_code_tool({}, ToolContext()))
    assert "error" in json.loads(execute_code_tool({"code": "   "}, ToolContext()))
    result = json.loads(execute_code_tool({"code": "x" * (MAX_CODE_CHARS + 1)}, ToolContext()))
    assert "error" in result and "too long" in result["error"]


def test_the_program_runs_in_the_session_working_directory(tmp_path):
    ctx = ToolContext(task_id="cwd", cwd=str(tmp_path))
    assert _run("import os; print(os.getcwd())", ctx)["stdout"].strip() == str(tmp_path)


def test_a_later_call_sees_what_an_earlier_one_wrote(tmp_path):
    ctx = ToolContext(task_id="state", cwd=str(tmp_path))
    assert _run("open('made.txt', 'w').write('kept\\n')", ctx)["exit_code"] == 0
    assert _run("print(open('made.txt').read(), end='')", ctx)["stdout"] == "kept\n"


def test_output_is_bounded_and_says_so():
    result = _run("print('x' * 200000)")
    assert len(result["stdout"]) < 200_000
    assert "truncated" in result["stdout"]


def test_ordinary_computation_needs_no_approval():
    result = _run("print(sum(range(10)))")
    assert result["exit_code"] == 0 and result["stdout"] == "45\n"


# ── the timeout kills the program and everything it started ─────────────────────────────


def test_a_program_that_overruns_its_timeout_is_stopped(tmp_path):
    ctx = ToolContext(task_id="timeout", cwd=str(tmp_path))
    started = time.monotonic()
    result = _run("import time\nprint('started', flush=True)\ntime.sleep(60)", ctx, timeout=1)
    assert time.monotonic() - started < 20
    assert result["exit_code"] == 124
    assert "timed out" in result["error"].lower()
    assert "started" in result["stdout"]


def test_the_timeout_kills_the_child_processes_the_program_started(tmp_path):
    """A timeout that leaves a background child running is not a timeout."""
    pid_file = tmp_path / "child.pid"
    ctx = ToolContext(task_id="children", cwd=str(tmp_path))
    code = (
        "import subprocess, time, pathlib\n"
        "child = subprocess.Popen(['sleep', '120'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(120)\n"
    )
    result = _run(code, ctx, timeout=2)
    assert result["exit_code"] == 124

    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"child process {child_pid} survived the timeout")


def test_an_interrupt_stops_the_program(tmp_path):
    import threading

    interrupt = threading.Event()
    threading.Timer(0.3, interrupt.set).start()
    ctx = ToolContext(task_id="interrupt", cwd=str(tmp_path), interrupt=interrupt)
    result = _run("import time\ntime.sleep(60)", ctx)
    assert result["error"] == "interrupted"


# ── code is a command: the approval gate reads the text ─────────────────────────────────


def test_code_containing_a_dangerous_pattern_asks_for_approval(tmp_path):
    target = tmp_path / "keep"
    target.mkdir()
    ctx = ToolContext(task_id="gate", cwd=str(tmp_path))
    code = f"import os; os.system('rm -rf {target}')"
    result = _run(code, ctx)
    assert result["status"] == "blocked"
    assert target.exists()


def test_a_destructive_call_written_in_python_is_flagged_like_the_command_it_runs(tmp_path):
    """``shutil.rmtree`` is ``rm -rf`` spelled in Python; the gate reads the code as a command."""
    target = tmp_path / "keep"
    target.mkdir()
    ctx = ToolContext(task_id="gate-python", cwd=str(tmp_path))
    result = _run(f"import shutil; shutil.rmtree({str(target)!r})", ctx)
    assert result["status"] == "blocked"
    assert target.exists()


def test_an_approved_dangerous_program_runs(tmp_path):
    target = tmp_path / "gone"
    target.mkdir()
    ctx = ToolContext(
        task_id="gate-approve",
        cwd=str(tmp_path),
        callbacks=SimpleNamespace(approve=lambda **kwargs: "once"),
    )
    result = _run(f"import os; os.system('rm -rf {target}')", ctx)
    assert result["exit_code"] == 0
    assert not target.exists()


def test_a_hardline_program_is_refused_in_every_mode(tmp_path):
    for mode in ("off", "manual"):
        result = _run("import os; os.system('rm -rf /')", ToolContext(task_id="hard", approval_mode=mode))
        assert result["status"] == "blocked"
        assert "no setting allows it" in result["error"].lower()
    # The same text reaching the interpreter another way is refused too.
    assert json.loads(execute_code_tool({"code": "open('/dev/sda', 'wb')"}, ToolContext(task_id="hard2")))


def test_a_missing_approver_means_deny_not_run(tmp_path):
    target = tmp_path / "kept"
    target.mkdir()
    result = _run(
        f"import shutil; shutil.rmtree({str(target)!r})", ToolContext(task_id="ask", platform="cron")
    )
    assert result["status"] == "blocked"
    assert target.exists()


# ── credentials and redaction ───────────────────────────────────────────────────────────


def test_credential_variables_are_not_visible_from_inside_the_code(clite_home):
    key = "sk-" + "Q1w2E3r4T5y6U7i8O9p0A1s2"
    (clite_home / ".env").write_text(f"OPENROUTER_API_KEY={key}\nPUBLIC_SETTING=visible-value\n")
    load_env()
    result = _run("import os\nprint(repr(os.environ.get('OPENROUTER_API_KEY')))")
    assert result["stdout"] == "None\n"
    # Everything from .env is stripped, not only the names the tool knows about.
    assert _run("import os; print(repr(os.environ.get('PUBLIC_SETTING')))")["stdout"] == "None\n"


def test_provider_keys_exported_in_the_shell_are_not_visible_either(monkeypatch):
    from clite.providers.registry import list_providers

    list_providers()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "Exportedd1nMy2Shell3Profile4")
    assert _run("import os; print(repr(os.environ.get('OPENAI_API_KEY')))")["stdout"] == "None\n"


def test_key_shaped_output_is_redacted():
    key = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    result = _run(f"print('token={key}')")
    assert "[REDACTED]" in result["stdout"]
    assert key not in result["stdout"]


def test_a_secret_the_code_prints_anyway_is_redacted_from_the_transcript(clite_home):
    key = "sk-" + "Z9y8X7w6V5u4T3s2R1q0P9o8"
    (clite_home / ".env").write_text(f"OPENROUTER_API_KEY={key}\n")
    load_env()
    result = _run(f"print({key!r})")
    assert key not in result["stdout"]
    assert "[REDACTED]" in result["stdout"]


# ── the session environment is the sandbox ──────────────────────────────────────────────


def test_code_runs_through_the_session_environment(tmp_path, monkeypatch):
    """The point of the tool: it goes through BaseEnvironment, so a sandboxed backend applies."""
    ctx = ToolContext(task_id="env", cwd=str(tmp_path))
    environment = get_environment("env", cwd=str(tmp_path))
    commands: list[str] = []
    original = environment.execute

    def recording(command, **kwargs):
        commands.append(command)
        return original(command, **kwargs)

    monkeypatch.setattr(environment, "execute", recording)
    assert _run("print('through the environment')", ctx)["stdout"] == "through the environment\n"
    assert commands, "execute_code never reached the environment"
    assert all(str(tmp_path) not in command for command in commands), commands


def test_code_runs_on_the_registered_backend_not_on_the_host(tmp_path, clite_home):
    """A fake backend answers instead of the host: proving the code went through it."""
    import clite.core.config as config
    from clite.tools.environments import cleanup_environment, register_environment_backend

    seen: list[str] = []

    class FakeSandbox:
        name = "fake-sandbox"

        def __init__(self, *, cwd="", timeout=180):
            self.cwd = cwd or str(tmp_path)
            self.default_timeout = timeout

        def resolve_path(self, path):
            return path if os.path.isabs(path) else os.path.join(self.cwd, path)

        def execute(self, command, **kwargs):
            from clite.tools.environments.base import ExecResult

            seen.append(command)
            return ExecResult("", 0)

        def cleanup(self):
            pass

    register_environment_backend(
        "fake-sandbox", lambda *, cwd="", timeout=180: FakeSandbox(cwd=cwd, timeout=timeout)
    )
    (clite_home / "config.yaml").write_text("terminal:\n  backend: fake-sandbox\n")
    config.reset_config_cache()
    cleanup_environment("sandbox")

    ctx = ToolContext(task_id="sandbox", cwd=str(tmp_path))
    result = _run("print('unused')", ctx)
    assert seen, "the code never reached the configured backend"
    assert result["stdout"] == ""  # the fake backend produced nothing


def test_the_python_used_is_the_one_running_the_agent_on_the_local_backend(tmp_path):
    ctx = ToolContext(task_id="py", cwd=str(tmp_path))
    assert _run("import sys; print(sys.executable)", ctx)["stdout"].strip() == sys.executable
