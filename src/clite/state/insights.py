"""Usage analytics over the session store: aggregate queries and their plain-text report.

The queries read through the connection :meth:`clite.state.db.SessionDB.get_insights` hands
over, with its lock held.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any


def collect_insights(conn: sqlite3.Connection, days: int) -> dict[str, Any]:
    """Aggregate usage analytics across sessions and messages.

    Rules:
    - Subagents (parent_session_id IS NOT NULL) are attributed to their parent session
      when counting sessions and platform distributions, never double-counted.
    - Token usage and costs are aggregated per model and per day.
    - Sessions without cost estimation are counted in `unpriced_sessions`, not zeroed out.
    """
    cutoff = time.time() - (days * 86400) if days > 0 else 0.0
    platforms, subagents = _sessions(conn, cutoff)
    totals = _totals(conn, cutoff)
    return {
        "days": days,
        "total_sessions": sum(platforms.values()),
        "total_subagents": subagents,
        "total_messages": totals["messages"],
        "tokens": totals["tokens"],
        "cost": totals["cost"],
        "models": _models(conn, cutoff),
        "platforms": platforms,
        "tools": _tools(conn, cutoff),
        "daily": _daily(conn, cutoff),
    }


def _sessions(conn: sqlite3.Connection, cutoff: float) -> tuple[dict[str, int], int]:
    """Root sessions per platform, and the number of subagent sessions."""
    cur = conn.execute(
        "SELECT source, COUNT(*) FROM sessions WHERE started_at >= ? AND parent_session_id IS NULL GROUP BY source",
        (cutoff,),
    )
    platforms = {row[0]: row[1] for row in cur.fetchall()}
    cur = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE started_at >= ? AND parent_session_id IS NOT NULL",
        (cutoff,),
    )
    return platforms, cur.fetchone()[0]


def _totals(conn: sqlite3.Connection, cutoff: float) -> dict[str, Any]:
    """Token, message and cost totals across all sessions in the period."""
    cur = conn.execute(
        """
        SELECT
            COALESCE(SUM(input_tokens), 0),
            COALESCE(SUM(output_tokens), 0),
            COALESCE(SUM(cache_read_tokens), 0),
            COALESCE(SUM(cache_write_tokens), 0),
            COALESCE(SUM(reasoning_tokens), 0),
            COALESCE(SUM(message_count), 0),
            COALESCE(SUM(CASE WHEN estimated_cost_usd IS NOT NULL THEN estimated_cost_usd ELSE 0.0 END), 0.0),
            COUNT(CASE WHEN estimated_cost_usd IS NULL THEN 1 END),
            COUNT(CASE WHEN estimated_cost_usd IS NOT NULL THEN 1 END)
        FROM sessions
        WHERE started_at >= ?
        """,
        (cutoff,),
    )
    in_tok, out_tok, cr_tok, cw_tok, reas_tok, total_msgs, total_cost, unpriced, priced = cur.fetchone()
    return {
        "messages": total_msgs,
        "tokens": {
            "input": in_tok,
            "output": out_tok,
            "cache_read": cr_tok,
            "cache_write": cw_tok,
            "reasoning": reas_tok,
            "total": in_tok + out_tok,
        },
        "cost": {
            "total_usd": round(total_cost, 6),
            "unpriced_sessions": unpriced,
            "priced_sessions": priced,
            "has_unpriced": bool(unpriced > 0),
        },
    }


def _models(conn: sqlite3.Connection, cutoff: float) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT
            model,
            COALESCE(SUM(input_tokens), 0),
            COALESCE(SUM(output_tokens), 0),
            COALESCE(SUM(CASE WHEN estimated_cost_usd IS NOT NULL THEN estimated_cost_usd ELSE 0.0 END), 0.0),
            COUNT(CASE WHEN estimated_cost_usd IS NULL THEN 1 END)
        FROM sessions
        WHERE started_at >= ?
        GROUP BY model
        ORDER BY (SUM(input_tokens) + SUM(output_tokens)) DESC
        """,
        (cutoff,),
    )
    return [
        {
            "model": name or "unknown",
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
            "cost_usd": round(cost, 6),
            "unpriced_sessions": unpriced,
        }
        for name, tokens_in, tokens_out, cost, unpriced in cur.fetchall()
    ]


def _tools(conn: sqlite3.Connection, cutoff: float) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT tool_name, COUNT(*) as cnt
        FROM messages
        WHERE role = 'tool' AND tool_name IS NOT NULL AND timestamp >= ?
        GROUP BY tool_name
        ORDER BY cnt DESC
        LIMIT 20
        """,
        (cutoff,),
    )
    return [{"name": row[0], "count": row[1]} for row in cur.fetchall()]


def _daily(conn: sqlite3.Connection, cutoff: float) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT
            date(started_at, 'unixepoch') as day,
            COUNT(CASE WHEN parent_session_id IS NULL THEN 1 END) as sess_count,
            COALESCE(SUM(input_tokens + output_tokens), 0) as tok_count,
            COALESCE(SUM(CASE WHEN estimated_cost_usd IS NOT NULL THEN estimated_cost_usd ELSE 0.0 END), 0.0) as day_cost
        FROM sessions
        WHERE started_at >= ?
        GROUP BY day
        ORDER BY day DESC
        LIMIT 30
        """,
        (cutoff,),
    )
    return [
        {"date": day, "sessions": sessions, "tokens": tokens, "cost_usd": round(cost, 6)}
        for day, sessions, tokens, cost in cur.fetchall()
        if day
    ]


def format_insights(data: dict[str, Any]) -> str:
    """Format aggregate insights dictionary into clean terminal output."""
    lines = [
        f"C-lite Usage Insights (Past {data['days']} Days)",
        "─" * 58,
    ]
    plat_str = ", ".join(f"{k}: {v}" for k, v in data["platforms"].items()) or "none"
    lines.append(f"Sessions:     {data['total_sessions']} ({plat_str})")
    if data["total_subagents"]:
        lines.append(f"Subagents:    {data['total_subagents']}")
    lines.append(f"Messages:     {data['total_messages']:,}")
    tok = data["tokens"]
    lines.append(f"Total Tokens: {tok['total']:,} (in: {tok['input']:,}, out: {tok['output']:,})")

    cost = data["cost"]
    cost_str = f"${cost['total_usd']:.4f}"
    if cost["unpriced_sessions"]:
        cost_str += (
            f" ({cost['unpriced_sessions']} unpriced session{'s' if cost['unpriced_sessions'] > 1 else ''})"
        )
    lines.append(f"Cost:         {cost_str}")

    if data["models"]:
        lines.append("\nTop Models:")
        for m in data["models"][:5]:
            c = (
                f"${m['cost_usd']:.4f}"
                if m["cost_usd"] > 0
                else ("(unpriced)" if m["unpriced_sessions"] else "$0.00")
            )
            lines.append(f"  • {m['model']:<20} {m['total_tokens']:,} tokens ({c})")

    if data["tools"]:
        lines.append("\nTop Tools:")
        lines.extend(f"  • {t['name']:<20} {t['count']:,} calls" for t in data["tools"][:5])

    if data["daily"]:
        lines.append("\nDaily Activity:")
        lines.extend(
            f"  • {d['date']}: {d['sessions']} sessions, {d['tokens']:,} tokens, ${d['cost_usd']:.4f}"
            for d in data["daily"][:7]
        )

    return "\n".join(lines)
