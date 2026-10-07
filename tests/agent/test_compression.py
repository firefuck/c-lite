"""Context compression: thresholds, boundaries, role alternation, and the agent integration."""

from __future__ import annotations

import pytest

from clite.agent.context.compressor import (
    FAILED_SUMMARY,
    PRUNED_MARKER,
    SUMMARY_PREFIX,
    SUMMARY_SECTIONS,
    SUMMARY_TEMPLATE,
    ContextCompressor,
    missing_summary_sections,
    prune_images,
    prune_tool_outputs,
    repair_tool_pairs,
    serialize_for_summary,
)
from clite.agent.context.engine import ContextEngine, create_context_engine, register_context_engine
from clite.agent.context.tokens import estimate_prompt_tokens
from clite.agent.memory.manager import MemoryManager
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


def _image(content: str = "look at this"):
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


def _with_image(index: int, text: str = "see the screenshot"):
    return {"role": "user", "content": [{"type": "text", "text": f"message {index}: {text}"}, _image()]}


def _content_text(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    return " ".join(part.get("text", "") for part in content if isinstance(part, dict))


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


# ── structured summary sections ──────────────────────────────────────────────────────────


def test_the_summary_template_asks_for_the_fixed_sections():
    # The five sections are the contract a handoff note has to satisfy, so the prompt names
    # each of them and the parser recognises the same names.
    assert SUMMARY_SECTIONS == ("Goal", "Key Decisions", "Files", "Failed Commands", "Unfinished Work")
    for section in SUMMARY_SECTIONS:
        assert f"## {section}" in SUMMARY_TEMPLATE


def test_missing_summary_sections_reports_what_a_summary_lacks():
    complete = "\n".join(f"## {section}\n- something" for section in SUMMARY_SECTIONS)
    assert missing_summary_sections(complete) == ()
    partial = "## Goal\nShip it.\n\n## Files\nsrc/app.py (changed)"
    missing = missing_summary_sections(partial)
    assert set(missing) == {"Key Decisions", "Failed Commands", "Unfinished Work"}


def test_a_structured_summary_keeps_file_states_and_failed_commands():
    messages = [*_chat(2), *_tool_round(1, "boom: command failed with exit 1"), *_chat(2)]

    def summarize(prompt):
        # The excerpt told the summariser what happened; the model answers in the fixed shape.
        assert "boom: command failed" in prompt
        return (
            "## Goal\nMake compression better.\n"
            "## Key Decisions\nUse provider prompt_tokens as the anchor.\n"
            "## Files\nsrc/clite/agent/context/compressor.py (changed)\n"
            "## Failed Commands\npytest tests/agent -k compress (exit 1: red test)\n"
            "## Unfinished Work\nWire the eval script into CI."
        )

    compressed = _engine(first=2, last=2).compress(messages, summarize=summarize)
    summary = next(m for m in compressed if m.get("is_summary"))
    assert "src/clite/agent/context/compressor.py (changed)" in summary["content"]
    assert "exit 1" in summary["content"]
    assert missing_summary_sections(summary["content"]) == ()


def test_the_summary_prompt_reports_what_a_previous_summary_was_missing():
    engine = _engine(first=2, last=2)
    first_pass = engine.compress(_chat(10), summarize=lambda prompt: "## Goal\nonly the goal")
    grown = [*first_pass, *_chat(8)]
    prompts = []

    engine.compress(grown, summarize=lambda prompt: prompts.append(prompt) or "## Goal\nupdated")
    # The model is told which sections the earlier note left out, so the update fills them.
    assert "Key Decisions" in prompts[0] and "Failed Commands" in prompts[0]


# ── staged summarisation ─────────────────────────────────────────────────────────────────


def test_a_middle_larger_than_the_aux_window_is_summarised_in_stages():
    engine = ContextCompressor()
    config = load_config()
    config["compression"].update({"protect_first_n": 2, "protect_last_n": 2})
    # A tiny auxiliary window forces the middle to be split rather than truncated.
    engine.configure(context_length=1_000_000, auxiliary_context_length=1_000, config=config)

    # Several large messages fill the middle; one carries a marker that would be lost if the
    # excerpt were cut to the first chunk.
    tail_marker = "the-very-last-thing-that-happened"
    big = "line-" + "x" * 400
    middle = [*_chat(2)]
    for _ in range(6):
        middle.append({"role": "assistant", "content": big * 8})
        middle.append({"role": "user", "content": big * 8})
    middle.append({"role": "assistant", "content": tail_marker})
    messages = [*middle, *_chat(6)]

    prompts = []

    def summarize(prompt):
        prompts.append(prompt)
        return "## Goal\nstaged"

    compressed = engine.compress(messages, summarize=summarize)
    assert engine.last_compression_calls > 1  # more than one summariser call: staged, not truncated
    assert any(m.get("is_summary") for m in compressed)
    # Every part of the middle reached a model call, so nothing was silently cut from the tape.
    joined = "\n".join(prompts)
    assert tail_marker in joined
    assert joined.count("line-") >= 2  # the oversized block appears in more than one chunk


def test_a_middle_that_fits_the_aux_window_is_summarised_in_one_call():
    engine = ContextCompressor()
    config = load_config()
    config["compression"].update({"protect_first_n": 2, "protect_last_n": 2})
    engine.configure(context_length=1_000_000, auxiliary_context_length=200_000, config=config)
    calls = []

    engine.compress(_chat(12), summarize=lambda prompt: calls.append(prompt) or "S")
    assert engine.last_compression_calls == 1
    assert len(calls) == 1


def test_staged_summarisation_still_updates_an_earlier_summary():
    engine = ContextCompressor()
    config = load_config()
    config["compression"].update({"protect_first_n": 2, "protect_last_n": 2})
    engine.configure(context_length=1_000_000, auxiliary_context_length=2_000, config=config)
    first = engine.compress(_chat(10), summarize=lambda prompt: "## Goal\nFIRST")
    grown = [*first, *_tool_round(1, "y" * 20_000), *_chat(8)]
    summaries = []

    def summarize(prompt):
        summaries.append(prompt)
        return "## Goal\nSECOND"

    second = engine.compress(grown, summarize=summarize)
    assert sum(1 for m in second if m.get("is_summary")) == 1
    assert any("FIRST" in prompt for prompt in summaries)  # the earlier note is folded in, not nested


# ── provider-anchored token counting ─────────────────────────────────────────────────────


def test_estimate_reuses_the_provider_number_for_the_part_it_already_measured():
    measured = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "y" * 400}]
    appended = [{"role": "user", "content": "z" * 400}]
    messages = [*measured, *appended]

    anchored = estimate_prompt_tokens(messages, system_prompt="S" * 400, tools=[{"a": 1}],
                                      anchor_tokens=1234, anchor_message_count=len(measured))
    # The anchor covers the earlier messages plus the system prompt and tools; only the
    # appended message is estimated on top.
    assert anchored == 1234 + estimate_prompt_tokens(appended)
    assert anchored != estimate_prompt_tokens(messages, system_prompt="S" * 400, tools=[{"a": 1}])


def test_engine_reports_anchored_tokens_after_a_response():
    engine = _engine(context_length=200_000)
    messages = [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}]
    engine.update_from_response(Usage(input_tokens=100_000), message_count=len(messages))
    # A later turn appends three messages; the provider number for the first two is reused.
    grown = [*messages, {"role": "user", "content": "three"}, {"role": "assistant", "content": "four"},
             {"role": "user", "content": "five"}]
    anchored = engine.anchored_prompt_tokens(grown, system_prompt="", tools=None)
    appended_only = estimate_prompt_tokens(grown[2:])
    assert anchored == 100_000 + appended_only
    assert engine.anchor_message_count == 2


def test_the_provider_number_wins_over_the_estimate_before_any_appended_message():
    engine = _engine(context_length=200_000)
    messages = [{"role": "user", "content": "x" * 4000}]
    engine.update_from_response(Usage(input_tokens=999_999), message_count=len(messages))
    assert engine.anchored_prompt_tokens(messages) == 999_999


# ── images are dropped before text ───────────────────────────────────────────────────────


def test_images_older_than_the_tail_are_dropped_before_any_text():
    messages = [_with_image(0), {"role": "assistant", "content": "seen"}, _with_image(2),
                {"role": "assistant", "content": "ok"}, _with_image(4), {"role": "assistant", "content": "recent"}]
    pruned, dropped = prune_images(messages, keep_last=2)
    assert dropped == 2
    assert not any(part.get("type") == "image_url" for part in pruned[0]["content"])
    assert "message 0" in pruned[0]["content"][0]["text"]  # the text of that message is kept
    # the newest image, inside the protected tail, survives
    assert any(part.get("type") == "image_url" for part in pruned[4]["content"])
    # the input list is untouched
    assert any(part.get("type") == "image_url" for part in messages[0]["content"])


def test_compression_drops_old_images_before_pruning_text():
    # Nothing to summarise here (the whole transcript is inside the protected head), so the
    # only work compression does is pruning — and images must be pruned ahead of text.
    engine = _engine(first=6, last=2)
    messages = [{"role": "user", "content": "start"}, _with_image(1, "first look"),
                {"role": "assistant", "content": "seen it"}, *_chat(2)]
    compressed = engine.compress(messages, summarize=lambda prompt: "unused")

    assert compressed is not messages
    image_message = compressed[1]
    assert isinstance(image_message.get("content"), list)
    # The image is replaced by a marker; the text of the same message survives.
    assert not any(part.get("type") == "image_url" for part in image_message["content"])
    assert "first look" in _content_text(image_message)


# ── the memory nudge survives a resumed session ──────────────────────────────────────────


def test_the_memory_nudge_counter_survives_a_resumed_session(clite_home):
    config = load_config()
    config["memory"]["nudge_interval"] = 3

    first = MemoryManager(config)
    first.initialize("session-42")
    nudges = [first.turn_nudge() for _ in range(3)]
    assert nudges[0] == "" and nudges[1] == "" and nudges[2] != ""

    # A new manager (the agent restarted for the same session) keeps the count, so the
    # reminder cycle continues instead of starting over at zero.
    resumed = MemoryManager(config)
    resumed.initialize("session-42")
    assert [resumed.turn_nudge() for _ in range(3)][2] != ""


def test_a_resumed_session_does_not_restart_the_nudge_count(clite_home):
    config = load_config()
    config["memory"]["nudge_interval"] = 2

    first = MemoryManager(config)
    first.initialize("s1")
    assert first.turn_nudge() == ""
    # Restart mid-interval: one more turn reaches the interval instead of starting over.
    resumed = MemoryManager(config)
    resumed.initialize("s1")
    assert resumed.turn_nudge() != ""


def test_writing_to_memory_resets_the_persisted_nudge_counter(clite_home):
    config = load_config()
    config["memory"]["nudge_interval"] = 2

    first = MemoryManager(config)
    first.initialize("s2")
    first.turn_nudge()
    first.handle_memory_tool("add", "memory", "Deploys run from the ops host")

    resumed = MemoryManager(config)
    resumed.initialize("s2")
    assert resumed.turn_nudge() == ""  # the count restarted, so no reminder yet


# ── the measurement script ───────────────────────────────────────────────────────────────


def test_the_compression_eval_script_runs_against_the_mock_provider():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("eval_compression", root / "scripts" / "eval_compression.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    report = module.evaluate(provider="mock")
    assert report["facts_total"] > 0
    assert report["facts_kept"] <= report["facts_total"]
    assert "missing" in report and isinstance(report["missing"], list)
    # The report is also renderable as text for a human comparing two summary prompts.
    assert "facts kept" in module.render(report).lower()


def test_the_compression_eval_script_reports_facts_a_summary_dropped():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("eval_compression", root / "scripts" / "eval_compression.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    # A summariser that throws the excerpt away loses every fact except the ones the protected
    # tail keeps, and the report says exactly which ones went missing.
    report = module.evaluate(provider="mock", summarize=lambda prompt: "## Goal\nNone")
    assert report["facts_kept"] < report["facts_total"]
    assert report["missing"]

