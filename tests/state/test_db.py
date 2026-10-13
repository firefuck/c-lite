"""SessionDB behaviour: durability, in-place compaction, search."""

from __future__ import annotations

import time

import pytest

from clite.state import SessionDB, get_session_db
from clite.state.db import new_session_id


@pytest.fixture
def db(clite_home) -> SessionDB:
    return get_session_db()


def _seed(db: SessionDB, session_id: str = "s1", **kwargs) -> str:
    db.create_session(session_id, "cli", model="m", provider="p", **kwargs)
    return session_id


def test_database_lives_in_the_active_home(db, clite_home):
    assert db.path == clite_home / "state.db"
    assert db.path.exists()


def test_get_session_db_returns_one_instance_per_file(db):
    assert get_session_db() is db


def test_create_session_is_idempotent(db):
    assert db.create_session("s1", "cli", model="first") is True
    assert db.create_session("s1", "cli", model="second") is False
    assert db.get_session("s1")["model"] == "first"


def test_new_session_ids_are_unique_and_sortable():
    first, second = new_session_id(), new_session_id()
    assert first != second
    assert first[:8].isdigit()


def test_messages_round_trip_in_internal_shape(db):
    sid = _seed(db)
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "terminal", "arguments": '{"command": "ls"}'},
    }
    db.append_messages(
        sid,
        [
            {"role": "user", "content": "list files"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call],
                "reasoning": "need ls",
                "provider_data": {"signature": "abc"},
                "finish_reason": "tool_calls",
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "terminal", "content": '{"output": "a.txt"}'},
            {"role": "assistant", "content": "One file: a.txt"},
        ],
    )
    messages = db.get_messages(sid)
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
    assistant = messages[1]
    assert assistant["content"] is None
    assert assistant["tool_calls"] == [tool_call]
    assert assistant["reasoning"] == "need ls"
    assert assistant["provider_data"] == {"signature": "abc"}
    assert messages[2]["tool_call_id"] == "call_1"
    assert messages[2]["name"] == "terminal"


def test_structured_content_round_trips(db):
    sid = _seed(db)
    parts = [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:x"}}]
    db.append_message(sid, {"role": "user", "content": parts})
    assert db.get_messages(sid)[0]["content"] == parts


def test_counters_follow_appends(db):
    sid = _seed(db)
    db.append_messages(
        sid, [{"role": "user", "content": "a"}, {"role": "tool", "content": "{}", "tool_call_id": "c"}]
    )
    session = db.get_session(sid)
    assert session["message_count"] == 2
    assert session["tool_call_count"] == 1


def test_compaction_keeps_session_id_and_archives_old_rows(db):
    sid = _seed(db)
    db.append_messages(
        sid, [{"role": "user", "content": "the zebra question"}, {"role": "assistant", "content": "answer"}]
    )
    db.replace_active_messages(
        sid, [{"role": "user", "content": "summary of earlier work", "is_summary": True}]
    )

    active = db.get_messages(sid)
    assert [m["content"] for m in active] == ["summary of earlier work"]
    assert active[0]["is_summary"] is True
    assert len(db.get_messages(sid, include_inactive=True)) == 3
    assert db.get_session(sid)["compression_count"] == 1
    # Archived rows stay searchable under the same session id.
    assert [hit["session_id"] for hit in db.search_messages("zebra")] == [sid]


def test_deactivate_from_rewinds_the_active_transcript(db):
    sid = _seed(db)
    ids = db.append_messages(sid, [{"role": "user", "content": f"m{i}"} for i in range(4)])
    assert db.deactivate_from(sid, ids[2]) == 2
    assert [m["content"] for m in db.get_messages(sid)] == ["m0", "m1"]
    assert db.count_messages(sid) == 2


def test_search_treats_operators_as_plain_text(db):
    sid = _seed(db)
    db.append_message(sid, {"role": "user", "content": 'deploy "blue-green" AND rollback NOT now'})
    for query in ('"blue-green"', "AND", "rollback NOT", "deploy*", "col:on (paren"):
        db.search_messages(query)  # must not raise on FTS syntax
    assert db.search_messages("rollback")[0]["session_id"] == sid


def test_search_can_scope_and_exclude_sessions(db):
    _seed(db, "s1")
    _seed(db, "s2")
    db.append_message("s1", {"role": "user", "content": "shared needle"})
    db.append_message("s2", {"role": "user", "content": "shared needle"})
    assert {hit["session_id"] for hit in db.search_messages("needle")} == {"s1", "s2"}
    assert {hit["session_id"] for hit in db.search_messages("needle", session_id="s2")} == {"s2"}
    assert {hit["session_id"] for hit in db.search_messages("needle", exclude_session_ids=["s2"])} == {"s1"}


def test_search_falls_back_to_like_without_fts(db):
    sid = _seed(db)
    db.append_message(sid, {"role": "user", "content": "50% done_now"})
    db.fts_enabled = False
    assert db.search_messages("50% done_now")[0]["session_id"] == sid
    assert db.search_messages("5_% d") == []  # LIKE wildcards in the query are literal


def _image_message(caption: str, payload: str = "QUJDREVG") -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": caption},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{payload}"}},
        ],
    }


def test_an_image_message_round_trips_with_its_parts_intact(db):
    sid = _seed(db)
    db.append_message(sid, _image_message("a chart of sales"))
    stored = db.get_messages(sid)[0]["content"]
    assert stored[0] == {"type": "text", "text": "a chart of sales"}
    assert stored[1]["image_url"]["url"] == "data:image/png;base64,QUJDREVG"


def test_an_image_is_searchable_by_its_caption(db):
    sid = _seed(db)
    db.append_message(sid, _image_message("a photo of a zebra"))
    hits = db.search_messages("zebra")
    assert [hit["session_id"] for hit in hits] == [sid]
    assert "zebra" in hits[0]["snippet"]


def test_the_search_index_does_not_carry_image_base64(db):
    """The image lives in ``content``; the FTS index (and the LIKE fallback) hold only the
    caption. Indexing the base64 would make the index as large as the picture."""
    sid = _seed(db)
    payload = "A" * 200_000
    db.append_message(sid, _image_message("tiny caption", payload))

    # The huge payload is nowhere in the indexed text.
    assert db.search_messages("A" * 50) == []
    stored_text = db.get_messages(sid)[0]["content"]
    assert len(str(stored_text)) > 200_000  # the picture is stored, just not indexed

    with db._lock:
        indexed = db._conn.execute("SELECT search_text FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert indexed["search_text"] == "tiny caption"


def test_a_legacy_database_gains_the_search_text_column_and_stays_searchable(clite_home):
    """A database written before image attachments (schema version 1) keeps its search."""
    import sqlite3

    path = clite_home / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL,
            session_key TEXT, title TEXT, parent_session_id TEXT, last_activity_at REAL,
            message_count INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT,
            content_is_json INTEGER NOT NULL DEFAULT 0, tool_call_id TEXT, tool_calls TEXT,
            tool_name TEXT, timestamp REAL NOT NULL, token_count INTEGER, finish_reason TEXT,
            reasoning TEXT, provider_data TEXT, turn_context TEXT, display_kind TEXT,
            is_summary INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
            compacted INTEGER NOT NULL DEFAULT 0);
        """
    )
    connection.execute("INSERT INTO schema_version(version) VALUES (1)")
    connection.execute("INSERT INTO sessions(id, source, started_at) VALUES ('old', 'cli', 1)")
    connection.execute(
        "INSERT INTO messages(session_id, role, content, timestamp) VALUES ('old', 'user', 'an old zebra note', 1)"
    )
    connection.commit()
    connection.close()

    upgraded = SessionDB(path)
    try:
        assert upgraded.search_messages("zebra")[0]["session_id"] == "old"
    finally:
        upgraded.close()


def test_a_legacy_database_that_already_has_search_text_is_not_broken(clite_home):
    """The column is reconciled on open, so a database that already has it still opens."""
    import sqlite3

    from clite.state.schema import SCHEMA_SQL

    path = clite_home / "halfway.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_SQL)
    connection.execute("INSERT INTO schema_version(version) VALUES (1)")
    connection.execute("INSERT INTO sessions(id, source, started_at) VALUES ('h', 'cli', 1)")
    connection.execute(
        "INSERT INTO messages(session_id, role, content, search_text, timestamp) "
        "VALUES ('h', 'user', 'kept', 'kept', 1)"
    )
    connection.commit()
    connection.close()

    upgraded = SessionDB(path)
    try:
        assert upgraded.search_messages("kept")[0]["session_id"] == "h"
    finally:
        upgraded.close()


def test_a_legacy_database_with_structured_content_backfills_its_text(clite_home):
    """A version-1 database could already hold a JSON content list; migration keeps the words
    searchable and still leaves the image out of the index."""
    import json as jsonlib
    import sqlite3

    path = clite_home / "structured.db"
    structured = [
        {"type": "text", "text": "an old zebra note"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "B" * 5000}},
    ]
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL,
            session_key TEXT, title TEXT, parent_session_id TEXT, last_activity_at REAL,
            message_count INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT,
            content_is_json INTEGER NOT NULL DEFAULT 0, tool_call_id TEXT, tool_calls TEXT,
            tool_name TEXT, timestamp REAL NOT NULL, token_count INTEGER, finish_reason TEXT,
            reasoning TEXT, provider_data TEXT, turn_context TEXT, display_kind TEXT,
            is_summary INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
            compacted INTEGER NOT NULL DEFAULT 0);
        """
    )
    connection.execute("INSERT INTO schema_version(version) VALUES (1)")
    connection.execute("INSERT INTO sessions(id, source, started_at) VALUES ('s', 'cli', 1)")
    connection.execute(
        "INSERT INTO messages(session_id, role, content, content_is_json, timestamp) VALUES (?, 'user', ?, 1, 1)",
        ("s", jsonlib.dumps(structured)),
    )
    connection.commit()
    connection.close()

    upgraded = SessionDB(path)
    try:
        assert upgraded.search_messages("zebra")[0]["session_id"] == "s"
        with upgraded._lock:
            text = upgraded._conn.execute(
                "SELECT search_text FROM messages WHERE session_id = 's'"
            ).fetchone()["search_text"]
        assert text == "an old zebra note" and "B" * 50 not in text
    finally:
        upgraded.close()


def test_titles_are_unique(db):
    _seed(db, "s1")
    _seed(db, "s2")
    assert db.set_title("s1", "Refactor  auth") == "Refactor auth"
    assert db.set_title("s2", "Refactor auth") == "Refactor auth #2"
    assert db.set_title("s1", "Refactor auth") == "Refactor auth"  # renaming to itself is not a clash
    with pytest.raises(ValueError):
        db.set_title("s1", "   ")


def test_find_session_by_id_title_or_unique_prefix(db):
    _seed(db, "20260101_000000_aaaa1111", title="Alpha")
    _seed(db, "20260102_000000_bbbb2222")
    assert db.find_session("20260101_000000_aaaa1111")["title"] == "Alpha"
    assert db.find_session("Alpha")["id"] == "20260101_000000_aaaa1111"
    assert db.find_session("20260102")["id"] == "20260102_000000_bbbb2222"
    assert db.find_session("2026") is None  # ambiguous prefix
    assert db.find_session("") is None


def test_list_sessions_hides_children_hidden_and_archived_by_default(db):
    _seed(db, "parent")
    db.create_session("child", "cli", parent_session_id="parent")
    db.create_session("hidden", "cli", hidden=True)
    _seed(db, "archived")
    db.update_session("archived", archived=1)
    assert [s["id"] for s in db.list_sessions()] == ["parent"]
    everything = db.list_sessions(include_hidden=True, include_archived=True, include_children=True)
    assert {s["id"] for s in everything} == {"parent", "child", "hidden", "archived"}
    assert [s["id"] for s in db.list_sessions(sources=["telegram"])] == []


def test_update_session_rejects_unknown_columns(db):
    _seed(db)
    with pytest.raises(ValueError):
        db.update_session("s1", id="other")


def test_usage_accumulates(db):
    sid = _seed(db)
    db.add_usage(sid, input_tokens=10, output_tokens=5, api_calls=1, cost_usd=0.01)
    db.add_usage(sid, input_tokens=7, cache_read_tokens=3, api_calls=1)
    session = db.get_session(sid)
    assert (session["input_tokens"], session["output_tokens"], session["cache_read_tokens"]) == (17, 5, 3)
    assert session["api_call_count"] == 2
    assert session["estimated_cost_usd"] == pytest.approx(0.01)


def test_turn_context_is_stored_beside_the_message_not_in_it(db):
    sid = _seed(db)
    db.append_messages(
        sid,
        [
            {
                "role": "user",
                "content": "deploy status?",
                "turn_context": "[recalled: deploys happen on Friday]",
            },
            {"role": "assistant", "content": "On Friday."},
        ],
    )
    user, assistant = db.get_messages(sid)
    assert (
        user["content"] == "deploy status?" and user["turn_context"] == "[recalled: deploys happen on Friday]"
    )
    assert "turn_context" not in assistant
    assert db.search_messages("Friday")[0]["role"] == "assistant"  # recalled text is not searchable


def test_replay_data_can_be_cleared_without_touching_the_transcript(db):
    sid = _seed(db)
    other = _seed(db, "s2")
    for session in (sid, other):
        db.append_messages(
            session,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello", "provider_data": {"signature": "abc"}},
            ],
        )
    assert db.clear_provider_data(sid) == 1
    assert db.clear_provider_data(sid) == 0
    assert [(m["content"], "provider_data" in m) for m in db.get_messages(sid)] == [
        ("hi", False),
        ("hello", False),
    ]
    assert "provider_data" in db.get_messages(other)[1]  # another session keeps its own


def test_a_database_from_before_a_column_existed_gains_it_on_open(clite_home):
    import sqlite3

    from clite.state.schema import SCHEMA_SQL

    path = clite_home / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_SQL.replace("    turn_context TEXT,\n", ""))
    connection.execute("INSERT INTO schema_version(version) VALUES (1)")
    connection.execute("INSERT INTO sessions(id, source, started_at) VALUES ('old', 'cli', 1)")
    connection.execute(
        "INSERT INTO messages(session_id, role, content, timestamp) VALUES ('old', 'user', 'kept', 1)"
    )
    connection.commit()
    connection.close()

    upgraded = SessionDB(path)
    try:
        assert upgraded.get_messages("old")[0]["content"] == "kept"
        upgraded.append_message("old", {"role": "user", "content": "new", "turn_context": "note"})
        assert upgraded.get_messages("old")[1]["turn_context"] == "note"
    finally:
        upgraded.close()


def test_delete_session_removes_messages_and_orphans_children(db):
    _seed(db, "parent")
    db.create_session("child", "cli", parent_session_id="parent")
    db.append_message("parent", {"role": "user", "content": "gone soon"})
    assert db.delete_session("parent") is True
    assert db.get_session("parent") is None
    assert db.search_messages("gone") == []
    assert db.get_session("child")["parent_session_id"] is None
    assert db.delete_session("parent") is False


def test_message_window_includes_archived_rows(db):
    sid = _seed(db)
    ids = db.append_messages(sid, [{"role": "user", "content": f"m{i}"} for i in range(6)])
    db.replace_active_messages(sid, [{"role": "user", "content": "summary"}])
    window = db.get_message_window(sid, ids[2], window=1)
    assert [m["content"] for m in window] == ["m1", "m2", "m3"]


def test_meta_round_trip(db):
    assert db.get_meta("k") is None
    assert db.get_meta("k", "fallback") == "fallback"
    db.set_meta("k", "v1")
    db.set_meta("k", "v2")
    assert db.get_meta("k") == "v2"


def test_reopening_preserves_data(db, clite_home):
    sid = _seed(db)
    db.append_message(sid, {"role": "user", "content": "persisted"})
    db.close()
    reopened = get_session_db()
    assert reopened is not db
    assert reopened.get_messages(sid)[0]["content"] == "persisted"


def test_prune_deletes_only_old_unpinned_sessions(db):
    day = 86400.0
    now = 1_000 * day
    ages = {"fresh": 1, "old": 100, "old-pinned": 100, "old-kept": 100, "old-child": 200}
    for sid in ages:
        db.create_session(sid, "cli", parent_session_id="old" if sid == "old-child" else None)
    db.append_message(
        "old", {"role": "user", "content": "forgettable"}
    )  # (this counts as activity, so age afterwards)
    for sid, age_days in ages.items():
        db._conn.execute(
            "UPDATE sessions SET started_at = ?, last_activity_at = ? WHERE id = ?",
            (now - age_days * day, now - age_days * day, sid),
        )
    # A session that never recorded activity is judged by when it started.
    db.create_session("never-active", "cli")
    db._conn.execute(
        "UPDATE sessions SET started_at = ?, last_activity_at = NULL WHERE id = 'never-active'",
        (now - 95 * day,),
    )
    db.update_session("old-pinned", pinned=1)

    assert db.prune_sessions(90, keep=["old-kept"], dry_run=True, now=now) == 3
    assert db.get_session("old") is not None  # a dry run deletes nothing
    assert db.prune_sessions(90, keep=["old-kept"], now=now) == 3
    assert {row["id"] for row in db.list_sessions(include_children=True)} == {
        "fresh",
        "old-pinned",
        "old-kept",
    }
    assert db.search_messages("forgettable") == []
    assert db.prune_sessions(90, keep=["old-kept"], now=now) == 0


def test_get_insights_aggregates_and_subagent_attribution(db):
    day = 86400.0
    now = time.time()

    # Session 1: Root, cli, claude-3-5, cost 0.05
    db.create_session("s1", "cli", model="claude-3-5", provider="anthropic")
    db.add_usage("s1", input_tokens=1000, output_tokens=500, api_calls=1)
    db._conn.execute(
        "UPDATE sessions SET estimated_cost_usd = 0.05, started_at = ? WHERE id = 's1'", (now - 1 * day,)
    )

    # Session 2: Root, telegram, gpt-4o, cost 0.03
    db.create_session("s2", "telegram", model="gpt-4o", provider="openai")
    db.add_usage("s2", input_tokens=2000, output_tokens=1000, api_calls=1)
    db._conn.execute(
        "UPDATE sessions SET estimated_cost_usd = 0.03, started_at = ? WHERE id = 's2'", (now - 2 * day,)
    )

    # Session 3: Child/subagent of s1, cli, claude-3-5, cost 0.02
    db.create_session("s3", "cli", model="claude-3-5", provider="anthropic", parent_session_id="s1")
    db.add_usage("s3", input_tokens=500, output_tokens=200, api_calls=1)
    db._conn.execute(
        "UPDATE sessions SET estimated_cost_usd = 0.02, started_at = ? WHERE id = 's3'", (now - 1 * day,)
    )

    # Session 4: Root, cli, custom-local, unpriced (estimated_cost_usd is NULL)
    db.create_session("s4", "cli", model="custom-local", provider="custom")
    db.add_usage("s4", input_tokens=300, output_tokens=100, api_calls=1)
    db._conn.execute(
        "UPDATE sessions SET estimated_cost_usd = NULL, started_at = ? WHERE id = 's4'", (now - 1 * day,)
    )

    # Add tool calls to messages
    for _ in range(3):
        db.append_message("s1", {"role": "tool", "name": "read_file", "tool_call_id": "c1", "content": "ok"})
    for _ in range(2):
        db.append_message("s2", {"role": "tool", "name": "terminal", "tool_call_id": "c2", "content": "ok"})

    # Query insights for past 7 days
    insights = db.get_insights(days=7)

    # Invariants verification:
    # 1. Subagent s3 is attributed to parent s1: total_sessions counts root sessions only (3), not 4.
    assert insights["total_sessions"] == 3
    assert insights["total_subagents"] == 1
    # 2. Platforms only count root sessions (cli: 2, telegram: 1)
    assert insights["platforms"] == {"cli": 2, "telegram": 1}

    # 3. Token totals match hand calculation:
    # input = 1000 + 2000 + 500 + 300 = 3800
    # output = 500 + 1000 + 200 + 100 = 1800
    assert insights["tokens"]["input"] == 3800
    assert insights["tokens"]["output"] == 1800
    assert insights["tokens"]["total"] == 5600

    # 4. Costs match hand calculation:
    # total_cost = 0.05 + 0.03 + 0.02 = 0.10
    # unpriced sessions = 1 (s4)
    assert abs(insights["cost"]["total_usd"] - 0.10) < 1e-5
    assert insights["cost"]["unpriced_sessions"] == 1
    assert insights["cost"]["has_unpriced"] is True

    # 5. Model breakdown matches hand calculation:
    models = {m["model"]: m for m in insights["models"]}
    assert models["claude-3-5"]["input_tokens"] == 1500
    assert models["claude-3-5"]["output_tokens"] == 700
    assert abs(models["claude-3-5"]["cost_usd"] - 0.07) < 1e-5

    assert models["gpt-4o"]["input_tokens"] == 2000
    assert models["gpt-4o"]["output_tokens"] == 1000
    assert abs(models["gpt-4o"]["cost_usd"] - 0.03) < 1e-5

    assert models["custom-local"]["unpriced_sessions"] == 1

    # 6. Tools counts match: read_file: 3, terminal: 2
    tools = {t["name"]: t["count"] for t in insights["tools"]}
    assert tools["read_file"] == 3
    assert tools["terminal"] == 2


def test_insights_attribute_subagents_to_their_parent_and_keep_unpriced_sessions_apart(db):
    db.create_session("root-cli", "cli", model="big")
    db.create_session("root-tg", "telegram", model="small")
    db.create_session("child", "cli", model="big", parent_session_id="root-cli")
    db.add_usage("root-cli", input_tokens=100, output_tokens=50, cost_usd=0.25)
    db.add_usage("child", input_tokens=10, output_tokens=5, cost_usd=0.05)
    db.add_usage("root-tg", input_tokens=7, output_tokens=3)  # no price known
    db.append_message("root-cli", {"role": "tool", "name": "terminal", "content": "ok", "tool_call_id": "c1"})
    db.append_message("root-cli", {"role": "tool", "name": "terminal", "content": "ok", "tool_call_id": "c2"})

    insights = db.get_insights(days=30)

    assert insights["platforms"] == {"cli": 1, "telegram": 1}  # the subagent is not a session of its own
    assert insights["total_sessions"] == 2 and insights["total_subagents"] == 1
    assert insights["tokens"]["total"] == 175
    assert insights["cost"] == {
        "total_usd": 0.3,
        "unpriced_sessions": 1,
        "priced_sessions": 2,
        "has_unpriced": True,
    }
    assert [(m["model"], m["total_tokens"], m["unpriced_sessions"]) for m in insights["models"]] == [
        ("big", 165, 0),
        ("small", 10, 1),
    ]
    assert insights["tools"] == [{"name": "terminal", "count": 2}]
    assert len(insights["daily"]) == 1 and insights["daily"][0]["sessions"] == 2
