"""SQLite schema for sessions and messages.

``SCHEMA_VERSION`` is bumped only when an existing database must be transformed; the
transform goes in :data:`MIGRATIONS`. New nullable columns are added through
``COLUMN_ADDITIONS`` and reconciled on open, so old databases gain them without a migration.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

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
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    provider_data TEXT,
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

# External-content FTS5 over the three searchable columns, kept in sync by triggers.
FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, tool_name, tool_calls,
    content='messages', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, tool_name, tool_calls)
    VALUES (new.id, new.content, new.tool_name, new.tool_calls);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, tool_name, tool_calls)
    VALUES ('delete', old.id, old.content, old.tool_name, old.tool_calls);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE OF content, tool_name, tool_calls ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, tool_name, tool_calls)
    VALUES ('delete', old.id, old.content, old.tool_name, old.tool_calls);
    INSERT INTO messages_fts(rowid, content, tool_name, tool_calls)
    VALUES (new.id, new.content, new.tool_name, new.tool_calls);
END;
"""

# {table: {column: "SQL type and default"}} for columns added after the first release.
COLUMN_ADDITIONS: dict[str, dict[str, str]] = {}

# {from_version: [sql, ...]} run in order to reach SCHEMA_VERSION.
MIGRATIONS: dict[int, list[str]] = {}

# Columns callers may set through SessionDB.update_session.
UPDATABLE_SESSION_COLUMNS = frozenset(
    {
        "model", "provider", "model_config", "system_prompt", "cwd", "title", "title_source",
        "display_name", "ended_at", "end_reason", "last_activity_at", "archived", "pinned",
        "hidden", "session_key", "compression_count", "parent_session_id",
    }
)
