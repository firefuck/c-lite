"""``execute_code``: run a short Python program inside the session's execution environment.

The model uses this to compute something or reshape data without stitching together shell
one-liners. The program is not run by this module: it is handed to the *session's*
``BaseEnvironment`` (the same one ``terminal`` uses), so it runs wherever that backend runs —
on the host with ``local``, inside the container with ``docker``, on the remote host with
``ssh`` — and inherits the sandbox that backend provides.

Two things make the code a command rather than a privileged shortcut:

* The text goes through ``check_command`` first, so a destructive call written in Python
  (``shutil.rmtree``, ``os.remove``, ``os.system("rm -rf …")``) is flagged exactly like the
  command it wraps, and ``approvals.mode`` decides whether it runs.
* It is given the same stripped environment as any other command (``build_child_env``), so no
  credential from ``.env`` or a provider key is visible from inside the program, and its
  output is redacted before it reaches the transcript.

The program reaches the interpreter on stdin, which keeps the model's text out of the command
line entirely: no quoting, no shell, no length limit. A small bootstrap runner wraps the two
streams — each write is tagged with the stream it came from and flushed as it happens — so the
tool can split them apart again. Output is therefore *streamed, not buffered*: a program that
is killed at the timeout still shows everything it printed first. The price of feeding the
program on stdin is that the program cannot read stdin. Output a child process writes straight
to a file descriptor carries no tag, so a subprocess's stderr is reported as stdout.
"""

from __future__ import annotations

import base64
import json
import re
import shlex
import sys
import uuid
from typing import Any

from clite.core.redact import redact
from clite.tools.approval import check_command
from clite.tools.context import ToolContext
from clite.tools.environments import get_environment
from clite.tools.environments.base import BaseEnvironment
from clite.tools.registry import registry, tool_error, tool_result

MAX_TIMEOUT_SECONDS = 600
MAX_CODE_CHARS = 100_000
# The runner caps each stream at ``tool_output.max_chars`` and flushes every write, so the
# environment sees both streams interleaved and tagged. Ask it for room for the two streams
# plus the per-write tags, so its own limit never cuts the runner off mid-report.
_OUTPUT_HEADROOM = 4096
# Closing notes ``LocalEnvironment`` and ``DockerEnvironment`` append to the merged stream when
# they stop a command themselves. This tool reports the same facts in its own fields.
_ENVIRONMENT_NOTES = ("\n[command timed out after ", "\n[command interrupted]", "\n[output truncated at ")

# The bootstrap that runs the model's program. It is deliberately small and obvious: replace
# the two streams with bounded, self-flushing wrappers, each write tagged with the stream it
# belongs to, run the program as ``__main__``, then report the exit status. ``{code_b64}``,
# ``{limit}``, ``{stdout_tag}``, ``{stderr_tag}`` and ``{report_marker}`` are substituted by
# :func:`_runner_source`.
_RUNNER = '''\
import base64 as _b64, io as _io, json as _json, sys as _sys, traceback as _tb

class _Stream(_io.TextIOBase):
    """Forward writes to the real stream at once, tagged, stopping after `limit` characters."""
    def __init__(self, real, limit, tag):
        self._real, self._limit, self._tag, self.written, self.truncated = real, limit, tag, 0, False
    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        if not text:
            return 0
        room = self._limit - self.written
        if room <= 0:
            self.truncated = True
            return len(text)
        kept = text[:room]
        self.truncated = self.truncated or len(kept) < len(text)
        self.written += len(kept)
        self._real.write(self._tag + kept)
        self._real.flush()
        return len(text)
    def flush(self):
        self._real.flush()
    def writable(self):
        return True

_limit = {limit}
_real_out, _real_err = _sys.stdout, _sys.stderr
_out = _Stream(_real_out, _limit, {stdout_tag!r})
_err = _Stream(_real_out, _limit, {stderr_tag!r})
_program = _b64.b64decode({code_b64!r}).decode("utf-8", "replace")
_sys.stdout, _sys.stderr = _out, _err
_status = 0
try:
    exec(compile(_program, "<execute_code>", "exec"), {{"__name__": "__main__", "__file__": "<execute_code>"}})
except SystemExit as _exit:
    _status = _exit.code if isinstance(_exit.code, int) else (0 if _exit.code is None else 1)
except BaseException:
    _tb.print_exc(file=_err)
    _status = 1
finally:
    _sys.stdout, _sys.stderr = _real_out, _real_err
_report = _json.dumps({{"exit_code": _status, "stdout_truncated": _out.truncated, "stderr_truncated": _err.truncated}})
_real_out.write({report_marker!r} + _b64.b64encode(_report.encode("utf-8")).decode("ascii") + "\\n")
_real_out.flush()
'''


def _runner_source(code: str, limit: int) -> tuple[str, str, str, str]:
    """The bootstrap program plus the three markers the tool reads its output back with."""
    nonce = uuid.uuid4().hex
    stdout_tag = f"\x00clite-out:{nonce}\x00"
    stderr_tag = f"\x00clite-err:{nonce}\x00"
    report_marker = f"\x00clite-report:{nonce}\x00"
    source = _RUNNER.format(
        code_b64=base64.b64encode(code.encode("utf-8")).decode("ascii"),
        limit=limit,
        stdout_tag=stdout_tag,
        stderr_tag=stderr_tag,
        report_marker=report_marker,
    )
    return source, stdout_tag, stderr_tag, report_marker


def _split(merged: str, stdout_tag: str, stderr_tag: str) -> tuple[str, str]:
    """The merged stream as (stdout, stderr), reading the tag before each write."""
    stdout: list[str] = []
    stderr: list[str] = []
    current = stdout
    for part in re.split(f"({re.escape(stdout_tag)}|{re.escape(stderr_tag)})", merged):
        if part == stdout_tag:
            current = stdout
        elif part == stderr_tag:
            current = stderr
        else:
            # Output a child wrote straight to a file descriptor carries no tag; it is read as
            # stdout, which is where a program's own printing mostly goes.
            current.append(part)
    return "".join(stdout), "".join(stderr)


def _report(merged: str, marker: str) -> dict[str, Any] | None:
    """The runner's closing report, or ``None`` when it was killed before writing one."""
    index = merged.rfind(marker)
    if index < 0:
        return None
    try:
        payload = json.loads(base64.b64decode(merged[index + len(marker) :].strip()))
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _interpreter(environment: BaseEnvironment) -> str:
    """The Python that runs the program.

    The local backend is the interpreter running the agent. A container or a remote host is
    another machine, where this host's path means nothing, so the first ``python3`` on its
    PATH is asked for instead.
    """
    return sys.executable if getattr(environment, "name", "local") == "local" else "python3"


EXECUTE_CODE_SCHEMA = {
    "name": "execute_code",
    "description": (
        "Run a short Python program and get back its stdout, stderr and exit code. Use it to "
        "compute, parse or reshape data in one step instead of chaining shell commands. The "
        "program runs in the session's working directory through the active terminal backend, "
        "so it sees the same files the other tools do; it cannot read stdin. A program that "
        "deletes or overwrites things needs the user's approval, exactly like a shell command."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The Python program to run."},
            "timeout": {
                "type": "integer",
                "description": "Seconds before it is killed (default from config).",
            },
        },
        "required": ["code"],
    },
}


def execute_code_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        return tool_error("code is required: pass the Python program to run.")
    if len(code) > MAX_CODE_CHARS:
        return tool_error(
            f"code is too long ({len(code)} characters); the limit is {MAX_CODE_CHARS}. "
            "Write the data to a file and have the program read it instead."
        )

    try:
        environment = get_environment(ctx.task_id or ctx.session_id, cwd=ctx.cwd)
    except ValueError as exc:
        return tool_error(str(exc))

    # The same gate the terminal goes through, reading the program as the command it is. Where
    # it would run matters: a bare `config.yaml` in the agent's own home is a policy file.
    decision = check_command(code, ctx, cwd=environment.cwd)
    if not decision.approved:
        return tool_error(decision.reason, status="blocked")

    try:
        timeout = min(int(args.get("timeout") or environment.default_timeout), MAX_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return tool_error("timeout must be an integer number of seconds")

    limit = int(ctx.setting("tool_output.max_chars", 50_000) or 50_000)
    source, stdout_tag, stderr_tag, report_marker = _runner_source(code, limit)
    result = environment.execute(
        f"{shlex.quote(_interpreter(environment))} -",
        stdin_data=source,
        timeout=timeout,
        interrupt=ctx.interrupt,
        max_output_chars=2 * limit + _OUTPUT_HEADROOM,
    )

    # A killed runner left no report; the environment's own status and truncation stand then.
    report = _report(result.output, report_marker) or {}
    merged = result.output[: result.output.rfind(report_marker)] if report else result.output
    # The environment appends its own closing notes to the merged stream ("timed out ..."),
    # untagged, so they would land in the model's stdout and read as program output. Drop them:
    # the `error` field below says the same thing, in the tool's own words.
    for note in _ENVIRONMENT_NOTES:
        marker_index = merged.find(note)
        if marker_index >= 0:
            merged = merged[:marker_index]
    stdout, stderr = _split(merged, stdout_tag, stderr_tag)
    if report.get("stdout_truncated") or result.truncated:
        stdout += f"\n[stdout truncated at {limit} characters]"
    if report.get("stderr_truncated"):
        stderr += f"\n[stderr truncated at {limit} characters]"

    payload: dict[str, Any] = {
        "stdout": redact(stdout),
        "stderr": redact(stderr),
        "exit_code": int(report.get("exit_code", result.exit_code)),
    }
    if result.timed_out:
        payload["error"] = f"timed out after {timeout}s; the program and its child processes were killed"
        payload["exit_code"] = 124
    elif result.interrupted:
        payload["error"] = "interrupted"
        payload["exit_code"] = 130
    return tool_result(payload)


registry.register("execute_code", "terminal", EXECUTE_CODE_SCHEMA, execute_code_tool, emoji="🐍")
