"""SessionDB behaviour: durability, in-place compaction, search."""

from __future__ import annotations

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
    tool_call = {"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": '{"command": "ls"}'}}
    db.append_messages(
        sid,
        [
            {"role": "user", "content": "list files"},
            {"role": "assistant", "content": None, "tool_calls": [tool_call], "reasoning": "need ls",
             "provider_data": {"signature": "abc"}, "finish_reason": "tool_calls"},
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
    db.append_messages(sid, [{"role": "user", "content": "a"}, {"role": "tool", "content": "{}", "tool_call_id": "c"}])
    session = db.get_session(sid)
    assert session["message_count"] == 2
    assert session["tool_call_count"] == 1


def test_compaction_keeps_session_id_and_archives_old_rows(db):
    sid = _seed(db)
    db.append_messages(sid, [{"role": "user", "content": "the zebra question"}, {"role": "assistant", "content": "answer"}])
    db.replace_active_messages(sid, [{"role": "user", "content": "summary of earlier work", "is_summary": True}])

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
    db.append_messages(sid, [{"role": "user", "content": "deploy status?", "turn_context": "[recalled: deploys happen on Friday]"},
                             {"role": "assistant", "content": "On Friday."}])
    user, assistant = db.get_messages(sid)
    assert user["content"] == "deploy status?" and user["turn_context"] == "[recalled: deploys happen on Friday]"
    assert "turn_context" not in assistant
    assert db.search_messages("Friday")[0]["role"] == "assistant"  # recalled text is not searchable


def test_replay_data_can_be_cleared_without_touching_the_transcript(db):
    sid = _seed(db)
    other = _seed(db, "s2")
    for session in (sid, other):
        db.append_messages(session, [{"role": "user", "content": "hi"},
                                     {"role": "assistant", "content": "hello", "provider_data": {"signature": "abc"}}])
    assert db.clear_provider_data(sid) == 1
    assert db.clear_provider_data(sid) == 0
    assert [(m["content"], "provider_data" in m) for m in db.get_messages(sid)] == [("hi", False), ("hello", False)]
    assert "provider_data" in db.get_messages(other)[1]  # another session keeps its own


def test_a_database_from_before_a_column_existed_gains_it_on_open(clite_home):
    import sqlite3

    from clite.state.schema import SCHEMA_SQL

    path = clite_home / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_SQL.replace("    turn_context TEXT,\n", ""))
    connection.execute("INSERT INTO schema_version(version) VALUES (1)")
    connection.execute("INSERT INTO sessions(id, source, started_at) VALUES ('old', 'cli', 1)")
    connection.execute("INSERT INTO messages(session_id, role, content, timestamp) VALUES ('old', 'user', 'kept', 1)")
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
    db.append_message("old", {"role": "user", "content": "forgettable"})  # (this counts as activity, so age afterwards)
    for sid, age_days in ages.items():
        db._conn.execute("UPDATE sessions SET started_at = ?, last_activity_at = ? WHERE id = ?",
                         (now - age_days * day, now - age_days * day, sid))
    # A session that never recorded activity is judged by when it started.
    db.create_session("never-active", "cli")
    db._conn.execute("UPDATE sessions SET started_at = ?, last_activity_at = NULL WHERE id = 'never-active'", (now - 95 * day,))
    db.update_session("old-pinned", pinned=1)

    assert db.prune_sessions(90, keep=["old-kept"], dry_run=True, now=now) == 3
    assert db.get_session("old") is not None  # a dry run deletes nothing
    assert db.prune_sessions(90, keep=["old-kept"], now=now) == 3
    assert {row["id"] for row in db.list_sessions(include_children=True)} == {"fresh", "old-pinned", "old-kept"}
    assert db.search_messages("forgettable") == []
    assert db.prune_sessions(90, keep=["old-kept"], now=now) == 0
