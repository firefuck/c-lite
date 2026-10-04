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

MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def _route(fake_api, provider="openai", model="model-x"):
    return resolve_runtime_provider(provider, model, base_url=fake_api.url + "/v1", api_key="test-key")


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
