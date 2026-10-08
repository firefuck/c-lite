"""Long-term memory in SQLite with FTS5 search: the worked example of a memory provider.

The built-in store (``MEMORY.md``/``USER.md``) is a short note the model reads every turn,
capped at a couple of thousand characters. This provider is the other end of that trade: facts
the model chooses to keep go into a SQLite database in the home directory, are found again
with FTS5 when they match what the user just asked, and are not bounded by prompt budgets.
Facts outlive the session that saved them.

``README.md`` beside this file walks through every ``MemoryProvider`` method and says when the
agent calls it. This module is the implementation, not the documentation.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from clite.agent.memory.provider import MemoryProvider
from clite.core.constants import ensure_dir, get_memories_dir

PROVIDER_NAME = "sqlite-memory"
DB_FILENAME = "sqlite-memory.sqlite3"

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_FACT_CHARS = 2000
# A query with hundreds of terms makes FTS5 do pointless work; the first few carry the meaning.
MAX_QUERY_TERMS = 32

# Letters and digits of any script. Splitting the user's message into bare terms keeps FTS5
# operators (AND, OR, NEAR, *) from being read as syntax.
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def match_query(text: str) -> str:
    """Turn free text into an FTS5 MATCH expression: each term quoted, joined with OR.

    Terms are quoted so that punctuation and FTS5 keywords in the user's message cannot turn
    into a syntax error.
    """
    terms = _WORD_RE.findall(text)[:MAX_QUERY_TERMS]
    return " OR ".join(f'"{term}"' for term in terms)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clamp_limit(value: Any) -> int:
    try:
        return max(1, min(MAX_LIMIT, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


class SqliteMemoryProvider(MemoryProvider):
    """Facts in one local SQLite table, searched with FTS5.

    The connection is opened on first use and shared between turns. Tool rounds can run on
    worker threads, so the connection is opened with ``check_same_thread=False`` and every use
    is serialised by a lock: SQLite objects are not thread-safe on their own.
    """

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def is_available(self) -> bool:
        """True when this Python's SQLite is built with FTS5. Opens no file, touches no network."""
        try:
            with sqlite3.connect(":memory:") as probe:
                options = [str(row[0]) for row in probe.execute("pragma compile_options")]
        except sqlite3.Error:
            return False
        return any("FTS5" in option.upper() for option in options)

    def initialize(self, session_id: str, **context: Any) -> None:
        with self._lock:
            self._connect()

    def shutdown(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── recall ───────────────────────────────────────────────────────────────────────────

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Facts matching the user's message. No match means no block is added at all.

        The manager fences whatever comes back in ``<memory-context>`` and attaches it to the
        user message, so this text is background, not an instruction.
        """
        facts = self.search(query, DEFAULT_LIMIT)
        if not facts:
            return ""
        return "Facts remembered from earlier sessions:\n" + "\n".join(
            f"- {fact}" for fact in facts
        )

    # ── the two tools this provider adds ─────────────────────────────────────────────────

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "memory_save",
                "description": (
                    "Save a durable fact about the user or their work so it can be recalled in "
                    "later sessions: a preference, a convention, a piece of their environment. "
                    "Not for things that only matter inside this conversation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The fact, in one sentence, standing on its own.",
                        }
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "memory_search",
                "description": (
                    "Search facts saved in earlier sessions. Use it when the user refers to "
                    "something you may have been told before."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to look for."},
                        "limit": {
                            "type": "integer",
                            "description": f"How many facts to return (default {DEFAULT_LIMIT}).",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context: Any) -> str:
        if tool_name == "memory_save":
            return json.dumps(self.save(str(args.get("content", ""))))
        if tool_name == "memory_search":
            facts = self.search(str(args.get("query", "")), _clamp_limit(args.get("limit")))
            return json.dumps({"results": facts})
        raise NotImplementedError(f"{self.name} does not handle tool {tool_name!r}")

    # ── storage ──────────────────────────────────────────────────────────────────────────

    def save(self, content: str) -> dict[str, Any]:
        """Store one fact. Repeating a fact is reported back rather than stored twice."""
        content = content.strip()
        if not content:
            return {"success": False, "error": "Nothing to save."}
        if len(content) > MAX_FACT_CHARS:
            return {
                "success": False,
                "error": f"Fact is {len(content)} characters; the limit is {MAX_FACT_CHARS}.",
            }
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "INSERT INTO facts (content, created_at) SELECT ?, ? "
                "WHERE NOT EXISTS (SELECT 1 FROM facts WHERE content = ?)",
                (content, _now(), content),
            )
            conn.commit()
            stored = cursor.rowcount
        if stored == 0:
            return {"success": False, "error": "That fact is already saved."}
        return {"success": True, "saved": content}

    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> list[str]:
        """Facts whose text matches ``query``, best match first."""
        match = match_query(query)
        if not match:
            return []
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT content FROM facts WHERE facts MATCH ? ORDER BY rank LIMIT ?",
                (match, _clamp_limit(limit)),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            directory = get_memories_dir()
            ensure_dir(directory)
            conn = sqlite3.connect(directory / DB_FILENAME, check_same_thread=False)
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS facts USING fts5(content, created_at UNINDEXED)"
            )
            conn.commit()
            self._conn = conn
        return self._conn


def register(ctx) -> None:
    ctx.register_memory_provider(PROVIDER_NAME, SqliteMemoryProvider)
