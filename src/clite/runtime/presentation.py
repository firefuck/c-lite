"""Small presentation helpers shared by every surface (terminal, RPC clients, gateway)."""

from __future__ import annotations

import json
from typing import Any

# What to show for a tool call: the one argument that says what it is doing.
_PREVIEW_ARGS = {
    "terminal": "command",
    "read_file": "path",
    "write_file": "path",
    "patch": "path",
    "search_files": "pattern",
    "web_fetch": "url",
    "skill_view": "name",
    "skill_manage": "name",
    "delegate_task": "goal",
    "session_search": "query",
    "clarify": "question",
    "memory": "content",
    "process": "action",
    "cronjob": "action",
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


def tool_diffs(result: str) -> list[tuple[str, str]]:
    """Pull ``(path, diff)`` pairs out of a ``patch`` / ``write_file`` tool result.

    The tools that change files return ``{"files": [{"path": ..., "diff": ...}]}``; a surface
    that wants to colour the change reads them from here instead of knowing the payload shape.
    """
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    pairs: list[tuple[str, str]] = []
    for entry in payload.get("files") or []:
        if isinstance(entry, dict) and isinstance(entry.get("diff"), str) and entry["diff"].strip():
            pairs.append((str(entry.get("path", "")), entry["diff"]))
    return pairs


# The semantic roles a Markdown/diff renderer needs, and the skin key that colours each one.
# The renderer names roles; the skin names colours; this table ties the two together so neither
# surface has to know ANSI codes.
MARKDOWN_ROLE_KEYS = {
    "heading": "md_heading",
    "code": "md_code",
    "fence": "md_fence",
    "table": "md_table",
    "marker": "md_marker",
    "quote": "md_quote",
    "rule": "md_rule",
    "link": "md_link",
    "diff_add": "diff_add",
    "diff_del": "diff_del",
    "diff_hunk": "diff_hunk",
    "diff_file": "diff_file",
    "diff_context": "diff_context",
}

_COLOR_CODES = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "gray": "90",
    "bright_red": "91",
    "bright_green": "92",
    "bright_yellow": "93",
    "bright_blue": "94",
    "bright_magenta": "95",
    "bright_cyan": "96",
    "bold": "1",
    "dim": "2",
}


def markdown_role_codes(skin: dict[str, str]) -> dict[str, str]:
    """Turn a skin (role name -> colour name) into a renderer role map (role -> ANSI code).

    Pure: the same skin always yields the same codes, and a role the skin leaves blank is
    dropped, which is what makes ``NO_COLOR`` and a dumb terminal come out as plain text.
    """
    codes: dict[str, str] = {}
    for role, key in MARKDOWN_ROLE_KEYS.items():
        code = _COLOR_CODES.get(skin.get(key, ""), "")
        if code:
            codes[role] = code
    return codes
