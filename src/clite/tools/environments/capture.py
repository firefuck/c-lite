"""Waiting for a started command: stream and cap its output, enforce timeout and interrupt.

Every backend starts its process differently (a local shell, ``docker exec``, ``ssh``) but
waits for it the same way, so the waiting lives here once and ``ExecResult`` reads the same
on every backend.
"""

from __future__ import annotations

import codecs
import io
import subprocess
import threading
import time
from collections.abc import Callable, Iterator

from clite.core.threads import start_thread
from clite.tools.environments.base import ExecResult

POLL_SECONDS = 0.05
DEFAULT_MAX_OUTPUT_CHARS = 50_000
_READER_JOIN_SECONDS = 2.0


def read_output_chunks(stream) -> Iterator[str]:
    """Drain a subprocess pipe in bounded chunks, preserving split UTF-8 characters."""
    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder("utf-8")(errors="replace"),
        translate=True,
    )
    while data := stream.buffer.read1(8192):
        text = decoder.decode(data)
        if text:
            yield text
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


def kill_client(process: subprocess.Popen) -> None:
    """Stop a client process (``docker exec``, ``ssh``) whose command lives elsewhere.

    The remote side keeps its own state; a client that does not die in time is left to the
    operating system rather than blocking the turn.
    """
    process.kill()
    try:
        process.wait(2.0)
    except subprocess.TimeoutExpired:
        pass


def capture(
    process: subprocess.Popen,
    *,
    timeout: int,
    stdin_data: str | None,
    interrupt: threading.Event | None,
    on_output: Callable[[str], None] | None,
    max_output_chars: int | None,
    stop: Callable[[subprocess.Popen], None],
    reader_name: str,
) -> ExecResult:
    """Feed ``stdin_data``, collect output until ``process`` exits, and describe how it ended.

    Output past ``max_output_chars`` is dropped (``on_output`` still sees all of it). On a
    timeout or an interrupt ``stop`` ends the process, and the exit code becomes 124 or 130 the
    way a shell reports them.
    """
    limit = DEFAULT_MAX_OUTPUT_CHARS if max_output_chars is None else max(0, max_output_chars)
    deadline = time.monotonic() + timeout
    chunks: list[str] = []
    size = 0
    truncated = False

    def collect() -> None:
        nonlocal size, truncated
        assert process.stdout is not None
        for chunk in read_output_chunks(process.stdout):
            if on_output is not None:
                try:
                    on_output(chunk)
                except Exception:  # noqa: BLE001 - a display callback must not kill the read loop
                    pass
            retained = chunk[: max(0, limit - size)]
            if retained:
                chunks.append(retained)
                size += len(retained)
            if len(retained) < len(chunk):
                truncated = True

    reader = start_thread(collect, name=reader_name)
    if stdin_data is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_data)
            process.stdin.close()
        except OSError:
            pass

    timed_out, interrupted = _wait(process, deadline, interrupt)
    if timed_out or interrupted:
        stop(process)
    reader.join(timeout=_READER_JOIN_SECONDS)

    output = "".join(chunks)
    if truncated:
        output += f"\n[output truncated at {limit} characters]"
    exit_code = process.returncode if process.returncode is not None else -1
    if timed_out:
        output += f"\n[command timed out after {timeout}s and was killed]"
        exit_code = 124
    elif interrupted:
        output += "\n[command interrupted]"
        exit_code = 130
    return ExecResult(output, exit_code, timed_out, interrupted, truncated)


def _wait(process: subprocess.Popen, deadline: float, interrupt: threading.Event | None) -> tuple[bool, bool]:
    """Wait for ``process`` to exit. ``(timed_out, interrupted)``; both false when it exited."""
    while process.poll() is None:
        if interrupt is not None and interrupt.is_set():
            return False, True
        if time.monotonic() > deadline:
            return True, False
        time.sleep(POLL_SECONDS)
    return False, False
