"""Waiting for a started command, shared by the local, Docker and SSH backends."""

from __future__ import annotations

import subprocess
import sys
import threading

from clite.tools.environments.capture import capture, kill_client


def _start(code: str, *, stdin: bool = False) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _capture(process: subprocess.Popen, **overrides):
    options = {
        "timeout": 30,
        "stdin_data": None,
        "interrupt": None,
        "on_output": None,
        "max_output_chars": None,
        "stop": kill_client,
        "reader_name": "test-reader",
    }
    options.update(overrides)
    return capture(process, **options)


def test_a_finished_command_returns_its_output_and_exit_code():
    result = _capture(_start("import sys; print('hello'); sys.exit(3)"))
    assert result.output == "hello\n"
    assert result.exit_code == 3
    assert not (result.timed_out or result.interrupted or result.truncated)


def test_stdin_data_reaches_the_command():
    result = _capture(_start("print(input().upper())", stdin=True), stdin_data="ping\n")
    assert result.output == "PING\n"


def test_output_past_the_cap_is_dropped_but_still_streamed():
    seen: list[str] = []
    result = _capture(_start("print('x' * 100)"), max_output_chars=10, on_output=seen.append)
    assert result.truncated
    assert result.output.startswith("x" * 10 + "\n[output truncated at 10 characters]")
    assert "".join(seen) == "x" * 100 + "\n"


def test_a_failing_display_callback_does_not_lose_output():
    def broken(_chunk: str) -> None:
        raise RuntimeError("display bug")

    result = _capture(_start("print('kept')"), on_output=broken)
    assert result.output == "kept\n"


def test_a_command_past_its_timeout_is_stopped_and_reports_124():
    stopped: list[subprocess.Popen] = []

    def stop(process: subprocess.Popen) -> None:
        stopped.append(process)
        kill_client(process)

    process = _start("import time; time.sleep(30)")
    result = _capture(process, timeout=0, stop=stop)
    assert stopped == [process]
    assert result.timed_out and result.exit_code == 124
    assert "[command timed out after 0s and was killed]" in result.output


def test_an_interrupted_command_is_stopped_and_reports_130():
    interrupt = threading.Event()
    interrupt.set()
    result = _capture(_start("import time; time.sleep(30)"), interrupt=interrupt)
    assert result.interrupted and result.exit_code == 130
    assert result.output.endswith("[command interrupted]")
