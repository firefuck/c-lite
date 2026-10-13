"""Message search: the text a message is indexed by, and the statements that look it up.

User text never becomes SQL or FTS5 syntax: every term of an FTS query is quoted, and the
wildcards of a ``LIKE`` pattern are escaped. The statements are only built here;
:class:`clite.state.db.SessionDB` runs them under its lock, FTS5 first and ``LIKE`` when SQLite
has no FTS5 or rejects the expression.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# SQL text and its parameters, as ``sqlite3.Connection.execute`` takes them.
Statement = tuple[str, tuple[Any, ...]]


def search_text_of(content: Any) -> str | None:
    """The plain text of a message's content, for the search index.

    A string is its own text. A list of parts contributes only its ``text`` parts: a user
    message with an image would otherwise put a base64 blob into the FTS index, making it as
    large as the picture for no benefit to search.
    """
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return (
            "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
            or None
        )
    return None


def search_statements(
    query: str, *, limit: int, session_id: str | None, exclude_session_ids: Sequence[str]
) -> tuple[Statement, Statement] | None:
    """The FTS5 statement that finds ``query`` and its ``LIKE`` fallback; None when it is blank.

    Both select the newest ``limit`` matching messages with a snippet, within ``session_id``
    when one is given and outside ``exclude_session_ids``.
    """
    query = query.strip()
    if not query:
        return None
    filters, params = [], []
    if session_id:
        filters.append("m.session_id = ?")
        params.append(session_id)
    if exclude_session_ids:
        filters.append(f"m.session_id NOT IN ({','.join('?' * len(exclude_session_ids))})")
        params.extend(exclude_session_ids)
    extra = (" AND " + " AND ".join(filters)) if filters else ""
    columns = (
        "m.id AS message_id, m.session_id, m.role, m.timestamp, m.tool_name, "
        "s.title AS session_title, s.source AS session_source"
    )
    fts = (
        f"""SELECT {columns},
                   snippet(messages_fts, 0, '>>', '<<', ' … ', 24) AS snippet
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE messages_fts MATCH ?{extra}
            ORDER BY m.timestamp DESC LIMIT ?""",
        (fts_query(query), *params, limit),
    )
    like = (
        f"""SELECT {columns}, substr(m.search_text, 1, 200) AS snippet
            FROM messages m JOIN sessions s ON s.id = m.session_id
            WHERE m.search_text LIKE ? ESCAPE '\\'{extra}
            ORDER BY m.timestamp DESC LIMIT ?""",
        ("%" + escape_like(query) + "%", *params, limit),
    )
    return fts, like


def fts_query(query: str) -> str:
    """Quote every term so user text can never be read as FTS5 syntax."""
    terms = [term.replace('"', '""') for term in query.split()]
    return " ".join(f'"{term}"' for term in terms if term)


def escape_like(text: str) -> str:
    """``text`` as a literal inside a ``LIKE`` pattern that declares ``ESCAPE '\\'``."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
