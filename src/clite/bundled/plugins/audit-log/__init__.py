"""Audit log: a small, complete plugin to copy from.

It shows the three things most plugins do: observe a lifecycle hook, add a slash command and
add a CLI subcommand. Enable it with ``clite plugins enable audit-log``.

Settings (``plugins.entries.audit-log.settings`` in config.yaml):

``max_result_chars``  how much of each tool result to keep (default 200)
"""

from __future__ import annotations

import json
import time

from clite.core.constants import ensure_dir, get_logs_dir
from clite.core.redact import redact

FILENAME = "tool-audit.jsonl"


def _log_path():
    return get_logs_dir() / FILENAME


def read_entries(limit: int = 20) -> list[dict]:
    try:
        lines = _log_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def format_entries(entries: list[dict]) -> str:
    if not entries:
        return "No tool calls recorded yet."
    return "\n".join(
        f"{time.strftime('%H:%M:%S', time.localtime(entry['time']))}  {entry['tool']:<14} "
        f"{entry['duration_ms']:>6} ms  {entry['args']}"
        for entry in entries
    )


def register(ctx) -> None:
    max_chars = int(ctx.settings.get("max_result_chars", 200))

    def on_tool_call(tool_name, args, result, duration, session_id):
        # A hook names only the keyword arguments it needs; core may pass more.
        entry = {
            "time": time.time(), "session_id": session_id, "tool": tool_name,
            "args": redact(json.dumps(args, ensure_ascii=False, default=str))[:500],
            "result": redact(str(result))[:max_chars], "duration_ms": round(duration * 1000),
        }
        ensure_dir(get_logs_dir())
        with open(_log_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def audit_command(args: str, session=None) -> str:
        limit = int(args) if args.strip().isdigit() else 10
        return format_entries(read_entries(limit))

    def audit_cli(args) -> int:
        print(format_entries(read_entries(args.limit)))
        return 0

    ctx.register_hook("post_tool_call", on_tool_call)
    ctx.register_command("audit", audit_command, description="Show recent tool calls", args_hint="[count]")
    ctx.register_cli_command("audit", "Show recent tool calls recorded by the audit-log plugin", audit_cli,
                             setup=lambda parser: parser.add_argument("--limit", type=int, default=20))
