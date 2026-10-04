"""``terminal``: run a shell command in the session's execution environment."""

from __future__ import annotations

import re
from typing import Any

from clite.core.redact import redact
from clite.plugins.hooks import first_result, has_hook, invoke_hook
from clite.tools.approval import check_command
from clite.tools.context import ToolContext
from clite.tools.environments import get_environment
from clite.tools.registry import registry, tool_error, tool_result

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
MAX_TIMEOUT_SECONDS = 3600

TERMINAL_SCHEMA = {
    "name": "terminal",
    "description": (
        "Run a shell command. The working directory persists between calls, so `cd` carries over. "
        "Output is stdout and stderr merged. For long-running work (servers, watchers, builds over a "
        "few minutes) set background=true and manage it with the process tool. Prefer read_file, "
        "write_file, patch and search_files over cat, echo >, sed and grep: they are safer and "
        "return structured results. Commands that can destroy data need the user's approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command line to run."},
            "timeout": {"type": "integer", "description": "Seconds before the command is killed (default from config)."},
            "workdir": {"type": "string", "description": "Run in this directory instead of the current one."},
            "background": {"type": "boolean", "description": "Start and return immediately with a process_id."},
        },
        "required": ["command"],
    },
}


def clip_lines(text: str, max_lines: int | None) -> str:
    """Keep the first and last lines of very long output; the middle is rarely the answer."""
    if not max_lines:
        return text
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    head, tail = max_lines * 2 // 3, max_lines // 3
    omitted = len(lines) - head - tail
    return "\n".join([*lines[:head], f"[... {omitted} lines omitted ...]", *lines[-tail:]])


def terminal_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return tool_error("command is required")

    decision = check_command(command, ctx)
    if not decision.approved:
        return tool_error(decision.reason, status="blocked")

    try:
        environment = get_environment(ctx.task_id or ctx.session_id, cwd=ctx.cwd)
    except ValueError as exc:
        return tool_error(str(exc))
    workdir = args.get("workdir") or None

    if args.get("background"):
        from clite.tools.builtin.process import process_registry

        cwd = environment.resolve_path(workdir) if workdir else environment.cwd
        try:
            managed = process_registry.spawn(command, cwd=cwd, task_id=ctx.task_id or ctx.session_id)
        except (OSError, RuntimeError) as exc:
            return tool_error(f"could not start background process: {exc}")
        return tool_result(process_id=managed.id, status="running", hint="Use the process tool to poll, wait or kill it.")

    try:
        timeout = min(int(args.get("timeout") or environment.default_timeout), MAX_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return tool_error("timeout must be an integer number of seconds")

    result = environment.execute(
        command, cwd=workdir, timeout=timeout, interrupt=ctx.interrupt,
        max_output_chars=ctx.setting("tool_output.max_chars", 50_000),
    )
    output = clip_lines(_ANSI.sub("", result.output), ctx.setting("tool_output.max_lines", 2000))
    if has_hook("transform_terminal_output"):
        replacement = first_result(
            invoke_hook("transform_terminal_output", command=command, output=output, exit_code=result.exit_code,
                        session_id=ctx.session_id)
        )
        if replacement is not None:
            output = replacement
    payload: dict[str, Any] = {"output": redact(output), "exit_code": result.exit_code}
    if result.timed_out:
        payload["error"] = f"timed out after {timeout}s"
    elif result.interrupted:
        payload["error"] = "interrupted"
    return tool_result(payload)


registry.register("terminal", "terminal", TERMINAL_SCHEMA, terminal_tool, emoji="💻")
