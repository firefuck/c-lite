"""SQLite schema for sessions and messages, and how a database is brought up to it.

``SCHEMA_VERSION`` is bumped only when an existing database must be transformed; the
transform goes in :data:`MIGRATIONS`. New nullable columns are added through
``COLUMN_ADDITIONS`` and reconciled on open, so old databases gain them without a migration.
:func:`prepare_schema` applies all of it every time a database is opened.
"""

from __future__ import annotations

import json
import sqlite3

from clite.state.search import search_text_of

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    session_key TEXT,
    user_id TEXT,
    chat_id TEXT,
    chat_type TEXT,
    thread_id TEXT,
    display_name TEXT,
    origin_json TEXT,
    model TEXT,
    provider TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT REFERENCES sessions(id),
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    last_activity_at REAL,
    message_count INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    api_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL,
    cwd TEXT,
    title TEXT,
    title_source TEXT,
    profile_name TEXT,
    compression_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    content_is_json INTEGER NOT NULL DEFAULT 0,
    -- Plain text of this message, the only column FTS indexes. A message whose content is a
    -- JSON list of parts (a user message with an image) keeps its base64 in `content`; this
    -- column holds just the words, so a search index never carries megabytes of image data.
    search_text TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    provider_data TEXT,
    turn_context TEXT,
    display_kind TEXT,
    is_summary INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    compacted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS state_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_key ON sessions(session_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique ON sessions(title) WHERE title IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_session_active ON messages(session_id, active, id);
"""

# External-content FTS5 over the searchable text, kept in sync by triggers. The indexed column
# is `search_text`, not `content`: a user message with an image stores its base64 in `content`,
# and indexing that would make the FTS index as large as the picture.
FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    search_text, tool_name, tool_calls,
    content='messages', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, search_text, tool_name, tool_calls)
    VALUES (new.id, new.search_text, new.tool_name, new.tool_calls);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, search_text, tool_name, tool_calls)
    VALUES ('delete', old.id, old.search_text, old.tool_name, old.tool_calls);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE OF search_text, tool_name, tool_calls ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, search_text, tool_name, tool_calls)
    VALUES ('delete', old.id, old.search_text, old.tool_name, old.tool_calls);
    INSERT INTO messages_fts(rowid, search_text, tool_name, tool_calls)
    VALUES (new.id, new.search_text, new.tool_name, new.tool_calls);
END;
"""

# {table: {column: "SQL type and default"}} for columns added after the first release.
# `turn_context` is listed although the schema above has it: databases created before it was
# added gain it here. `search_text` is listed for the same reason: reconciled on open, then
# backfilled by the 1 -> 2 migration.
COLUMN_ADDITIONS: dict[str, dict[str, str]] = {
    "messages": {"turn_context": "TEXT", "search_text": "TEXT"},
}

# {from_version: [sql, ...]} run in order to reach SCHEMA_VERSION.
# 1 -> 2: FTS moved from `content` to `search_text`, so a database written before image
# attachments does not index image base64. `search_text` itself is added by COLUMN_ADDITIONS
# (idempotent, safe when the column is already there). The old FTS table and its triggers are
# dropped here (FTS_SQL recreates them against `search_text` after the migrations run), the
# plain text of every existing row is copied over, and the index is rebuilt from the external
# content by `prepare_schema`.
MIGRATIONS: dict[int, list[str]] = {
    1: [
        "UPDATE messages SET search_text = content WHERE content_is_json = 0 AND search_text IS NULL",
        "DROP TRIGGER IF EXISTS messages_fts_insert",
        "DROP TRIGGER IF EXISTS messages_fts_delete",
        "DROP TRIGGER IF EXISTS messages_fts_update",
        "DROP TABLE IF EXISTS messages_fts",
    ],
}

# Columns callers may set through SessionDB.update_session.
UPDATABLE_SESSION_COLUMNS = frozenset(
    {
        "model",
        "provider",
        "model_config",
        "system_prompt",
        "cwd",
        "title",
        "title_source",
        "display_name",
        "ended_at",
        "end_reason",
        "last_activity_at",
        "archived",
        "pinned",
        "hidden",
        "session_key",
        "compression_count",
        "parent_session_id",
    }
)


def prepare_schema(conn: sqlite3.Connection) -> bool:
    """Create the schema on ``conn``, or bring an older database up to it, and commit.

    Returns whether SQLite has FTS5; without it search falls back to ``LIKE``. ``conn`` must
    return :class:`sqlite3.Row` rows, and a caller that shares it between threads holds its
    lock throughout (``SessionDB`` does both).
    """
    conn.executescript(SCHEMA_SQL)
    _reconcile_columns(conn)
    migrated = _run_migrations(conn)
    if migrated:
        _backfill_search_text(conn)
    try:
        conn.executescript(FTS_SQL)
        fts_enabled = True
        if migrated:
            # A migration that dropped the FTS table left it empty; external-content
            # FTS only repopulates from its triggers or an explicit rebuild.
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
    except sqlite3.OperationalError:
        # SQLite built without FTS5: search falls back to LIKE.
        fts_enabled = False
    conn.commit()
    return fts_enabled


def _reconcile_columns(conn: sqlite3.Connection) -> None:
    for table, columns in COLUMN_ADDITIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _run_migrations(conn: sqlite3.Connection) -> bool:
    """Run pending migrations. Returns True when the schema was transformed."""
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        return False
    version = int(row["version"])
    migrated = False
    while version < SCHEMA_VERSION:
        for statement in MIGRATIONS.get(version, []):
            conn.execute(statement)
        version += 1
        migrated = True
        conn.execute("UPDATE schema_version SET version = ?", (version,))
    return migrated


def _backfill_search_text(conn: sqlite3.Connection) -> None:
    """Fill ``search_text`` for rows a migration left NULL.

    The migration handles plain-string content in SQL. A row whose content is a JSON list
    takes more than SQL to interpret, so it is done here: the parts' text, if any. Rows
    that had no text stay NULL and are simply not indexed.
    """
    rows = conn.execute(
        "SELECT id, content FROM messages WHERE search_text IS NULL AND content IS NOT NULL"
    ).fetchall()
    for row in rows:
        raw = row["content"]
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = raw
        conn.execute("UPDATE messages SET search_text = ? WHERE id = ?", (search_text_of(parsed), row["id"]))
