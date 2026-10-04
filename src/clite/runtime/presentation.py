"""Small presentation helpers shared by every surface (terminal, RPC clients, gateway)."""

from __future__ import annotations

import json
from typing import Any

# What to show for a tool call: the one argument that says what it is doing.
_PREVIEW_ARGS = {
    "terminal": "command", "read_file": "path", "write_file": "path", "patch": "path", "search_files": "pattern",
    "web_fetch": "url", "skill_view": "name", "skill_manage": "name", "delegate_task": "goal",
    "session_search": "query", "clarify": "question", "memory": "content", "process": "action", "cronjob": "action",
}


def tool_preview(name: str, args: dict[str, Any], width: int = 70) -> str:
    """One line describing a tool call, for progress displays."""
    key = _PREVIEW_ARGS.get(name)
    value = args.get(key) if key else None
    if value is None:
        value = next((v for v in args.values() if isinstance(v, str) and v), "")
    text = " ".join(str(value).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def result_failed(result: str) -> bool:
    """True when a tool result is an error payload."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and bool(payload.get("error"))
