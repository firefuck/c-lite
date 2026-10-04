"""``SessionDB``: durable sessions and messages in ``<home>/state.db``.

Contracts the agent loop relies on:

* History is append-only. The only rewrite is compaction, which soft-archives the old rows
  (``active=0, compacted=1``) under the same session id so they stay searchable.
* A message is durable the moment :meth:`SessionDB.append_message` returns.
* Messages round-trip in the internal OpenAI-style shape (see ``docs/arsitektur``). Two
  extra keys ride along: ``provider_data`` (opaque data the same provider wants back) and
  ``turn_context`` (text that was sent with a user message but is not the user's words).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from clite.core.constants import ensure_dir, get_state_db_path, home_key
from clite.state.schema import (
    COLUMN_ADDITIONS,
    FTS_SQL,
    MIGRATIONS,
    SCHEMA_SQL,
    SCHEMA_VERSION,
    UPDATABLE_SESSION_COLUMNS,
)

_OPEN: dict[str, SessionDB] = {}
_OPEN_LOCK = threading.Lock()

# Message keys stored in their own columns. Anything else on a message is dropped on write.
_JSON_FIELDS = ("tool_calls", "provider_data")


def new_session_id() -> str:
    """Sortable session id: UTC timestamp plus a short random suffix."""
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime()) + "_" + uuid.uuid4().hex[:8]


def get_session_db(path: Path | None = None) -> SessionDB:
    """Process-wide ``SessionDB`` for the active home, opened once per database file."""
    target = path or get_state_db_path()
    key = home_key(target)
    with _OPEN_LOCK:
        db = _OPEN.get(key)
        if db is None or db.closed:
            db = _OPEN[key] = SessionDB(target)
        return db


def close_all_session_dbs() -> None:
    with _OPEN_LOCK:
        for db in _OPEN.values():
            db.close()
        _OPEN.clear()


class SessionDB:
    """Thread-safe wrapper around one SQLite connection."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else get_state_db_path()
        ensure_dir(self.path.parent)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self.closed = False
        self.fts_enabled = False
        self._init_schema()

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.executescript(SCHEMA_SQL)
            self._reconcile_columns()
            self._run_migrations()
            try:
                self._conn.executescript(FTS_SQL)
                self.fts_enabled = True
            except sqlite3.OperationalError:
                # SQLite built without FTS5: search falls back to LIKE.
                self.fts_enabled = False
            self._conn.commit()

    def _reconcile_columns(self) -> None:
        for table, columns in COLUMN_ADDITIONS.items():
            existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _run_migrations(self) -> None:
        row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            self._conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            return
        version = int(row["version"])
        while version < SCHEMA_VERSION:
            for statement in MIGRATIONS.get(version, []):
                self._conn.execute(statement)
            version += 1
            self._conn.execute("UPDATE schema_version SET version = ?", (version,))

    def close(self) -> None:
        with self._lock:
            if not self.closed:
                self._conn.close()
                self.closed = True

    # ── sessions ─────────────────────────────────────────────────────────────────────────

    def create_session(
        self,
        session_id: str,
        source: str,
        *,
        model: str | None = None,
        provider: str | None = None,
        system_prompt: str | None = None,
        parent_session_id: str | None = None,
        cwd: str | None = None,
        title: str | None = None,
        session_key: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        chat_type: str | None = None,
        thread_id: str | None = None,
        display_name: str | None = None,
        origin: dict[str, Any] | None = None,
        profile_name: str | None = None,
        model_config: dict[str, Any] | None = None,
        hidden: bool = False,
    ) -> bool:
        """Insert the session row. Idempotent: returns False when the id already exists."""
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                """INSERT OR IGNORE INTO sessions
                   (id, source, session_key, user_id, chat_id, chat_type, thread_id, display_name,
                    origin_json, model, provider, model_config, system_prompt, parent_session_id,
                    started_at, last_activity_at, cwd, profile_name, hidden)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, source, session_key, user_id, chat_id, chat_type, thread_id,
                    display_name, json.dumps(origin) if origin else None, model, provider,
                    json.dumps(model_config) if model_config else None, system_prompt,
                    parent_session_id, now, now, cwd, profile_name, int(hidden),
                ),
            )
            self._conn.commit()
            created = cursor.rowcount > 0
        if created and title:
            self.set_title(session_id, title)
        return created

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id: str, **fields: Any) -> None:
        unknown = set(fields) - UPDATABLE_SESSION_COLUMNS
        if unknown:
            raise ValueError(f"cannot update session column(s): {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{column} = ?" for column in fields)
        values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
        with self._lock:
            self._conn.execute(f"UPDATE sessions SET {assignments} WHERE id = ?", (*values, session_id))
            self._conn.commit()

    def end_session(self, session_id: str, reason: str) -> None:
        self.update_session(session_id, ended_at=time.time(), end_reason=reason)

    def set_title(self, session_id: str, title: str, *, source: str = "user") -> str:
        """Set a unique title; a clash gets a numeric suffix. Returns the title stored."""
        base = " ".join(title.split())[:120]
        if not base:
            raise ValueError("title must not be empty")
        candidate, attempt = base, 1
        with self._lock:
            while True:
                clash = self._conn.execute(
                    "SELECT id FROM sessions WHERE title = ? AND id != ?", (candidate, session_id)
                ).fetchone()
                if clash is None:
                    break
                attempt += 1
                candidate = f"{base} #{attempt}"
            self._conn.execute(
                "UPDATE sessions SET title = ?, title_source = ? WHERE id = ?",
                (candidate, source, session_id),
            )
            self._conn.commit()
        return candidate

    def add_usage(
        self,
        session_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        api_calls: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE sessions SET
                     input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                     cache_read_tokens = cache_read_tokens + ?,
                     cache_write_tokens = cache_write_tokens + ?,
                     reasoning_tokens = reasoning_tokens + ?, api_call_count = api_call_count + ?,
                     estimated_cost_usd = COALESCE(estimated_cost_usd, 0) + ?,
                     last_activity_at = ?
                   WHERE id = ?""",
                (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                 reasoning_tokens, api_calls, cost_usd, time.time(), session_id),
            )
            self._conn.commit()

    def list_sessions(
        self,
        *,
        sources: Sequence[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        include_hidden: bool = False,
        include_archived: bool = False,
        include_children: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if sources:
            clauses.append(f"source IN ({','.join('?' * len(sources))})")
            params.extend(sources)
        if not include_hidden:
            clauses.append("hidden = 0")
        if not include_archived:
            clauses.append("archived = 0")
        if not include_children:
            clauses.append("parent_session_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM sessions {where} "
                "ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_session(self, reference: str) -> dict[str, Any] | None:
        """Resolve an exact id, an exact title, or a unique id prefix."""
        reference = reference.strip()
        if not reference:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ? OR title = ?", (reference, reference)
            ).fetchone()
            if row is None:
                matches = self._conn.execute(
                    "SELECT * FROM sessions WHERE id LIKE ? ESCAPE '\\' LIMIT 2",
                    (_escape_like(reference) + "%",),
                ).fetchall()
                row = matches[0] if len(matches) == 1 else None
        return dict(row) if row else None

    def latest_session(self, sources: Sequence[str] | None = None) -> dict[str, Any] | None:
        found = self.list_sessions(sources=sources, limit=1)
        return found[0] if found else None

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            self._conn.execute("UPDATE sessions SET parent_session_id = NULL WHERE parent_session_id = ?",
                               (session_id,))
            cursor = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def prune_sessions(
        self,
        older_than_days: float,
        *,
        keep: Iterable[str] = (),
        dry_run: bool = False,
        now: float | None = None,
    ) -> int:
        """Delete sessions with no activity for ``older_than_days`` and return how many.

        Pinned sessions and the ids in ``keep`` survive. Children of a deleted session are
        detached, not deleted: each is judged by its own last activity.
        """
        cutoff = (time.time() if now is None else now) - float(older_than_days) * 86400
        spared = set(keep)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM sessions WHERE pinned = 0 AND COALESCE(last_activity_at, started_at) < ?",
                (cutoff,),
            ).fetchall()
            victims = [row["id"] for row in rows if row["id"] not in spared]
            if dry_run or not victims:
                return len(victims)
            for session_id in victims:
                self._conn.execute("UPDATE sessions SET parent_session_id = NULL WHERE parent_session_id = ?",
                                   (session_id,))
                self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()
        return len(victims)

    # ── messages ─────────────────────────────────────────────────────────────────────────

    def append_message(self, session_id: str, message: dict[str, Any]) -> int:
        """Persist one message and return its row id."""
        return self.append_messages(session_id, [message])[0]

    def append_messages(self, session_id: str, messages: Iterable[dict[str, Any]]) -> list[int]:
        row_ids: list[int] = []
        with self._lock:
            for message in messages:
                row_ids.append(self._insert_message(session_id, message))
            if row_ids:
                self._refresh_counts(session_id)
            self._conn.commit()
        return row_ids

    def _insert_message(self, session_id: str, message: dict[str, Any]) -> int:
        content = message.get("content")
        content_is_json = 0
        if content is not None and not isinstance(content, str):
            content, content_is_json = json.dumps(content, ensure_ascii=False), 1
        tool_calls = message.get("tool_calls")
        provider_data = message.get("provider_data")
        cursor = self._conn.execute(
            """INSERT INTO messages
               (session_id, role, content, content_is_json, tool_call_id, tool_calls, tool_name,
                timestamp, token_count, finish_reason, reasoning, provider_data, turn_context,
                display_kind, is_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, message["role"], content, content_is_json, message.get("tool_call_id"),
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                message.get("name"), float(message.get("timestamp") or time.time()),
                message.get("token_count"), message.get("finish_reason"), message.get("reasoning"),
                json.dumps(provider_data, ensure_ascii=False) if provider_data else None,
                message.get("turn_context") or None,
                message.get("display_kind"), int(bool(message.get("is_summary"))),
            ),
        )
        return int(cursor.lastrowid or 0)

    def _refresh_counts(self, session_id: str) -> None:
        self._conn.execute(
            """UPDATE sessions SET
                 message_count = (SELECT COUNT(*) FROM messages WHERE session_id = ? AND active = 1),
                 tool_call_count = (SELECT COUNT(*) FROM messages
                                    WHERE session_id = ? AND role = 'tool'),
                 last_activity_at = ?
               WHERE id = ?""",
            (session_id, session_id, time.time(), session_id),
        )

    def get_messages(self, session_id: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Messages in order, in the internal shape, each carrying its ``_row_id``."""
        where = "" if include_inactive else "AND active = 1"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM messages WHERE session_id = ? {where} ORDER BY id", (session_id,)
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def count_messages(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE session_id = ? AND active = 1", (session_id,)
            ).fetchone()
        return int(row["n"])

    def replace_active_messages(self, session_id: str, messages: Sequence[dict[str, Any]]) -> list[int]:
        """In-place compaction: archive every active row, then append ``messages``.

        Old rows keep their content (``active=0, compacted=1``) so ``session_search`` still
        finds them. The session id does not change.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE messages SET active = 0, compacted = 1 WHERE session_id = ? AND active = 1",
                (session_id,),
            )
            row_ids = [self._insert_message(session_id, message) for message in messages]
            self._conn.execute(
                "UPDATE sessions SET compression_count = compression_count + 1 WHERE id = ?",
                (session_id,),
            )
            self._refresh_counts(session_id)
            self._conn.commit()
        return row_ids

    def clear_provider_data(self, session_id: str) -> int:
        """Forget the opaque replay data on a session's active messages (the provider no
        longer accepts it). The visible transcript is untouched. Returns the rows changed."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE messages SET provider_data = NULL WHERE session_id = ? AND active = 1 "
                "AND provider_data IS NOT NULL",
                (session_id,),
            )
            self._conn.commit()
            return cursor.rowcount

    def deactivate_from(self, session_id: str, row_id: int) -> int:
        """Rewind: drop ``row_id`` and everything after it from the active transcript."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE messages SET active = 0 WHERE session_id = ? AND id >= ? AND active = 1",
                (session_id, row_id),
            )
            self._refresh_counts(session_id)
            self._conn.commit()
            return cursor.rowcount

    # ── search ───────────────────────────────────────────────────────────────────────────

    def search_messages(
        self,
        query: str,
        *,
        limit: int = 20,
        session_id: str | None = None,
        exclude_session_ids: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        """Full-text search across every stored message, newest first."""
        query = query.strip()
        if not query:
            return []
        filters, params = [], []
        if session_id:
            filters.append("m.session_id = ?")
            params.append(session_id)
        if exclude_session_ids:
            filters.append(f"m.session_id NOT IN ({','.join('?' * len(exclude_session_ids))})")
            params.extend(exclude_session_ids)
        extra = (" AND " + " AND ".join(filters)) if filters else ""
        columns = ("m.id AS message_id, m.session_id, m.role, m.timestamp, m.tool_name, "
                   "s.title AS session_title, s.source AS session_source")
        with self._lock:
            if self.fts_enabled:
                try:
                    rows = self._conn.execute(
                        f"""SELECT {columns},
                                   snippet(messages_fts, 0, '>>', '<<', ' … ', 24) AS snippet
                            FROM messages_fts
                            JOIN messages m ON m.id = messages_fts.rowid
                            JOIN sessions s ON s.id = m.session_id
                            WHERE messages_fts MATCH ?{extra}
                            ORDER BY m.timestamp DESC LIMIT ?""",
                        (_fts_query(query), *params, limit),
                    ).fetchall()
                    return [dict(row) for row in rows]
                except sqlite3.OperationalError:
                    pass  # malformed FTS expression: fall through to LIKE
            like = "%" + _escape_like(query) + "%"
            rows = self._conn.execute(
                f"""SELECT {columns}, substr(m.content, 1, 200) AS snippet
                    FROM messages m JOIN sessions s ON s.id = m.session_id
                    WHERE m.content LIKE ? ESCAPE '\\'{extra}
                    ORDER BY m.timestamp DESC LIMIT ?""",
                (like, *params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_message_window(self, session_id: str, message_id: int, window: int = 5) -> list[dict[str, Any]]:
        """Messages around ``message_id`` in one session, archived rows included."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM messages WHERE session_id = ? AND id BETWEEN ? AND ? ORDER BY id""",
                (session_id, message_id - window, message_id + window),
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    # ── key/value ────────────────────────────────────────────────────────────────────────

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO state_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    content = row["content"]
    if row["content_is_json"] and content is not None:
        content = json.loads(content)
    message: dict[str, Any] = {"role": row["role"], "content": content, "_row_id": row["id"]}
    if row["tool_calls"]:
        message["tool_calls"] = json.loads(row["tool_calls"])
    if row["tool_call_id"]:
        message["tool_call_id"] = row["tool_call_id"]
    if row["tool_name"]:
        message["name"] = row["tool_name"]
    if row["reasoning"]:
        message["reasoning"] = row["reasoning"]
    if row["provider_data"]:
        message["provider_data"] = json.loads(row["provider_data"])
    if row["turn_context"]:
        message["turn_context"] = row["turn_context"]
    if row["finish_reason"]:
        message["finish_reason"] = row["finish_reason"]
    if row["is_summary"]:
        message["is_summary"] = True
    if row["display_kind"]:
        message["display_kind"] = row["display_kind"]
    message["timestamp"] = row["timestamp"]
    return message


def _fts_query(query: str) -> str:
    """Quote every term so user text can never be read as FTS5 syntax."""
    terms = [term.replace('"', '""') for term in query.split()]
    return " ".join(f'"{term}"' for term in terms if term)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
