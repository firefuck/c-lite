"""File checkpoints: capture before ``write_file``/``patch``, and rollback with ``/rollback``.

The tests drive the public door: the file tools through ``handle_function_call`` (so the
turn grouping, the guards and the registry are all exercised) and the commands through a real
``ChatSession``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from clite.core.config import load_config
from clite.core.constants import get_checkpoints_dir
from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.runtime import ChatSession
from clite.state.db import get_session_db
from clite.tools.checkpoints import (
    list_checkpoints,
    prune_checkpoints,
    record_change,
    rollback,
    session_dir,
    total_size,
)
from clite.tools.context import ToolContext
from clite.tools.dispatch import handle_function_call


class FakeAgent:
    """The smallest thing the turn counter needs: a growing conversation."""

    def __init__(self) -> None:
        self.messages: list[dict] = [{"role": "user", "content": "start"}]

    def begin_turn(self, text: str = "next turn") -> None:
        self.messages.append({"role": "user", "content": text})


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture(autouse=True)
def builtin_tools_registered():
    """Make sure ``write_file``/``patch`` are in the registry the public door dispatches through."""
    from clite.tools.registry import discover_builtin_tools

    discover_builtin_tools()
    yield


@pytest.fixture
def ctx(workspace):
    return ToolContext(session_id="session-1", task_id="task-1", cwd=str(workspace), agent=FakeAgent())


def _call(name: str, args: dict, ctx: ToolContext) -> dict:
    return json.loads(handle_function_call(name, args, ctx))


# ── the whole point: one turn, three edits, one rollback ────────────────────────────────────


def test_a_write_a_patch_and_a_creation_in_one_turn_are_all_undone_by_one_rollback(ctx, workspace):
    (workspace / "edited.txt").write_text("original\n")
    (workspace / "patched.txt").write_text("value = 1\n")

    assert _call("write_file", {"path": "edited.txt", "content": "changed\n"}, ctx)["created"] is False
    patched = _call(
        "patch", {"path": "patched.txt", "old_string": "value = 1", "new_string": "value = 2"}, ctx
    )
    assert patched["replacements"] == 1
    assert _call("write_file", {"path": "created.txt", "content": "brand new\n"}, ctx)["created"] is True

    result = rollback("session-1", turns=1)

    assert (workspace / "edited.txt").read_text() == "original\n"
    assert (workspace / "patched.txt").read_text() == "value = 1\n"
    assert not (workspace / "created.txt").exists()
    assert sorted(Path(path).name for path in result.restored) == ["edited.txt", "patched.txt"]
    assert [Path(path).name for path in result.removed] == ["created.txt"]


def test_a_delete_from_a_multi_file_patch_is_restored_by_rollback(ctx, workspace):
    victim = workspace / "gone.txt"
    victim.write_text("bring me back\n")
    patch = "*** Update File: kept.txt\n@@ @@\n-old\n+new\n*** Delete File: gone.txt\n"
    (workspace / "kept.txt").write_text("old\n")
    applied = _call("patch", {"mode": "patch", "patch": patch}, ctx)
    assert applied["count"] == 2 and not victim.exists()

    rollback("session-1", turns=1)
    assert victim.read_text() == "bring me back\n"
    assert (workspace / "kept.txt").read_text() == "old\n"


def test_rollback_moves_back_one_turn_at_a_time(ctx, workspace):
    (workspace / "f.txt").write_text("v0\n")
    _call("write_file", {"path": "f.txt", "content": "v1\n"}, ctx)
    ctx.agent.begin_turn()
    _call("write_file", {"path": "f.txt", "content": "v2\n"}, ctx)

    assert len(list_checkpoints("session-1")) == 2
    rollback("session-1", turns=1)
    assert (workspace / "f.txt").read_text() == "v1\n"
    rollback("session-1", turns=1)
    assert (workspace / "f.txt").read_text() == "v0\n"
    # Nothing left: a further rollback changes nothing and says so.
    assert rollback("session-1", turns=1).empty
    assert (workspace / "f.txt").read_text() == "v0\n"


def test_rollback_of_several_turns_restores_the_oldest_saved_state(ctx, workspace):
    (workspace / "f.txt").write_text("v0\n")
    _call("write_file", {"path": "f.txt", "content": "v1\n"}, ctx)
    ctx.agent.begin_turn()
    _call("write_file", {"path": "f.txt", "content": "v2\n"}, ctx)

    result = rollback("session-1", turns=2)
    assert result.empty is False
    assert (workspace / "f.txt").read_text() == "v0\n"
    assert list_checkpoints("session-1") == []


def test_the_turn_counter_counts_only_real_user_messages(ctx, workspace):
    """Agent-written (internal) user messages are not turns, so a continue/steer does not
    split a turn's checkpoints in two."""
    ctx.agent.messages.append({"role": "user", "content": "wrap up", "display_kind": "internal"})
    (workspace / "f.txt").write_text("before\n")
    _call("write_file", {"path": "f.txt", "content": "after\n"}, ctx)
    groups = list_checkpoints("session-1")
    assert len(groups) == 1 and groups[0].turn == 1


def test_the_turn_number_does_not_reuse_an_old_group_after_the_message_count_drops(ctx, workspace):
    """Compression and undo shrink the conversation; a later turn must still get a fresh group,
    not reopen the group of the turn it now numerically equals."""
    (workspace / "f.txt").write_text("v0\n")
    _call("write_file", {"path": "f.txt", "content": "v1\n"}, ctx)  # turn 1
    ctx.agent.begin_turn()
    _call("write_file", {"path": "f.txt", "content": "v2\n"}, ctx)  # turn 2
    # Compression removed the first user message: the count is back to what turn 1 saw.
    ctx.agent.messages = [{"role": "user", "content": "resumed"}]
    _call("write_file", {"path": "f.txt", "content": "v3\n"}, ctx)

    turns = [group.turn for group in list_checkpoints("session-1")]
    assert turns == [1, 2, 3]
    rollback("session-1", turns=1)
    assert (workspace / "f.txt").read_text() == "v2\n"


# ── the guard: a denied read is never stored ────────────────────────────────────────────────


def test_a_checkpoint_never_stores_a_file_the_read_tools_refuse(ctx, clite_home, workspace):
    secret = clite_home / ".env"
    secret.write_text("OPENROUTER_API_KEY=correct-horse-battery-staple\n")
    # The write itself is refused first; even if it were not, the store must not hold it.
    assert "Refused" in _call("write_file", {"path": str(secret), "content": "x"}, ctx)["error"]

    # A refused path recorded directly is dropped as well: nothing lands on disk.
    assert record_change("session-1", str(secret), before=secret.read_text(), existed=True, turn=1) is None

    store = session_dir("session-1")
    leaked = (
        [path for path in store.rglob("*") if "correct-horse" in path.read_text(errors="ignore")]
        if store.is_dir()
        else []
    )
    assert leaked == []
    assert list_checkpoints("session-1") == []


def test_a_readable_file_in_the_home_is_checkpointed_normally(ctx, clite_home, workspace):
    """Only credential files are refused; an ordinary file anywhere is still saved."""
    note = clite_home / "notes.md"
    note.write_text("keep me\n")
    assert record_change("session-1", str(note), before="keep me\n", existed=True, turn=1) is not None
    note.write_text("edited\n")
    rollback("session-1", turns=1)
    assert note.read_text() == "keep me\n"


# ── size and pruning ────────────────────────────────────────────────────────────────────────


def test_pruning_removes_the_checkpoints_of_a_pruned_session(ctx, workspace):
    """The session database is the source of truth: a store whose session is gone goes with it."""
    (workspace / "f.txt").write_text("before\n")
    _call("write_file", {"path": "f.txt", "content": "after\n"}, ctx)
    assert session_dir("session-1").is_dir()

    # Simulate the session having been pruned: no surviving id, so the store is dropped.
    prune_checkpoints(load_config(), session_ids=[])
    assert not session_dir("session-1").is_dir()


def test_pruning_keeps_the_store_of_a_session_that_still_exists(ctx, workspace):
    (workspace / "f.txt").write_text("before\n")
    _call("write_file", {"path": "f.txt", "content": "after\n"}, ctx)
    prune_checkpoints(load_config(), session_ids=["session-1"])
    assert session_dir("session-1").is_dir()
    assert len(list_checkpoints("session-1")) == 1


def test_pruning_drops_groups_older_than_retention_days(ctx, workspace):
    (workspace / "f.txt").write_text("before\n")
    _call("write_file", {"path": "f.txt", "content": "after\n"}, ctx)
    # Backdate the group past the 90-day window rather than sleeping.
    manifest = session_dir("session-1") / "turn-00001" / "manifest.json"
    data = json.loads(manifest.read_text())
    data["created_at"] = time.time() - 200 * 86400
    manifest.write_text(json.dumps(data))

    config = {**load_config(), "sessions": {"auto_prune": False, "retention_days": 90}}
    prune_checkpoints(config, now=time.time())
    assert not session_dir("session-1").is_dir()


def test_a_store_larger_than_the_cap_is_trimmed_oldest_first(ctx, workspace):
    for turn in range(1, 5):
        (workspace / "f.txt").write_text(f"v{turn}\n")
        record_change("session-1", str(workspace / "f.txt"), before=f"v{turn}\n", existed=True, turn=turn)
    assert total_size("session-1") > 0
    # A one-byte cap forces every group out; the oldest is deleted first.
    prune_checkpoints(load_config(), max_bytes=1)
    assert list_checkpoints("session-1") == []


def test_a_saved_file_is_bounded_so_a_huge_edit_does_not_double_the_cost(ctx, workspace):
    big = workspace / "big.txt"
    big.write_text("x" * 10)
    change = record_change("session-1", str(big), before="y" * 6_000_000, existed=True, turn=1)
    assert change is not None and change.saved is None
    assert change.skipped_reason and "larger than" in change.skipped_reason
    # The change is still recorded; rollback reports it as skipped instead of failing.
    result = rollback("session-1", turns=1)
    assert [Path(path).name for path, _reason in result.skipped] == ["big.txt"]


# ── the commands ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def make_session(clite_home, tmp_path):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    created = []

    def factory(workspace):
        client = ScriptedClient([], default=text_response("ok"))
        session = ChatSession(client=client, cwd=str(workspace))
        created.append(session)
        return session

    yield factory
    for session in created:
        session.close()


def test_the_rollback_command_undoes_the_last_turn(workspace, make_session):
    session = make_session(workspace)
    ctx = ToolContext(session_id=session.session_id, task_id=session.session_id, cwd=str(workspace))
    (workspace / "f.txt").write_text("before\n")
    _call("write_file", {"path": "f.txt", "content": "after\n"}, ctx)

    result = session.handle_input("/rollback")
    assert "Rolled back 1 turn" in result.text
    assert (workspace / "f.txt").read_text() == "before\n"


def test_the_rollback_command_takes_a_turn_count_and_rejects_junk(workspace, make_session):
    session = make_session(workspace)
    assert "Usage: /rollback" in session.handle_input("/rollback abc").text
    assert "turns must be 1 or more" in session.handle_input("/rollback 0").text


def test_the_checkpoints_command_lists_the_stored_groups(workspace, make_session):
    session = make_session(workspace)
    session.submit("go")  # one real turn, so the file change is grouped under turn 1
    ctx = ToolContext(
        session_id=session.session_id, task_id=session.session_id, cwd=str(workspace), agent=session.agent
    )
    _call("write_file", {"path": "made.txt", "content": "hello\n"}, ctx)

    text = session.handle_input("/checkpoints").text
    assert "turn 1" in text and "created" in text and "made.txt" in text


def test_the_commands_explain_the_terminal_boundary_when_there_is_nothing_to_roll_back(
    workspace, make_session
):
    session = make_session(workspace)
    text = session.handle_input("/rollback").text
    assert "No file checkpoints" in text and "terminal command" in text


def test_a_committed_turn_through_the_loop_is_rolled_back(workspace, make_session, clite_home):
    """End to end: the model calls write_file, and /rollback put the file back."""
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    (workspace / "app.py").write_text("print('original')\n")
    client = ScriptedClient(
        [
            tool_call_response(("write_file", {"path": "app.py", "content": "print('edited')\n"})),
            text_response("done"),
        ]
    )
    session = ChatSession(client=client, cwd=str(workspace))
    try:
        session.submit("rewrite app.py")
        assert (workspace / "app.py").read_text() == "print('edited')\n"
        result = session.handle_input("/rollback")
        assert "Rolled back 1 turn" in result.text
        assert (workspace / "app.py").read_text() == "print('original')\n"
    finally:
        session.close()


def test_startup_maintenance_prunes_the_store_of_a_deleted_session(workspace, make_session, clite_home):
    from clite.runtime.maintenance import prune_checkpoints as maintenance_prune
    from clite.runtime.maintenance import reset_maintenance_state

    reset_maintenance_state()
    session = make_session(workspace)
    ctx = ToolContext(session_id=session.session_id, task_id=session.session_id, cwd=str(workspace))
    _call("write_file", {"path": "f.txt", "content": "x\n"}, ctx)
    assert session_dir(session.session_id).is_dir()

    get_session_db().delete_session(session.session_id)
    maintenance_prune(load_config())
    assert not session_dir(session.session_id).is_dir()


def test_the_checkpoints_live_under_the_home_in_a_per_session_subdirectory(clite_home, workspace, ctx):
    (workspace / "f.txt").write_text("before\n")
    _call("write_file", {"path": "f.txt", "content": "after\n"}, ctx)
    assert get_checkpoints_dir() == clite_home / "checkpoints"
    assert session_dir("session-1").parent == clite_home / "checkpoints"
