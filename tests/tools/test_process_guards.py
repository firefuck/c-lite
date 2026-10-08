"""Process ownership and bounded output against local subprocesses."""

from __future__ import annotations

import json
import shlex
import sys
from contextlib import nullcontext

import pytest

from clite.core.constants import home_scope
from clite.tools.builtin.process import process_registry, process_tool
from clite.tools.builtin.terminal import terminal_tool
from clite.tools.context import ToolContext
from clite.tools.environments.local import LocalEnvironment

pytestmark = pytest.mark.platforms("posix")


def _python(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


@pytest.mark.parametrize("action", ["poll", "log", "wait", "kill", "write"])
@pytest.mark.parametrize("foreign", ["task", "profile", "empty"])
def test_process_actions_reject_other_owners_without_touching_the_process(tmp_path, action, foreign):
    owner = ToolContext(task_id="owner", cwd=str(tmp_path))
    started = json.loads(terminal_tool({"command": "read value; echo got:$value", "background": True}, owner))
    process_id = started["process_id"]
    caller = ToolContext(task_id="other" if foreign == "task" else "owner")
    if foreign == "empty":
        caller = ToolContext()
    scope = home_scope(tmp_path / "other-profile") if foreign == "profile" else nullcontext()
    with scope:
        result = json.loads(
            process_tool(
                {
                    "action": action,
                    "process_id": process_id,
                    "data": "intruder\n",
                    "timeout": 1,
                },
                caller,
            )
        )
    assert "error" in result
    managed = process_registry.get(process_id)
    assert managed is not None and managed.exit_code is None
    assert json.loads(process_tool({"action": "write", "process_id": process_id, "data": "owner\n"}, owner))[
        "written"
    ]
    waited = json.loads(process_tool({"action": "wait", "process_id": process_id, "timeout": 5}, owner))
    assert waited["finished"] and "got:owner" in waited["output"]
    assert "intruder" not in waited["output"]


def test_session_fallback_and_profile_filter_keep_process_lists_private(tmp_path):
    ctx = ToolContext(session_id="session", cwd=str(tmp_path))
    started = json.loads(terminal_tool({"command": "echo session-output", "background": True}, ctx))
    process_id = started["process_id"]
    assert json.loads(process_tool({"action": "wait", "process_id": process_id, "timeout": 5}, ctx))[
        "finished"
    ]
    assert [p["process_id"] for p in json.loads(process_tool({"action": "list"}, ctx))["processes"]] == [
        process_id
    ]
    assert json.loads(process_tool({"action": "list"}, ToolContext()))["processes"] == []
    with home_scope(tmp_path / "foreign"):
        assert json.loads(process_tool({"action": "list"}, ctx))["processes"] == []


def test_foreground_output_drains_a_huge_line_but_retains_only_the_character_limit(tmp_path):
    chunks = []
    result = LocalEnvironment(str(tmp_path)).execute(
        _python("import sys; sys.stdout.write('x' * 1000000 + 'END')"),
        max_output_chars=1000,
        on_output=chunks.append,
        timeout=5,
    )
    assert result.exit_code == 0 and result.truncated
    assert result.output.split("\n[output truncated", 1)[0] == "x" * 1000
    assert "".join(chunks).endswith("END")
    assert max(map(len, chunks)) <= 8192


def test_background_output_drains_a_huge_line_and_retains_the_exact_tail(tmp_path):
    managed = process_registry.spawn(
        _python("import sys; sys.stdout.write('x' * 1000000 + 'END')"), cwd=str(tmp_path), task_id="bounded"
    )
    assert process_registry.wait(managed, 5)
    assert managed.exit_code == 0
    assert managed.size == 200000
    assert managed.dropped == 800003
    assert len("".join(managed.chunks)) == 200000
    assert "".join(managed.chunks).endswith("END")


def test_chunked_output_preserves_multibyte_characters_across_pipe_reads(tmp_path):
    result = LocalEnvironment(str(tmp_path)).execute(
        _python("import sys; sys.stdout.write('😀' * 10000)"),
        max_output_chars=123,
        timeout=5,
    )
    assert result.exit_code == 0 and result.truncated
    assert result.output.split("\n[output truncated", 1)[0] == "😀" * 123


def test_background_reader_carries_secret_scope_and_output_redacts_it(tmp_path, monkeypatch):
    from clite.core.env import get_secret, secret_scope
    from clite.tools.builtin.process import ManagedProcess

    secret = "synthetic-scoped-value"
    observed = []
    append = ManagedProcess.append

    def observe_scope(self, text):
        observed.append(get_secret("LOCAL_PROCESS_TEST_SECRET"))
        append(self, text)

    monkeypatch.setattr(ManagedProcess, "append", observe_scope)
    with secret_scope({"LOCAL_PROCESS_TEST_SECRET": secret}):
        managed = process_registry.spawn(_python(f"print({secret!r})"), cwd=str(tmp_path), task_id="scope")
        assert process_registry.wait(managed, 5)
        assert secret not in managed.output()
        assert "[REDACTED]" in managed.output()
    assert observed and all(value == secret for value in observed)


def test_chunked_output_preserves_universal_newline_translation(tmp_path):
    result = LocalEnvironment(str(tmp_path)).execute(
        _python("import sys; sys.stdout.buffer.write(b'first\\r\\nsecond\\rthird\\n')"),
        timeout=5,
    )
    assert result.exit_code == 0
    assert result.output == "first\nsecond\nthird\n"


def test_foreground_output_callback_carries_the_callers_secret_scope(tmp_path):
    from clite.core.env import get_secret, secret_scope

    observed = []
    with secret_scope({"LOCAL_PROCESS_TEST_SECRET": "synthetic-callback-value"}):
        result = LocalEnvironment(str(tmp_path)).execute(
            "echo callback",
            on_output=lambda text: observed.append(get_secret("LOCAL_PROCESS_TEST_SECRET")),
            timeout=5,
        )
    assert result.exit_code == 0
    assert observed and all(value == "synthetic-callback-value" for value in observed)
