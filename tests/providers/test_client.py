"""LLMClient against a real HTTP server: requests, streams, errors, cancellation."""

from __future__ import annotations

import json
import threading
import time

import pytest

from clite.providers.client import LLMClient
from clite.providers.errors import FailoverReason, classify_api_error
from clite.providers.http import ProviderHTTPError, parse_sse
from clite.providers.runtime import resolve_runtime_provider
from clite.providers.testing import mock_route
from clite.providers.transports.types import RequestParams


@pytest.mark.parametrize("stream", [False, True])
def test_responses_every_request_repeats_the_previous_one_and_adds_to_its_end(fake_api, stream):
    from clite.agent import AgentCallbacks
    from clite.core.config import load_config
    from clite.runtime import build_agent
    from clite.tools.registry import registry, tool_result

    executed, deltas, thoughts = [], [], []

    def probe(args, ctx=None):
        executed.append(args["n"])
        return tool_result(number=args["n"])

    registry.register("probe", "responses-probe", {"name": "probe", "description": "Return a number",
                      "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}},
                      probe, origin="test")
    outputs = []
    for n in (1, 2):
        outputs.append([
            {"type": "reasoning", "id": f"rs_{n}", "encrypted_content": f"opaque-{n}",
             "summary": [{"type": "summary_text", "text": f"plan {n}"}]},
            {"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}", "name": "probe",
             "arguments": json.dumps({"n": n}), "status": "completed"},
        ])
    for n in (3, 4, 5):
        outputs.append([{"type": "message", "id": f"msg_{n}", "role": "assistant", "status": "completed",
                         "phase": "final_answer", "content": [{"type": "output_text", "text": "done", "annotations": []}]}])
    replies = []
    for output in outputs:
        payload = {"status": "completed", "model": "gpt-5-codex", "output": output,
                   "usage": {"input_tokens": 10, "output_tokens": 4}}
        if stream:
            events = []
            for index, item in enumerate(output):
                events.append(("response.output_item.added", {"output_index": index, "item": item}))
                if item["type"] == "message":
                    events.append(("response.output_text.delta", {"output_index": index, "delta": "done"}))
                elif item["type"] == "reasoning":
                    events.append(("response.reasoning_summary_text.delta", {"output_index": index, "delta": item["summary"][0]["text"]}))
                events.append(("response.output_item.done", {"output_index": index, "item": item}))
            events.append(("response.completed", {"response": payload}))
            replies.append((200, fake_api.sse(*events)))
        else:
            replies.append((200, payload))
    fake_api.on("POST", "/v1/responses", *replies)
    config = load_config()
    config["agent"]["api_max_retries"] = 0
    config["display"]["show_reasoning"] = True
    config["fallback_providers"] = []
    route = _route(fake_api, model="gpt-5-codex")
    agent = build_agent(route=route, config=config, toolsets=["responses-probe"], auto_title=False,
                        stream=stream, callbacks=AgentCallbacks(on_delta=deltas.append, on_reasoning=thoughts.append))
    session_id = agent.session_id
    try:
        assert agent.run_conversation("Run probe twice.").final_response == "done"
        assert executed == [1, 2]
        assert agent.run_conversation("Again?").final_response == "done"
    finally:
        agent.close()
    resumed = build_agent(route=route, config=config, toolsets=["responses-probe"], auto_title=False,
                          stream=stream, session_id=session_id)
    try:
        assert resumed.run_conversation("Continue.").final_response == "done"
    finally:
        resumed.close()
    requests = fake_api.bodies("/v1/responses")
    assert len(requests) == 5
    for earlier, later in zip(requests, requests[1:], strict=False):
        assert later["input"][:len(earlier["input"])] == earlier["input"]
        assert len(later["input"]) > len(earlier["input"])
        assert later["tools"] == earlier["tools"]
    for n, output in enumerate(outputs[:2]):
        start = len(requests[n]["input"])
        assert requests[n + 1]["input"][start:start + len(output)] == output
        result = requests[n + 1]["input"][start + len(output)]
        assert result["type"] == "function_call_output" and result["call_id"] == f"call_{n + 1}"
        assert json.loads(result["output"])["number"] == n + 1
    assert all(r["store"] is False and "previous_response_id" not in r for r in requests)
    if stream:
        assert deltas == ["done", "done"] and thoughts == ["plan 1", "plan 2"]


MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]

IMAGE_CONTENT = [{"type": "text", "text": "what is this?"},
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]


def _route(fake_api, provider="openai", model="model-x"):
    return resolve_runtime_provider(provider, model, base_url=fake_api.url + "/v1", api_key="test-key")


@pytest.mark.parametrize("stream", [False, True])
def test_a_turn_with_an_image_reaches_the_provider_over_http_and_is_resent_unchanged(fake_api, stream):
    """End to end through the real HTTP client: the image part is on the wire in both stream
    modes, and the second turn repeats the first request byte for byte before appending."""
    from clite.agent import AgentCallbacks
    from clite.core.config import load_config
    from clite.runtime import build_agent

    reply = {"choices": [{"finish_reason": "stop", "message": {"content": "a red dot"}}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
    if stream:
        chunks = [
            {"choices": [{"delta": {"content": "a red dot"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": reply["usage"]},
        ]
        fake_api.on("POST", "/v1/chat/completions",
                    (200, fake_api.sse(*chunks, done=True)), (200, fake_api.sse(*chunks, done=True)))
    else:
        fake_api.on("POST", "/v1/chat/completions", (200, reply), (200, reply))

    config = load_config()
    config["fallback_providers"] = []
    agent = build_agent(route=_route(fake_api), config=config, toolsets=[], auto_title=False,
                        stream=stream, callbacks=AgentCallbacks())
    try:
        agent.run_conversation(IMAGE_CONTENT)
        agent.run_conversation("and now?")
    finally:
        agent.close()

    bodies = fake_api.bodies("/v1/chat/completions")
    assert len(bodies) == 2
    assert bodies[0]["messages"][1]["content"] == IMAGE_CONTENT
    assert bodies[1]["messages"][:len(bodies[0]["messages"])] == bodies[0]["messages"]
    assert bodies[1]["messages"][1]["content"] == IMAGE_CONTENT



def test_non_streaming_call(fake_api):
    fake_api.on("POST", "/v1/chat/completions", (200, {
        "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }))
    response = LLMClient().complete(_route(fake_api), MESSAGES, stream=False)
    assert response.content == "hello" and response.usage.output_tokens == 1
    sent = fake_api.requests[0]
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["body"]["model"] == "model-x" and sent["body"]["messages"] == MESSAGES
    assert sent["headers"]["User-Agent"].startswith("clite/")


def test_streaming_call_delivers_deltas_in_order(fake_api):
    fake_api.on("POST", "/v1/chat/completions", (200, fake_api.sse(
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        done=True,
    )))
    deltas = []
    response = LLMClient().complete(_route(fake_api), MESSAGES, on_delta=deltas.append)
    assert deltas == ["Hel", "lo"] and response.content == "Hello"
    assert response.usage.prompt_tokens == 5
    assert fake_api.requests[0]["body"]["stream"] is True


def test_anthropic_streaming_end_to_end(fake_api):
    fake_api.on("POST", "/v1/messages", (200, fake_api.sse(
        ("message_start", {"type": "message_start", "message": {"model": "claude-x", "usage": {"input_tokens": 4}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi!"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}}),
        ("message_stop", {"type": "message_stop"}),
    )))
    route = resolve_runtime_provider("anthropic", "claude-x", base_url=fake_api.url, api_key="sk-ant")
    response = LLMClient().complete(route, MESSAGES)
    assert response.content == "Hi!" and response.finish_reason == "stop"
    sent = fake_api.requests[0]
    assert sent["path"] == "/v1/messages" and sent["headers"]["x-api-key"] == "sk-ant"
    assert sent["body"]["system"] == [{"type": "text", "text": "sys"}]


def test_http_error_carries_status_message_and_headers(fake_api):
    fake_api.on("POST", "/v1/chat/completions",
                (429, {"error": {"message": "Rate limit reached", "type": "rate_limit_error"}}, {"Retry-After": "7"}))
    with pytest.raises(ProviderHTTPError) as raised:
        LLMClient().complete(_route(fake_api), MESSAGES, stream=False)
    assert raised.value.status == 429 and raised.value.message == "Rate limit reached"
    classified = classify_api_error(raised.value)
    assert classified.reason is FailoverReason.RATE_LIMIT and classified.retry_after == 7.0


def test_error_event_inside_a_stream_is_raised(fake_api):
    fake_api.on("POST", "/v1/messages", (200, fake_api.sse(
        ("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))))
    route = resolve_runtime_provider("anthropic", "claude-x", base_url=fake_api.url, api_key="k")
    with pytest.raises(ProviderHTTPError) as raised:
        LLMClient().complete(route, MESSAGES)
    assert classify_api_error(raised.value).reason is FailoverReason.OVERLOADED


def test_cancel_aborts_a_stream_promptly(fake_api):
    chunk = fake_api.sse({"choices": [{"delta": {"content": "tick "}}]})
    fake_api.on("POST", "/v1/chat/completions", (200, fake_api.slow_stream([chunk] * 200, 0.05)))
    cancel = threading.Event()
    deltas = []

    def on_delta(text):
        deltas.append(text)
        if len(deltas) == 3:
            cancel.set()

    started = time.monotonic()
    with pytest.raises(InterruptedError):
        LLMClient().complete(_route(fake_api), MESSAGES, on_delta=on_delta, cancel=cancel)
    assert time.monotonic() - started < 3  # the full stream would take 10 seconds
    assert 3 <= len(deltas) < 30


def test_a_stalled_stream_times_out(fake_api):
    fake_api.on("POST", "/v1/chat/completions", (200, fake_api.slow_stream([fake_api.sse({"choices": [{"delta": {"content": "x"}}]})], 5)))
    with pytest.raises(OSError) as raised:
        LLMClient().complete(_route(fake_api), MESSAGES, params=RequestParams(timeout=0.3))
    assert classify_api_error(raised.value).reason is FailoverReason.TIMEOUT


def test_connection_refused_is_retryable(fake_api):
    route = resolve_runtime_provider("openai", "m", base_url="http://127.0.0.1:9/v1", api_key="k")
    with pytest.raises(OSError) as raised:
        LLMClient().complete(route, MESSAGES, stream=False)
    assert classify_api_error(raised.value).retryable is True


def test_sse_parser_handles_comments_multiline_data_and_a_missing_final_blank_line():
    lines = [": keep-alive\n", "event: note\n", "data: one\n", "data: two\n", "\n", "data: last\n"]
    assert [(e.event, e.data) for e in parse_sse(iter(lines))] == [("note", "one\ntwo"), ("message", "last")]


# ── the offline mock provider ────────────────────────────────────────────────────────────

TOOLS = [{"type": "function", "function": {"name": "terminal", "parameters": {}}}]


def test_mock_echoes_and_streams():
    deltas = []
    response = LLMClient().complete(mock_route(), [{"role": "user", "content": "hello there"}], on_delta=deltas.append)
    assert response.content == "You said: hello there"
    assert "".join(deltas) == response.content and len(deltas) > 1
    assert response.usage.input_tokens > 0


def test_mock_calls_an_offered_tool_then_reports_its_result():
    client = LLMClient()
    first = client.complete(mock_route(), [{"role": "user", "content": '!terminal {"command": "echo hi"}'}], TOOLS)
    assert first.finish_reason == "tool_calls"
    assert json.loads(first.tool_calls[0].arguments) == {"command": "echo hi"}
    second = client.complete(mock_route(), [
        {"role": "user", "content": "x"}, first.to_assistant_message(),
        {"role": "tool", "tool_call_id": first.tool_calls[0].id, "name": "terminal", "content": '{"output": "hi"}'},
    ], TOOLS)
    assert "terminal tool returned" in second.content and second.finish_reason == "stop"


def test_mock_refuses_a_tool_that_was_not_offered():
    response = LLMClient().complete(mock_route(), [{"role": "user", "content": "!terminal {}"}], [])
    assert response.tool_calls == [] and "unknown directive" in response.content


def test_mock_can_fail_and_be_cancelled():
    with pytest.raises(ProviderHTTPError) as raised:
        LLMClient().complete(mock_route(), [{"role": "user", "content": "!error 503"}])
    assert raised.value.status == 503

    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(InterruptedError):
        LLMClient().complete(mock_route(), [{"role": "user", "content": "!sleep 10"}], cancel=cancel)
    assert time.monotonic() - started < 3


@pytest.mark.parametrize("url", ["https://other.invalid/v1", "http://proxy.invalid/v1", "https://proxy.invalid:444/v1"])
@pytest.mark.parametrize("stream", [False, True])
def test_credentials_are_rejected_before_http_when_route_origin_changes(monkeypatch, url, stream):
    from clite.core.errors import AuthError

    route = resolve_runtime_provider("openai", "m", base_url="https://proxy.invalid/v1", api_key="synthetic-key")
    route.base_url = url
    client = LLMClient()

    def forbidden_http(*args, **kwargs):
        pytest.fail("A mismatched credential origin reached the HTTP client")

    monkeypatch.setattr(client.http, "post_json", forbidden_http)
    monkeypatch.setattr(client.http, "stream_sse", forbidden_http)
    with pytest.raises(AuthError, match="bound to another endpoint origin"):
        client.complete(route, MESSAGES, stream=stream)
