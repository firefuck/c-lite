"""Background review and the scheduled curator.

Two pieces of self-improvement that must never get in a turn's way: an agent that reviews a
long turn afterwards and writes what it learned to memory or skills, and a curator that keeps
the skill library from growing without bound.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from clite.agent import AgentCallbacks
from clite.agent import review as review_module
from clite.agent.review import (
    ReviewOutcome,
    review_enabled,
    run_review,
    should_review,
    spawn_background_review,
)
from clite.agent.state import TurnState
from clite.core.constants import get_memories_dir
from clite.providers.testing import mock_route, text_response, tool_call_response
from clite.skills import curator
from clite.skills.catalog import discover_skills
from clite.skills.usage import load_usage, record_created

MEMORY_CALL = ("memory", {"action": "add", "target": "memory", "content": "The deploy host is gilead."})


def _state(user="deploy the service", *, task_id="task-1"):
    state = TurnState(user_message=user, route=mock_route(), task_id=task_id)
    state.completed = True
    return state


def _long_turn(agent, count=8):
    """Make ``agent.messages`` look like a finished turn that used ``count`` tool calls."""
    agent.ensure_session()
    agent.append_message({"role": "user", "content": "go", "timestamp": time.time()})
    for index in range(count):
        agent.append_message(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"c{index}",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": json.dumps({"path": f"f{index}"})},
                    }
                ],
            }
        )
        agent.append_message(
            {"role": "tool", "tool_call_id": f"c{index}", "name": "read_file", "content": "{}"}
        )
    agent.append_message({"role": "assistant", "content": "done"})


# ── gates ────────────────────────────────────────────────────────────────────────────────


def test_review_is_on_by_default_and_off_when_disabled(clite_home, make_agent):
    agent, _ = make_agent([])
    assert review_enabled(agent.config) is True
    (clite_home / "config.yaml").write_text("background_review:\n  enabled: false\n")
    from clite.core import config as config_module

    config_module.reset_config_cache()
    disabled, _ = make_agent([], config=config_module.load_config())
    assert review_enabled(disabled.config) is False


def test_a_short_turn_is_not_reviewed(make_agent):
    agent, _ = make_agent([])
    _long_turn(agent, count=1)
    assert should_review(agent, _state()) is False


def test_a_long_turn_is_reviewed(make_agent):
    agent, _ = make_agent([])
    _long_turn(agent, count=8)
    assert should_review(agent, _state()) is True


def test_a_subagent_turn_is_never_reviewed(make_agent):
    parent, _ = make_agent([])
    parent.ensure_session()
    child, _ = make_agent([], parent=parent)  # memory on: only the depth gate can stop it
    _long_turn(child, count=8)
    assert child.depth == 1 and child.memory is not None
    assert should_review(child, _state()) is False


def test_a_cron_turn_is_never_reviewed(make_agent):
    agent, _ = make_agent([], platform="cron")
    _long_turn(agent, count=8)
    assert should_review(agent, _state()) is False


def test_a_busy_session_is_not_reviewed(make_agent):
    agent, _ = make_agent([])
    _long_turn(agent, count=8)
    agent._turn_lock.acquire()  # simulate a turn still running
    try:
        assert agent.busy and should_review(agent, _state()) is False
    finally:
        agent._turn_lock.release()


def test_review_runs_at_most_once_per_interval(make_agent):
    agent, _ = make_agent([], session_id="sess-interval")
    _long_turn(agent, count=8)
    assert should_review(agent, _state()) is True
    review_module._mark_reviewed(agent.session_id)
    assert should_review(agent, _state()) is False


def test_a_different_session_has_its_own_interval(make_agent):
    one, _ = make_agent([], session_id="sess-a")
    two, _ = make_agent([], session_id="sess-b")
    _long_turn(one, count=8)
    _long_turn(two, count=8)
    review_module._mark_reviewed(one.session_id)
    assert should_review(one, _state()) is False  # throttled
    assert should_review(two, _state()) is True  # its own clock


# ── the review itself ────────────────────────────────────────────────────────────────────


def test_review_writes_one_memory_entry_and_leaves_the_main_session_untouched(make_agent):
    agent, client = make_agent(
        [tool_call_response(MEMORY_CALL), text_response("saved")],
        enabled_toolsets=["file", "memory", "skills"],
    )
    _long_turn(agent, count=8)
    history_before = list(agent.messages)
    prompt_before = agent.system_prompt

    outcome = run_review(agent, _state())

    assert isinstance(outcome, ReviewOutcome)
    assert outcome.actions == ["Memory updated"]
    assert outcome.error is None
    # The main transcript and the system prompt are byte-for-byte what they were.
    assert agent.messages == history_before
    assert agent.system_prompt == prompt_before


def test_review_writes_to_the_real_memory_store(make_agent, clite_home):
    agent, _ = make_agent(
        [tool_call_response(MEMORY_CALL), text_response("saved")], enabled_toolsets=["memory", "skills"]
    )
    _long_turn(agent, count=8)
    run_review(agent, _state())
    from clite.core.constants import get_memories_dir

    memory_file = get_memories_dir() / "MEMORY.md"
    assert memory_file.exists() and "gilead" in memory_file.read_text()


def test_the_reviewer_sees_only_the_turn_copy_as_its_input(make_agent):
    agent, client = make_agent(
        [tool_call_response(MEMORY_CALL), text_response("saved")], enabled_toolsets=["memory", "skills"]
    )
    _long_turn(agent, count=8)
    run_review(agent, _state())
    # The review's own first request: a system prompt and the turn copy as the user message.
    review_request = next(
        call["messages"]
        for call in client.calls
        if call["messages"][-1]["role"] == "user"
        and "reviewing a conversation turn" in call["messages"][-1]["content"]
    )
    assert review_request[0]["role"] == "system"
    assert "go" in review_request[-1]["content"]  # the turn copy, not the live transcript
    assert all(message.get("role") != "tool" for message in review_request)


def test_the_review_toolset_is_narrow(make_agent):
    agent, client = make_agent(
        [tool_call_response(MEMORY_CALL), text_response("saved")],
        enabled_toolsets=["file", "terminal", "memory", "skills"],
    )
    _long_turn(agent, count=8)
    run_review(agent, _state())
    offered = {tool["function"]["name"] for tool in (client.calls[-1]["tools"] or [])}
    assert offered == {"memory", "skills_list", "skill_view", "skill_manage"}


def test_the_review_has_its_own_small_budget(make_agent, clite_home):
    """The reviewer stops after its own few turns and never touches the session's budget."""
    (clite_home / "config.yaml").write_text("background_review:\n  max_turns: 1\n")
    from clite.core import config as config_module

    config_module.reset_config_cache()
    loop_forever = tool_call_response(("memory", {"action": "add", "target": "memory", "content": "x"}))
    agent, client = make_agent(
        [loop_forever, loop_forever, text_response("wrapped up")],
        enabled_toolsets=["memory", "skills"],
        config=config_module.load_config(),
    )
    _long_turn(agent, count=8)
    before = len(client.calls)

    run_review(agent, _state())

    # With max_turns=1 the reviewer gets one tool round plus a single tool-less wrap-up.
    assert len(client.calls) - before <= 2
    assert agent.budget.limit is None  # the session's own budget is untouched


def test_a_failing_review_does_not_break_the_next_turn(make_agent):
    agent, client = make_agent([RuntimeError("provider exploded")], enabled_toolsets=["memory", "skills"])
    _long_turn(agent, count=8)
    outcome = run_review(agent, _state())
    assert outcome.error and "exploded" in outcome.error
    assert outcome.actions == []
    # The session still works: a fresh turn answers normally.
    client.queue(text_response("still fine"))
    result = agent.run_conversation("are you ok?")
    assert result.final_response == "still fine"


def test_a_timed_out_review_does_not_break_the_next_turn(make_agent):
    agent, client = make_agent([], enabled_toolsets=["memory", "skills"])
    _long_turn(agent, count=8)

    def slow(**kwargs):
        time.sleep(5)
        return text_response("late")

    client.queue(slow)
    outcome = run_review(agent, _state(), timeout=0.2)
    assert outcome.error and "timed out" in outcome.error.lower()
    client.queue(text_response("next turn"))
    assert agent.run_conversation("hello").final_response == "next turn"


def test_spawn_review_runs_in_the_background_and_reports_a_status_line(make_agent):
    events = []
    agent, _ = make_agent(
        [tool_call_response(MEMORY_CALL), text_response("saved")],
        enabled_toolsets=["memory", "skills"],
        callbacks=AgentCallbacks(on_status=lambda kind, text: events.append((kind, text))),
    )
    _long_turn(agent, count=8)
    thread = spawn_background_review(agent, _state())
    assert isinstance(thread, threading.Thread)
    thread.join(10)
    assert not thread.is_alive()
    kinds = [kind for kind, _ in events]
    assert "review" in kinds
    assert any("Memory updated" in text for kind, text in events if kind == "review")


def test_a_review_that_learns_nothing_says_so(make_agent):
    agent, _ = make_agent([text_response("Nothing to save.")], enabled_toolsets=["memory", "skills"])
    _long_turn(agent, count=8)
    outcome = run_review(agent, _state())
    assert outcome.actions == []
    assert outcome.summary == "nothing to save"


def test_a_review_that_writes_a_skill_reports_it(make_agent):
    skill_body = (
        "---\nname: deploy-notes\ndescription: how the deploy host is reached\n---\n\n1. ssh gilead\n"
    )
    agent, _ = make_agent(
        [
            tool_call_response(
                ("skill_manage", {"action": "create", "name": "deploy-notes", "content": skill_body})
            ),
            text_response("saved"),
        ],
        enabled_toolsets=["memory", "skills"],
    )
    _long_turn(agent, count=8)
    outcome = run_review(agent, _state())
    assert outcome.actions == ["Skill created"]
    assert (curator.get_skills_dir() / "deploy-notes" / "SKILL.md").exists()


def test_a_real_long_turn_triggers_a_review_and_its_own_history_is_untouched(make_agent):
    """The wiring in ``finalize.py``: a turn over the threshold starts a review, and the turn's
    stored transcript is exactly the turn and nothing else."""
    responses = [tool_call_response(("read_file", {"path": f"note{index}"})) for index in range(8)]
    responses += [text_response("all read"), tool_call_response(MEMORY_CALL), text_response("saved")]
    agent, _ = make_agent(responses, enabled_toolsets=["file", "memory", "skills"])
    for index in range(8):
        Path(agent.cwd, f"note{index}").write_text("x", encoding="utf-8")

    result = agent.run_conversation("read every note")

    assert result.completed and result.final_response == "all read"
    assert [message["role"] for message in agent.messages] == ["user"] + ["assistant", "tool"] * 8 + [
        "assistant"
    ]
    # The review runs on a background thread; wait for it to land in the real memory store.
    memory_file = get_memories_dir() / "MEMORY.md"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (memory_file.exists() and "gilead" in memory_file.read_text()):
        time.sleep(0.02)
    assert memory_file.exists() and "gilead" in memory_file.read_text()
    # And the turn that triggered it is still exactly the turn.
    assert [message["role"] for message in agent.messages] == ["user"] + ["assistant", "tool"] * 8 + [
        "assistant"
    ]


# ── the scheduled curator ────────────────────────────────────────────────────────────────


def _make_stale_agent_skill(name="deploy-thing", *, age_days=90):
    directory = curator.get_skills_dir() / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: a thing the agent once learned\n---\n\nBody.\n",
        encoding="utf-8",
    )
    record_created(name, "agent")
    from clite.core.io import atomic_write_json

    usage = load_usage()
    old = time.time() - age_days * 86400
    usage[name].update(created_at=old, last_used_at=old)
    atomic_write_json(curator.get_skills_dir() / ".usage.json", usage)


def test_the_startup_curator_runs_at_most_once_per_interval(clite_home, monkeypatch):
    from clite.core.config import load_config
    from clite.runtime import maintenance

    (clite_home / "config.yaml").write_text(
        "curator:\n  enabled: true\n  interval_hours: 24\n  stale_days: 30\n"
    )
    from clite.core import config as config_module

    config_module.reset_config_cache()
    config = load_config()

    calls = []
    monkeypatch.setattr(
        maintenance, "_prune_curator_store", lambda cfg, **kw: calls.append(1) or {"archived": []}
    )

    first = maintenance.run_curator_maintenance(config, now=1_000_000.0)
    second = maintenance.run_curator_maintenance(config, now=1_000_000.0 + 60)
    third = maintenance.run_curator_maintenance(config, now=1_000_000.0 + 25 * 3600)

    assert len(calls) == 2  # once at the start, once after the interval; not the middle call
    assert first is not None and second is None and third is not None


def test_the_startup_curator_is_off_when_disabled(clite_home, monkeypatch):
    from clite.core.config import load_config
    from clite.runtime import maintenance

    (clite_home / "config.yaml").write_text("curator:\n  enabled: false\n")
    from clite.core import config as config_module

    config_module.reset_config_cache()
    calls = []
    monkeypatch.setattr(
        maintenance, "_prune_curator_store", lambda cfg, **kw: calls.append(1) or {"archived": []}
    )
    assert maintenance.run_curator_maintenance(load_config(), now=1_000_000.0) is None
    assert calls == []


def test_a_failing_curator_does_not_stop_a_session(clite_home, monkeypatch):
    from clite.core.config import load_config
    from clite.runtime import maintenance

    (clite_home / "config.yaml").write_text("curator:\n  enabled: true\n  interval_hours: 1\n")
    from clite.core import config as config_module

    config_module.reset_config_cache()

    def boom(cfg, **kw):
        raise RuntimeError("curator store exploded")

    monkeypatch.setattr(maintenance, "_prune_curator_store", boom)
    maintenance.reset_maintenance_state()
    # run_startup_maintenance swallows the failure and returns normally.
    maintenance.run_startup_maintenance(load_config())
    assert maintenance.reset_maintenance_state() is None


def test_the_startup_curator_archives_a_stale_agent_skill(clite_home, monkeypatch):
    from clite.core.config import load_config
    from clite.runtime import maintenance

    (clite_home / "config.yaml").write_text(
        "curator:\n  enabled: true\n  interval_hours: 1\n  stale_days: 30\n"
    )
    from clite.core import config as config_module

    config_module.reset_config_cache()
    _make_stale_agent_skill("old-lesson")
    report = maintenance.run_curator_maintenance(load_config(), now=time.time())
    assert [entry["name"] for entry in report["stale"]] == ["old-lesson"]
    assert any("old-lesson" in path for path in report["archived"])
    assert all(
        skill.name != "old-lesson" for skill in discover_skills(include_disabled=True, all_platforms=True)
    )
