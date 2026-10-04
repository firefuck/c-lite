"""``session_search``: recall past conversations from the session database."""

from __future__ import annotations

import time
from typing import Any

from clite.state.db import get_session_db
from clite.tools.context import ToolContext
from clite.tools.registry import PARALLEL_SAFE, registry, tool_error, tool_result

SESSION_SEARCH_SCHEMA = {
    "name": "session_search",
    "description": (
        "Search past conversations (all sessions, including parts that were summarised away) by keyword. "
        "Use it when the user refers to earlier work that is not in the current context. Returns matching "
        "messages with their session and date. Pass session_id and message_id from a result to read the "
        "messages around a hit. With no query, lists recent sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords to look for. All of them must appear."},
            "limit": {"type": "integer", "description": "Maximum matches (default 10)."},
            "session_id": {"type": "string", "description": "With message_id: read context around a hit."},
            "message_id": {"type": "integer", "description": "The message to centre the context window on."},
        },
    },
}


def _date(timestamp: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp)) if timestamp else ""


def session_search_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    db = getattr(getattr(ctx, "agent", None), "db", None) or get_session_db()
    session_id, message_id = args.get("session_id"), args.get("message_id")
    if session_id and message_id is not None:
        window = db.get_message_window(str(session_id), int(message_id), window=4)
        if not window:
            return tool_error("No such message in that session.")
        return tool_result(session_id=session_id, messages=[
            {"message_id": m["_row_id"], "role": m["role"], "date": _date(m.get("timestamp")),
             "content": (m["content"] if isinstance(m.get("content"), str) else str(m.get("content") or ""))[:2000]}
            for m in window
        ])

    query = str(args.get("query") or "").strip()
    try:
        limit = max(1, min(int(args.get("limit") or 10), 50))
    except (TypeError, ValueError):
        return tool_error("limit must be an integer")
    if not query:
        sessions = db.list_sessions(limit=limit)
        return tool_result(sessions=[
            {"session_id": s["id"], "title": s.get("title") or "", "source": s["source"],
             "date": _date(s.get("last_activity_at") or s.get("started_at")), "messages": s.get("message_count", 0)}
            for s in sessions if s["id"] != ctx.session_id
        ])

    # The current session is excluded: its content is already in context.
    exclude = [ctx.session_id] if ctx.session_id else []
    hits = db.search_messages(query, limit=limit * 2, exclude_session_ids=exclude)
    seen: set[tuple[str, str]] = set()
    results = []
    for hit in hits:
        key = (hit["session_id"], hit.get("snippet") or "")
        if key in seen:  # an archived row and its compacted copy match the same text
            continue
        seen.add(key)
        results.append({
            "session_id": hit["session_id"], "session_title": hit.get("session_title") or "",
            "message_id": hit["message_id"], "role": hit["role"], "date": _date(hit.get("timestamp")),
            "snippet": hit.get("snippet") or "",
        })
        if len(results) >= limit:
            break
    return tool_result(query=query, results=results, count=len(results))


registry.register("session_search", "session_search", SESSION_SEARCH_SCHEMA, session_search_tool, emoji="🗂️",
                  parallel=PARALLEL_SAFE)
