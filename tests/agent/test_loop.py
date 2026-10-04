"""The turn loop's contracts, exercised with a scripted model."""

from __future__ import annotations

import json
import threading
import time

import pytest

from clite.agent import AgentCallbacks
from clite.agent.messages import parse_tool_arguments, sanitize_for_api
from clite.agent.tool_executor import can_run_in_parallel
from clite.plugins.hooks import get_hook_bus
from clite.providers.base import ProviderProfile
from clite.providers.http import ProviderHTTPError
from clite.providers.testing import ScriptedClient, mock_route, text_response, tool_call_response
from clite.providers.transports.types import ToolCall, Usage
from clite.state import get_session_db
from clite.tools.registry import registry, tool_result


def _roles(agent):
    return [message["role"] for message in agent.messages]


def _http_error(status, message="boom"):
    return ProviderHTTPError(status, json.dumps({"error": {"message": message}}), {}, "u")


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr("clite.agent.turn.request._backoff", lambda attempt, retry_after: 0.0)


# ── the basic turn ───────────────────────────────────────────────────────────────────────


def test_text_turn(make_agent):
    agent, client = make_agent([text_response("Hello!")])
    result = agent.run_conversation("hi")
    assert result.final_response == "Hello!" and result.completed and result.api_calls == 1
    assert _roles(agent) == ["user", "assistant"]
    assert client.last_messages[0]["role"] == "system"
    assert client.last_messages[-1] == {"role": "user", "content": "hi"}


def test_tool_round_then_answer(make_agent, tmp_path):
    (tmp_path / "workspace" / "notes.txt").write_text("remember the milk\n")
    agent, client = make_agent([tool_call_response(("read_file", {"path": "notes.txt"})), text_response("It says: milk")])
    result = agent.run_conversation("what is in notes.txt?")
    assert result.final_response == "It says: milk" and result.api_calls == 2
    assert _roles(agent) == ["user", "assistant", "tool", "assistant"]
    tool_message = agent.messages[2]
    assert tool_message["name"] == "read_file" and "remember the milk" in tool_message["content"]
    # The second request carried the tool call and its result.
    assert [m["role"] for m in client.calls[1]["messages"]] == ["system", "user", "assistant", "tool"]


def test_transcript_is_durable_and_resumable(make_agent):
    agent, _ = make_agent([tool_call_response(("read_file", {"path": "x"})), text_response("done")])
    agent.run_conversation("go")
    stored = get_session_db().get_messages(agent.session_id)
    assert [m["role"] for m in stored] == ["user", "assistant", "tool", "assistant"]
    assert stored[1]["tool_calls"][0]["function"]["name"] == "read_file"

    resumed, client = make_agent([text_response("welcome back")], session_id=agent.session_id)
    assert _roles(resumed) == ["user", "assistant", "tool", "assistant"]
    resumed.run_conversation("again")
    assert [m["role"] for m in client.last_messages] == ["system", "user", "assistant", "tool", "assistant", "user"]


def test_assistant_tool_call_is_persisted_before_the_tool_runs(make_agent):
    seen = {}

    def spy(args, ctx=None):
        seen["stored_roles"] = [m["role"] for m in get_session_db().get_messages(ctx.session_id)]
        return tool_result(ok=True)

    registry.register("spy", "probe", {"description": "spy"}, spy, origin="test")
    agent, _ = make_agent([tool_call_response(("spy", {})), text_response("ok")], enabled_toolsets=["probe"])
    agent.run_conversation("go")
    assert seen["stored_roles"] == ["user", "assistant"]


def test_usage_accumulates_on_the_result_and_in_the_database(make_agent):
    agent, _ = make_agent([
        tool_call_response(("read_file", {"path": "x"}), usage=Usage(100, 10, cache_read_tokens=50)),
        text_response("ok", usage=Usage(200, 20)),
    ])
    result = agent.run_conversation("go")
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cache_read_tokens) == (300, 30, 50)
    row = get_session_db().get_session(agent.session_id)
    assert (row["input_tokens"], row["output_tokens"], row["api_call_count"]) == (300, 30, 2)
    assert agent.context_engine.last_prompt_tokens == 200


def test_callbacks_observe_the_turn(make_agent):
    events = []
    callbacks = AgentCallbacks(
        on_delta=lambda text: events.append(("delta", text)),
        on_step=lambda n: events.append(("step", n)),
        on_tool_start=lambda call_id, name, args: events.append(("tool_start", name)),
        on_tool_complete=lambda call_id, name, args, result, seconds: events.append(("tool_done", name)),
        on_message=lambda message: events.append(("message", message["role"])),
    )
    agent, _ = make_agent([tool_call_response(("read_file", {"path": "x"})), text_response("fin")], callbacks=callbacks)
    agent.run_conversation("go")
    assert events == [("step", 1), ("message", "assistant"), ("tool_start", "read_file"), ("tool_done", "read_file"),
                      ("step", 2), ("delta", "fin"), ("message", "assistant")]


def test_a_failing_callback_does_not_break_the_turn(make_agent):
    def explode(*args):
        raise RuntimeError("ui bug")

    agent, _ = make_agent([text_response("fine")], callbacks=AgentCallbacks(on_step=explode, on_message=explode))
    assert agent.run_conversation("go").final_response == "fine"


def test_only_one_turn_runs_at_a_time(make_agent):
    release = threading.Event()

    def slow(**kwargs):
        release.wait(5)
        return text_response("late")

    agent, _ = make_agent([slow])
    worker = threading.Thread(target=agent.run_conversation, args=("first",))
    worker.start()
    while not agent.busy:
        time.sleep(0.01)
    with pytest.raises(RuntimeError, match="already running"):
        agent.run_conversation("second")
    release.set()
    worker.join(5)


# ── prompt stability ─────────────────────────────────────────────────────────────────────


def test_system_prompt_and_tools_are_byte_stable_across_turns_and_resume(make_agent):
    agent, client = make_agent([text_response("a"), tool_call_response(("read_file", {"path": "x"})), text_response("b")])
    agent.run_conversation("one")
    agent.run_conversation("two")
    assert len(set(client.system_prompts())) == 1
    assert len({json.dumps(call["tools"]) for call in client.calls}) == 1

    resumed, resumed_client = make_agent([text_response("c")], session_id=agent.session_id)
    resumed.run_conversation("three")
    assert resumed_client.system_prompts()[0] == client.system_prompts()[0]


def test_memory_written_mid_session_does_not_change_that_sessions_prompt(make_agent):
    agent, client = make_agent(
        [tool_call_response(("memory", {"action": "add", "target": "user", "content": "Prefers tabs over spaces"})),
         text_response("saved"), text_response("again")],
        enabled_toolsets=["memory"],
    )
    agent.run_conversation("remember that I prefer tabs")
    agent.run_conversation("thanks")
    assert len(set(client.system_prompts())) == 1
    assert "Prefers tabs" not in client.system_prompts()[0]

    fresh, fresh_client = make_agent([text_response("hi")], enabled_toolsets=["memory"])
    fresh.run_conversation("hello")
    assert "Prefers tabs over spaces" in fresh_client.system_prompts()[0]


def test_turn_context_rides_the_user_message_and_is_stored_beside_it(make_agent):
    get_hook_bus().register("pre_llm_call", lambda user_message: {"context": f"[recalled for: {user_message}]"})
    agent, client = make_agent([tool_call_response(("read_file", {"path": "x"})), text_response("ok"), text_response("later")])
    agent.run_conversation("deploy status?")
    agent.run_conversation("and now?")
    for call in client.calls:  # the same bytes on every request, in this turn and the next
        assert call["messages"][1]["content"] == "deploy status?\n\n[recalled for: deploy status?]"
        assert "[recalled" not in call["messages"][0]["content"]
        assert all("turn_context" not in message for message in call["messages"])
    # The user's own words stay clean for display and search; the context sits beside them.
    stored = get_session_db().get_messages(agent.session_id)[0]
    assert agent.messages[0]["content"] == stored["content"] == "deploy status?"
    assert stored["turn_context"] == "[recalled for: deploy status?]"
    assert get_session_db().search_messages("recalled") == []


def test_every_request_repeats_the_previous_one_and_adds_to_its_end(make_agent, clite_home):
    """The wire form of what was already sent never changes. Prompt caching depends on it,
    and so do providers that sign reasoning blocks against the conversation before them."""
    (clite_home / "config.yaml").write_text("memory:\n  nudge_interval: 2\n")
    counter = iter(range(100))
    get_hook_bus().register("pre_llm_call", lambda user_message: {"context": f"[context #{next(counter)}]"})
    agent, client = make_agent(
        [tool_call_response(("read_file", {"path": "a"}), ("read_file", {"path": "b"})), text_response("one"),
         tool_call_response(("memory", {"action": "add", "target": "memory", "content": "Uses fish"})), text_response("two"),
         text_response("three"), text_response("four")],
        enabled_toolsets=["file", "memory"],
    )
    for text in ("first", "second", "third", "fourth"):
        agent.run_conversation(text)
    requests = [call["messages"] for call in client.calls]
    assert len(requests) == 6
    for earlier, later in zip(requests, requests[1:], strict=False):
        assert later[:len(earlier)] == earlier
        assert len(later) > len(earlier)

    # A resumed session sends the same bytes again.
    resumed, resumed_client = make_agent([text_response("five")], session_id=agent.session_id,
                                         enabled_toolsets=["file", "memory"])
    resumed.run_conversation("fifth")
    assert resumed_client.calls[0]["messages"][:len(requests[-1])] == requests[-1]


def test_cache_markers_are_applied_on_the_wire_only(make_agent):
    class Caching(ProviderProfile):
        def wants_cache_markers(self, model):
            return True

    route = mock_route(profile=Caching(name="mock", api_mode="mock", auth_type="none"))
    agent, client = make_agent([tool_call_response(("read_file", {"path": "x"})), text_response("ok")], route=route)
    agent.run_conversation("go")
    wire = client.calls[1]["messages"]
    assert wire[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    marked = sum(1 for m in wire if "cache_control" in m or (isinstance(m["content"], list) and "cache_control" in m["content"][-1]))
    assert marked == 4
    assert all("cache_control" not in m and isinstance(m.get("content"), (str, type(None))) for m in agent.messages)


def test_hooks_see_the_finished_turn_and_can_rewrite_the_answer(make_agent):
    seen = {}
    bus = get_hook_bus()
    bus.register("transform_llm_output", lambda text: text.replace("darn", "****"))
    bus.register("post_llm_call", lambda user_message, assistant_response, completed: seen.update(
        user=user_message, answer=assistant_response, completed=completed))
    agent, _ = make_agent([text_response("well darn")])
    assert agent.run_conversation("hm").final_response == "well ****"
    assert seen == {"user": "hm", "answer": "well ****", "completed": True}
    assert agent.messages[-1]["content"] == "well ****"


# ── tool execution ───────────────────────────────────────────────────────────────────────


def test_results_return_in_the_models_order_even_when_run_in_parallel(make_agent):
    started = []

    def slow(args):
        started.append("slow")
        time.sleep(0.2)
        return tool_result(v="slow")

    def fast(args):
        started.append("fast")
        return tool_result(v="fast")

    registry.register("slow_read", "probe", {"description": "s"}, slow, origin="test", parallel="safe")
    registry.register("fast_read", "probe", {"description": "f"}, fast, origin="test", parallel="safe")
    agent, _ = make_agent([tool_call_response(("slow_read", {}), ("fast_read", {})), text_response("ok")],
                          enabled_toolsets=["probe"])
    begun = time.monotonic()
    agent.run_conversation("go")
    assert [m["name"] for m in agent.messages if m["role"] == "tool"] == ["slow_read", "fast_read"]
    assert set(started) == {"slow", "fast"} and time.monotonic() - begun < 2


def test_a_sequential_tool_makes_the_whole_batch_sequential(make_agent, probe_tools):
    agent, _ = make_agent(
        [tool_call_response(("probe_read", {"path": "a"}), ("probe_act", {"path": "b"}), ("probe_read", {"path": "c"})),
         text_response("ok")],
        enabled_toolsets=["probe"],
    )
    agent.run_conversation("go")
    assert [name for name, _ in probe_tools] == ["probe_read", "probe_act", "probe_read"]


def test_parallel_policy():
    def calls(*specs):
        return [(ToolCall(f"c{i}", name, "{}"), args) for i, (name, args) in enumerate(specs)]

    registry.register("p_read", "probe", {"description": "r"}, lambda a: "{}", origin="test", parallel="safe")
    registry.register("p_write", "probe", {"description": "w"}, lambda a: "{}", origin="test", parallel="path", path_args=("path",))
    registry.register("p_act", "probe", {"description": "a"}, lambda a: "{}", origin="test")
    assert can_run_in_parallel(calls(("p_read", {}), ("p_read", {}))) is True
    assert can_run_in_parallel(calls(("p_write", {"path": "a"}), ("p_write", {"path": "b"}))) is True
    assert can_run_in_parallel(calls(("p_write", {"path": "a"}), ("p_write", {"path": "a"}))) is False  # same file
    assert can_run_in_parallel(calls(("p_read", {}), ("p_act", {}))) is False  # side effects
    assert can_run_in_parallel(calls(("p_read", {}), ("unknown", {}))) is False
    assert can_run_in_parallel(calls(("p_read", {}), ("p_read", None))) is False  # unparseable arguments
    assert can_run_in_parallel(calls(("p_read", {}))) is False  # nothing to parallelise


def test_malformed_arguments_are_repaired_or_reported(make_agent, probe_tools):
    agent, _ = make_agent(
        [tool_call_response(("probe_act", '```json\n{"path": "a",}\n```'), ("probe_act", "{not json")), text_response("ok")],
        enabled_toolsets=["probe"],
    )
    agent.run_conversation("go")
    assert probe_tools == [("probe_act", {"path": "a"})]  # the second call never ran
    results = [json.loads(m["content"]) for m in agent.messages if m["role"] == "tool"]
    assert results[0]["echo"] == {"path": "a"}
    assert "Invalid tool arguments" in results[1]["error"]


def test_parse_tool_arguments():
    assert parse_tool_arguments("") == ({}, None)
    assert parse_tool_arguments('{"a": 1}') == ({"a": 1}, None)
    assert parse_tool_arguments('"{\\"a\\": 1}"') == ({"a": 1}, None)  # double-encoded
    assert parse_tool_arguments("[1, 2]")[0] is None


def test_unknown_or_disabled_tool_gets_an_error_result_and_the_turn_continues(make_agent):
    agent, _ = make_agent([tool_call_response(("launch_rockets", {}), ("terminal", {"command": "ls"})), text_response("sorry")])
    result = agent.run_conversation("go")
    errors = [json.loads(m["content"])["error"] for m in agent.messages if m["role"] == "tool"]
    assert "Unknown tool" in errors[0] and "not enabled" in errors[1]
    assert result.completed and result.final_response == "sorry"


def test_tools_get_the_agent_context(make_agent):
    seen = {}

    def inspect(args, ctx=None):
        seen.update(session=ctx.session_id, platform=ctx.platform, has_agent=ctx.agent is not None, call=ctx.tool_call_id)
        return "{}"

    registry.register("inspect", "probe", {"description": "i"}, inspect, origin="test")
    agent, _ = make_agent([tool_call_response(("inspect", {})), text_response("ok")], enabled_toolsets=["probe"], platform="desktop")
    agent.run_conversation("go")
    assert seen == {"session": agent.session_id, "platform": "desktop", "has_agent": True, "call": "call_0_inspect"}


# ── response handling ────────────────────────────────────────────────────────────────────


def test_empty_response_is_retried(make_agent):
    statuses = []
    agent, client = make_agent([text_response(""), text_response("   "), text_response("finally")],
                               callbacks=AgentCallbacks(on_status=lambda kind, text: statuses.append(kind)))
    result = agent.run_conversation("go")
    assert result.final_response == "finally" and len(client.calls) == 3
    assert statuses == ["retry", "retry"]
    assert _roles(agent) == ["user", "assistant"]  # the empty responses left no trace


def test_a_refusal_is_reported_once_and_not_retried(make_agent):
    agent, client = make_agent([text_response("", finish_reason="content_filter")])
    result = agent.run_conversation("go")
    assert len(client.calls) == 1
    assert result.completed is False and result.exit_reason == "refusal"
    assert "declined to respond" in result.final_response and _roles(agent) == ["user", "assistant"]


def test_persistently_empty_response_ends_the_turn_with_an_explanation(make_agent):
    agent, _ = make_agent([text_response("")] * 3)
    result = agent.run_conversation("go")
    assert result.completed is False and result.error == "empty_response"
    assert "empty response" in result.final_response


def test_truncated_output_is_continued_and_joined(make_agent):
    agent, client = make_agent([text_response("The answer is ", finish_reason="length"), text_response("forty-two.")])
    result = agent.run_conversation("go")
    assert result.final_response == "The answer is forty-two."
    assert "cut off" in client.calls[1]["messages"][-1]["content"]
    assert _roles(agent) == ["user", "assistant", "user", "assistant"]


# ── limits ───────────────────────────────────────────────────────────────────────────────


def test_iteration_budget_ends_with_a_tool_less_wrap_up(make_agent):
    loop_forever = tool_call_response(("read_file", {"path": "x"}))
    agent, client = make_agent([loop_forever, loop_forever, text_response("I read the file twice; more remains.")], max_turns=2)
    result = agent.run_conversation("go")
    assert result.completed is False and result.exit_reason == "budget_exhausted"
    assert result.final_response == "I read the file twice; more remains."
    assert client.calls[-1]["tools"] is None
    assert "limit for this turn" in client.calls[-1]["messages"][-1]["content"]
    assert _roles(agent)[-1] == "assistant"


def test_the_model_is_warned_before_the_budget_runs_out(make_agent):
    step = tool_call_response(("read_file", {"path": "x"}))
    agent, _ = make_agent([step, step, text_response("done")], max_turns=3)
    agent.run_conversation("go")
    tool_results = [m["content"] for m in agent.messages if m["role"] == "tool"]
    assert "[BUDGET:" not in tool_results[0]
    assert "[BUDGET: 1 tool-calling iteration(s) left" in tool_results[1]


def test_unlimited_budget_by_default(make_agent):
    agent, _ = make_agent([])
    assert agent.budget.limit is None and agent.budget.remaining is None


def test_time_budget(make_agent, clite_home):
    (clite_home / "config.yaml").write_text("agent:\n  run_budget_seconds: 0.05\n")

    def slow_tool_call(**kwargs):
        time.sleep(0.1)
        return tool_call_response(("read_file", {"path": "x"}))

    agent, _ = make_agent([slow_tool_call, text_response("out of time")])
    assert agent.run_conversation("go").exit_reason == "budget_exhausted"


# ── interrupts and steering ──────────────────────────────────────────────────────────────


def test_interrupt_during_the_model_call(make_agent):
    def blocked(cancel, **kwargs):
        cancel.wait(5)
        raise InterruptedError

    agent, _ = make_agent([blocked, text_response("second turn works")])
    threading.Timer(0.1, agent.interrupt).start()
    result = agent.run_conversation("go")
    assert result.interrupted and not result.completed and result.final_response == ""
    assert _roles(agent) == ["user"]
    assert agent.run_conversation("again").final_response == "second turn works"


def test_interrupt_during_tools_skips_the_rest_and_keeps_the_transcript_valid(make_agent, probe_tools):
    def interrupting(args, ctx=None):
        ctx.agent.interrupt()
        return tool_result(done=True)

    registry.register("stopper", "probe", {"description": "s"}, interrupting, origin="test")
    agent, client = make_agent(
        [tool_call_response(("stopper", {}), ("probe_act", {"path": "never"})), text_response("resumed")],
        enabled_toolsets=["probe"],
    )
    result = agent.run_conversation("go")
    assert result.interrupted and probe_tools == []
    tool_results = [json.loads(m["content"]) for m in agent.messages if m["role"] == "tool"]
    assert tool_results[0] == {"done": True} and "cancelled" in tool_results[1]["error"]
    # The next turn sends a transcript in which every call has its result.
    agent.run_conversation("continue")
    assert [m["role"] for m in client.last_messages] == ["system", "user", "assistant", "tool", "tool", "user"]


def test_steer_attaches_to_the_latest_tool_result(make_agent):
    def steering(args, ctx=None):
        ctx.agent.steer("use the staging database")
        return tool_result(ok=True)

    registry.register("work", "probe", {"description": "w"}, steering, origin="test")
    agent, client = make_agent([tool_call_response(("work", {})), text_response("switched")], enabled_toolsets=["probe"])
    agent.run_conversation("migrate")
    tool_message = client.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "use the staging database" in tool_message["content"]
    assert _roles(agent) == ["user", "assistant", "tool", "assistant"]  # no extra message, no interruption


def test_sanitize_adds_stubs_and_drops_orphans():
    call = {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}
    history = [
        {"role": "system", "content": "old prompt"},
        {"role": "tool", "tool_call_id": "gone", "content": "orphan"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None, "tool_calls": [call, {**call, "id": "c2"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
        {"role": "user", "content": "next"},
    ]
    cleaned = sanitize_for_api(history)
    assert [(m["role"], m.get("tool_call_id")) for m in cleaned] == [
        ("user", None), ("assistant", None), ("tool", "c1"), ("tool", "c2"), ("user", None)]
    assert "interrupted" in cleaned[3]["content"]
    assert len(history) == 6  # the input is untouched


# ── API failures ─────────────────────────────────────────────────────────────────────────


def test_transient_errors_are_retried(make_agent):
    statuses = []
    agent, client = make_agent([_http_error(503), _http_error(429), text_response("ok")],
                               callbacks=AgentCallbacks(on_status=lambda kind, text: statuses.append((kind, text))))
    result = agent.run_conversation("go")
    assert result.final_response == "ok" and len(client.calls) == 3
    assert [kind for kind, _ in statuses] == ["retry", "retry"]
    assert result.api_calls == 1  # only the call that succeeded counts


def test_retries_are_bounded(make_agent, clite_home):
    (clite_home / "config.yaml").write_text("agent:\n  api_max_retries: 2\n")
    agent, client = make_agent([_http_error(503)] * 5)
    result = agent.run_conversation("go")
    assert len(client.calls) == 3  # one attempt and two retries
    assert result.completed is False and result.exit_reason == "api_error:server_error"
    assert "503" in result.final_response and _roles(agent) == ["user"]


def test_a_request_error_is_not_retried(make_agent):
    agent, client = make_agent([_http_error(400, "messages.3: unexpected role")])
    result = agent.run_conversation("go")
    assert len(client.calls) == 1 and result.exit_reason == "api_error:format_error"


def test_bad_key_rotates_to_the_next_credential(make_agent, monkeypatch):
    from clite.providers.runtime import resolve_runtime_provider

    monkeypatch.setenv("OPENROUTER_API_KEY", "key-one")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "key-two")
    agent, client = make_agent([_http_error(401, "invalid key"), text_response("ok")],
                               route=resolve_runtime_provider("openrouter", "vendor/m"))
    assert agent.run_conversation("go").final_response == "ok"
    assert [call["route"].api_key for call in client.calls] == ["key-one", "key-two"]


def test_fallback_provider_takes_over_for_the_turn(make_agent, clite_home):
    (clite_home / "config.yaml").write_text(
        "agent:\n  api_max_retries: 0\nfallback_providers:\n  - {provider: mock, model: backup-model}\n")
    statuses = []
    agent, client = make_agent([_http_error(503), text_response("from the backup")],
                               callbacks=AgentCallbacks(on_status=lambda kind, text: statuses.append(kind)))
    result = agent.run_conversation("go")
    assert result.final_response == "from the backup" and result.model == "backup-model"
    assert [call["route"].model for call in client.calls] == ["test-model", "backup-model"]
    assert statuses == ["fallback"]
    assert agent.route.model == "test-model"  # the primary route is used again next turn


def test_context_overflow_compresses_and_tries_again(make_agent):
    history = [text_response(f"answer {n}") for n in range(12)]
    agent, client = make_agent([*history, _http_error(400, "prompt is too long: 250000 tokens > 200000 maximum"),
                                text_response("SUMMARY OF EARLIER TURNS"), text_response("after compression")])
    for n in range(12):
        agent.run_conversation(f"question {n}")
    session_id = agent.session_id
    result = agent.run_conversation("one more")
    assert result.final_response == "after compression"
    assert agent.session_id == session_id
    assert any("SUMMARY OF EARLIER TURNS" in str(m["content"]) for m in agent.messages)
    assert len(agent.messages) < 26
    assert get_session_db().get_session(session_id)["compression_count"] == 1
    assert get_session_db().search_messages("question 5")  # archived turns stay searchable


# ── replayed reasoning blocks ────────────────────────────────────────────────────────────

SIGNED = {"anthropic_blocks": [{"type": "thinking", "thinking": "", "signature": "sig-1"}, {"type": "text", "text": "one"}]}
SIGNATURE_ERROR = ("messages.1.content.0: Invalid `signature` in `thinking` block. The block is bound to a "
                   "different conversation.")


def _signed(text):
    response = text_response(text)
    response.provider_data = dict(SIGNED)
    return response


def test_replay_data_is_stored_and_sent_back(make_agent):
    agent, client = make_agent([_signed("one"), text_response("two")])
    agent.run_conversation("first")
    agent.run_conversation("second")
    assert client.calls[1]["messages"][2]["provider_data"] == SIGNED
    assert get_session_db().get_messages(agent.session_id)[1]["provider_data"] == SIGNED


def test_rejected_replay_data_is_dropped_and_the_request_retried_once(make_agent):
    statuses = []
    agent, client = make_agent(
        [_signed("one"), _http_error(400, SIGNATURE_ERROR), text_response("two")],
        callbacks=AgentCallbacks(on_status=lambda kind, text: statuses.append(text)),
    )
    agent.run_conversation("first")
    result = agent.run_conversation("second")
    assert result.final_response == "two" and result.api_calls == 1
    assert "provider_data" in client.calls[1]["messages"][2] and "provider_data" not in client.calls[2]["messages"][2]
    assert "resending without it" in statuses[0]
    # Dropped for good, in memory and in the database; what the user sees is unchanged.
    stored = get_session_db().get_messages(agent.session_id)
    assert all("provider_data" not in message for message in [*agent.messages, *stored])
    assert [message["content"] for message in stored] == ["first", "one", "second", "two"]


def test_a_second_signature_rejection_in_the_same_turn_fails_the_turn(make_agent):
    agent, client = make_agent([_signed("one"), _http_error(400, SIGNATURE_ERROR), _http_error(400, SIGNATURE_ERROR)])
    agent.run_conversation("first")
    result = agent.run_conversation("second")
    assert result.completed is False and result.exit_reason == "api_error:thinking_signature"
    assert len(client.calls) == 3


def test_switching_models_drops_replay_data(make_agent):
    agent, client = make_agent([_signed("one"), text_response("two")])
    agent.run_conversation("first")
    agent.switch_model(mock_route(model="another-model"))
    agent.run_conversation("second")
    assert all("provider_data" not in message for message in client.calls[1]["messages"])


def test_compression_drops_replay_data_only_when_it_is_bound_to_the_prefix(make_agent):
    class Bound(ProviderProfile):
        def replay_is_prefix_bound(self, model):
            return True

    def run(route):
        agent, _ = make_agent([_signed(f"answer {n}") for n in range(14)] + [text_response("SUMMARY")], route=route)
        for n in range(14):
            agent.run_conversation(f"question {n}")
        assert agent.compress_context() is True
        return [message for message in agent.messages if message.get("provider_data")]

    assert run(mock_route(profile=Bound(name="mock", api_mode="mock", auth_type="none"))) == []
    assert len(run(mock_route())) > 0  # a provider without that rule keeps its blocks


def test_an_internal_error_is_reported_not_raised(make_agent, monkeypatch):
    def broken(agent, state):
        raise KeyError("bug in a phase")

    monkeypatch.setattr("clite.agent.loop.ITERATION_PHASES", (broken,))
    agent, _ = make_agent([])
    result = agent.run_conversation("go")
    assert result.exit_reason == "internal_error" and "KeyError" in result.error


# ── agent-level tools ────────────────────────────────────────────────────────────────────


def test_todo_tool_keeps_a_plan_on_the_agent(make_agent):
    plan = [{"id": "1", "content": "write tests", "status": "in_progress"}, {"id": "2", "content": "ship", "status": "pending"}]
    agent, _ = make_agent(
        [tool_call_response(("todo", {"todos": plan})),
         tool_call_response(("todo", {"todos": [{"id": "1", "content": "write tests", "status": "completed"}], "merge": True})),
         tool_call_response(("todo", {})), text_response("ok")],
        enabled_toolsets=["todo"],
    )
    agent.run_conversation("plan it")
    assert [item["status"] for item in agent.todos.read()] == ["completed", "pending"]
    last = json.loads([m for m in agent.messages if m["role"] == "tool"][-1]["content"])
    assert last["summary"]["completed"] == 1 and last["summary"]["total"] == 2
    assert "2. ship" in agent.todos.format_active() and "write tests" not in agent.todos.format_active()


def test_clarify_asks_through_the_surface(make_agent):
    asked = []

    def clarify(question, choices):
        asked.append((question, choices))
        return "staging"

    agent, _ = make_agent([tool_call_response(("clarify", {"question": "Which env?", "choices": ["staging", "prod"]})),
                           text_response("ok")], enabled_toolsets=["clarify"], callbacks=AgentCallbacks(clarify=clarify))
    agent.run_conversation("deploy")
    assert asked == [("Which env?", ["staging", "prod"])]
    assert json.loads(agent.messages[2]["content"])["answer"] == "staging"


def test_clarify_without_a_user_tells_the_model_to_decide(make_agent):
    agent, _ = make_agent([tool_call_response(("clarify", {"question": "Which env?"})), text_response("ok")],
                          enabled_toolsets=["clarify"])
    agent.run_conversation("deploy")
    assert "no user to ask" in json.loads(agent.messages[2]["content"])["error"]


def test_session_search_finds_other_sessions_only(make_agent):
    earlier, _ = make_agent([text_response("The staging database is db-stage-7.")])
    earlier.run_conversation("where is the staging database?")
    agent, _ = make_agent([tool_call_response(("session_search", {"query": "staging database"})), text_response("ok")],
                          enabled_toolsets=["session_search"])
    agent.run_conversation("what was the staging database again?")
    found = json.loads(agent.messages[2]["content"])
    assert found["count"] >= 1
    assert {hit["session_id"] for hit in found["results"]} == {earlier.session_id}
    assert any("db-stage-7" in hit["snippet"] for hit in found["results"])


def test_closing_fires_the_session_end_hook_once(make_agent):
    ended = []
    get_hook_bus().register("on_session_end", lambda session_id, reason: ended.append((session_id, reason)))
    agent, _ = make_agent([text_response("bye")])
    agent.run_conversation("hi")
    agent.close("user_exit")
    agent.close("again")
    assert ended == [(agent.session_id, "user_exit")]
    assert get_session_db().get_session(agent.session_id)["end_reason"] == "user_exit"
    with pytest.raises(RuntimeError):
        agent.run_conversation("more")


def test_scripted_client_reports_when_the_script_runs_out(make_agent):
    client = ScriptedClient([])
    agent, _ = make_agent(client=client)
    result = agent.run_conversation("go")
    assert result.completed is False  # the AssertionError is classified, not propagated
