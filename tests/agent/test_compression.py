"""Context compression: thresholds, boundaries, role alternation, and the agent integration."""

from __future__ import annotations

import pytest

from clite.agent.context.compressor import (
    FAILED_SUMMARY,
    PRUNED_MARKER,
    SUMMARY_PREFIX,
    ContextCompressor,
    prune_tool_outputs,
    repair_tool_pairs,
    serialize_for_summary,
)
from clite.agent.context.engine import ContextEngine, create_context_engine, register_context_engine
from clite.core.config import load_config
from clite.providers.testing import text_response, tool_call_response
from clite.providers.transports.types import Usage
from clite.state import get_session_db


def _engine(first=2, last=4, context_length=1_000_000):
    engine = ContextCompressor()
    config = load_config()
    config["compression"].update({"protect_first_n": first, "protect_last_n": last})
    engine.configure(context_length=context_length, config=config)
    return engine


def _chat(count):
    return [{"role": "user" if n % 2 == 0 else "assistant", "content": f"message {n}"} for n in range(count)]


def _tool_round(index, output="result"):
    call = {"id": f"call_{index}", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}
    return [{"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": f"call_{index}", "name": "terminal", "content": output}]


def _roles(messages):
    return [message["role"] for message in messages]


def _assert_pairs_intact(messages):
    calls = [call["id"] for m in messages for call in m.get("tool_calls") or []]
    results = [m["tool_call_id"] for m in messages if m["role"] == "tool"]
    assert sorted(calls) == sorted(results)


# ── thresholds ───────────────────────────────────────────────────────────────────────────


def test_threshold_is_floored_for_small_windows():
    large, small = _engine(context_length=1_000_000), _engine(context_length=200_000)
    assert large.threshold_tokens == 500_000  # the configured 50%
    assert small.threshold_tokens == 150_000  # floored at 75%


def test_should_compress_follows_reported_usage():
    engine = _engine(context_length=200_000)
    assert engine.should_compress() is False
    engine.update_from_response(Usage(input_tokens=100_000, cache_read_tokens=60_000))
    assert engine.should_compress() is True
    assert engine.should_compress(10) is False
    assert engine.status()["usage_percent"] == 80.0


def test_engine_registry():
    class Keeper(ContextEngine):
        name = "keeper"

        def compress(self, messages, *, summarize, focus=None):
            return messages

    register_context_engine("keeper", Keeper)
    assert isinstance(create_context_engine("keeper"), Keeper)
    assert isinstance(create_context_engine("compressor"), ContextCompressor)
    with pytest.raises(ValueError):
        create_context_engine("nope")


# ── the algorithm ────────────────────────────────────────────────────────────────────────


def test_head_and_tail_survive_and_the_middle_becomes_a_summary():
    messages = _chat(12)
    prompts = []

    def summarize(prompt):
        prompts.append(prompt)
        return "## Goal\nShip the feature."

    compressed = _engine(first=2, last=3).compress(messages, summarize=summarize)
    assert [m["content"] for m in compressed[:2]] == ["message 0", "message 1"]
    assert [m["content"] for m in compressed[-3:]] == ["message 9", "message 10", "message 11"]
    assert len(compressed) == 6
    summary = compressed[2]
    assert summary["is_summary"] is True and summary["content"].startswith(SUMMARY_PREFIX)
    assert "Ship the feature." in summary["content"]
    assert "message 5" in prompts[0] and "message 0" not in prompts[0] and "message 11" not in prompts[0]
    assert len(messages) == 12 and "is_summary" not in messages[2]  # the input is untouched


def test_nothing_to_compress_returns_the_input():
    messages = _chat(5)
    engine = _engine(first=2, last=4)
    assert engine.compress(messages, summarize=lambda prompt: "unused") is messages
    assert engine.compression_count == 0


def test_tool_calls_are_never_separated_from_their_results():
    messages = [*_chat(2), *_tool_round(1), *_tool_round(2), *_tool_round(3), *_tool_round(4), {"role": "user", "content": "now?"}]
    for last in range(1, 8):
        for first in range(0, 5):
            compressed = _engine(first=first, last=last).compress(list(messages), summarize=lambda prompt: "S")
            _assert_pairs_intact(compressed)


def test_roles_alternate_around_the_summary():
    def no_adjacent_duplicates(messages):
        roles = [m["role"] for m in messages if m["role"] != "tool"]
        return all(a != b for a, b in zip(roles, roles[1:], strict=False))

    summarize = lambda prompt: "S"  # noqa: E731
    # head ends with assistant, tail starts with user: summary is folded into that user message
    folded = _engine(first=2, last=2).compress(_chat(10), summarize=summarize)
    assert no_adjacent_duplicates(folded) and folded[2]["content"].endswith("message 8")
    # head ends with user, tail starts with user: summary speaks as the assistant
    as_assistant = _engine(first=1, last=2).compress(_chat(10), summarize=summarize)
    assert as_assistant[1]["role"] == "assistant" and no_adjacent_duplicates(as_assistant)
    # head ends with assistant, tail starts with assistant: summary is a user message
    as_user = _engine(first=2, last=3).compress(_chat(11), summarize=summarize)
    assert as_user[2]["role"] == "user" and no_adjacent_duplicates(as_user)
    # head ends with user, tail starts with assistant: summary is folded into the head's user message
    into_head = _engine(first=1, last=3).compress(_chat(10), summarize=summarize)
    assert into_head[0]["content"].startswith("message 0") and SUMMARY_PREFIX in into_head[0]["content"]
    assert no_adjacent_duplicates(into_head)


def test_an_earlier_summary_is_updated_not_nested():
    engine = _engine(first=2, last=2)
    first_pass = engine.compress(_chat(10), summarize=lambda prompt: "FIRST SUMMARY")
    grown = [*first_pass, *_chat(8)]
    prompts = []

    def summarize(prompt):
        prompts.append(prompt)
        return "SECOND SUMMARY"

    second_pass = engine.compress(grown, summarize=summarize)
    assert "<earlier_summary>" in prompts[0] and "FIRST SUMMARY" in prompts[0]
    assert sum(1 for m in second_pass if m.get("is_summary")) == 1
    assert engine.compression_count == 2


def test_a_failing_summariser_still_makes_room():
    def broken(prompt):
        raise RuntimeError("auxiliary model is down")

    compressed = _engine(first=2, last=3).compress(_chat(12), summarize=broken)
    assert len(compressed) == 6
    assert FAILED_SUMMARY.format(count=7) in compressed[2]["content"]


def test_old_tool_output_is_pruned_but_recent_output_is_kept():
    messages = [*_chat(2), *_tool_round(1, "x" * 5000), *_tool_round(2, "y" * 5000), *_tool_round(3, "short")]
    pruned, saved = prune_tool_outputs(messages, keep_last=2)
    assert pruned[3]["content"] == PRUNED_MARKER and pruned[5]["content"] == PRUNED_MARKER
    assert pruned[7]["content"] == "short" and saved > 9000
    assert messages[3]["content"] == "x" * 5000


def test_pruning_alone_counts_as_a_change():
    messages = [*_chat(1), *_tool_round(1, "x" * 5000), *_chat(2)]
    engine = _engine(first=3, last=2)
    compressed = engine.compress(messages, summarize=lambda prompt: "unused")
    assert compressed is not messages and compressed[2]["content"] == PRUNED_MARKER


def test_repair_tool_pairs():
    call = {"id": "kept", "type": "function", "function": {"name": "t", "arguments": "{}"}}
    repaired = repair_tool_pairs([
        {"role": "tool", "tool_call_id": "orphan", "content": "x"},
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "user", "content": "next"},
    ])
    assert _roles(repaired) == ["assistant", "tool", "user"]
    assert repaired[1]["tool_call_id"] == "kept"


def test_summary_input_is_bounded_and_redacted():
    text = serialize_for_summary([
        {"role": "user", "content": "token is sk-abcdefghijklmnopqrstuvwxyz0123"},
        {"role": "tool", "name": "terminal", "content": "z" * 50_000},
        {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]},
    ])
    assert "[REDACTED]" in text and "sk-abcdefghijklmnop" not in text
    assert len(text) < 5000 and "[called tools: read_file(" in text


# ── through the agent ────────────────────────────────────────────────────────────────────


def test_manual_compression_keeps_the_session_and_rebuilds_the_prompt(make_agent, clite_home):
    (clite_home / "config.yaml").write_text("compression:\n  protect_first_n: 2\n  protect_last_n: 2\n")
    statuses = []
    from clite.agent import AgentCallbacks

    agent, client = make_agent(
        [text_response(f"answer {n}") for n in range(5)] + [
            tool_call_response(("memory", {"action": "add", "target": "memory", "content": "Deploys run from the ops host"})),
            text_response("noted"), text_response("HANDOFF SUMMARY"), text_response("after")],
        enabled_toolsets=["memory", "todo"],
        callbacks=AgentCallbacks(on_status=lambda kind, text: statuses.append(kind)),
    )
    for n in range(5):
        agent.run_conversation(f"question {n}")
    agent.run_conversation("remember where deploys run")
    agent.todos.write([{"id": "1", "content": "rotate the keys", "status": "in_progress"}])
    prompt_before, session_id = agent.system_prompt, agent.session_id

    assert agent.compress_context(focus="the deploy setup") is True
    assert agent.session_id == session_id
    assert statuses == ["compressing", "compressed"]
    summary = next(m for m in agent.messages if m.get("is_summary"))
    assert "HANDOFF SUMMARY" in summary["content"] and "rotate the keys" in summary["content"]
    assert "Pay particular attention to: the deploy setup" in client.calls[-1]["messages"][0]["content"]
    # Memory saved during the session becomes part of the prompt at the compression boundary.
    assert agent.system_prompt != prompt_before and "Deploys run from the ops host" in agent.system_prompt

    db = get_session_db()
    assert [m["content"] for m in db.get_messages(session_id)] == [m["content"] for m in agent.messages]
    assert db.get_session(session_id)["system_prompt"] == agent.system_prompt
    assert len(db.get_messages(session_id, include_inactive=True)) > len(agent.messages)

    agent.run_conversation("carry on")
    assert client.calls[-1]["messages"][0]["content"] == agent.system_prompt


def test_preflight_compression_fires_before_the_window_is_exceeded(make_agent, clite_home):
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  context_length: 16000\ncompression:\n  protect_first_n: 1\n  protect_last_n: 2\n")
    big = "lorem ipsum " * 1500  # about 4.5k tokens per answer
    agent, client = make_agent([text_response(big), text_response(big), text_response(big),
                                text_response("SUMMARY"), text_response("small answer")])
    for n in range(3):
        agent.run_conversation(f"q{n}")
    assert agent.context_engine.compression_count == 0
    result = agent.run_conversation("q3")  # history is now past 75% of 16k tokens
    assert result.final_response == "small answer"
    assert agent.context_engine.compression_count == 1
    assert any(m.get("is_summary") for m in agent.messages)


def test_compression_can_be_disabled(make_agent, clite_home):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  context_length: 16000\ncompression:\n  enabled: false\n")
    big = "lorem ipsum " * 3000
    agent, _ = make_agent([text_response(big), text_response(big), text_response("ok")])
    for n in range(3):
        agent.run_conversation(f"q{n}")
    assert agent.context_engine.compression_count == 0
