"""Wire-format conversion, in both directions, for each protocol."""

from __future__ import annotations

import json

import pytest

from clite.providers.base import OMIT_TEMPERATURE, ProviderProfile
from clite.providers.runtime import RuntimeRoute
from clite.providers.transports.anthropic_messages import REPLAY_KEY, convert_messages, convert_tools
from clite.providers.transports.base import get_transport
from clite.providers.transports.types import RequestParams

TOOLS = [{"type": "function", "function": {"name": "terminal", "description": "run", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}]
CALL = {"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": '{"command": "ls"}'}}
HISTORY = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "list files", "_row_id": 1, "timestamp": 1.0},
    {"role": "assistant", "content": None, "tool_calls": [CALL], "reasoning": "thinking...", "finish_reason": "tool_calls", "_row_id": 2},
    {"role": "tool", "tool_call_id": "call_1", "name": "terminal", "content": '{"output": "a.txt"}', "_row_id": 3},
]


def _route(api_mode="chat_completions", **profile_fields):
    profile = ProviderProfile(name="p", base_url="https://api.test/v1", **profile_fields)
    return RuntimeRoute(provider="p", model="model-x", api_mode=api_mode, base_url="https://api.test/v1",
                        api_key="k", headers=profile.get_headers("k"), profile=profile)


# ── chat completions ─────────────────────────────────────────────────────────────────────


def test_chat_request_strips_internal_keys_and_keeps_the_protocol_ones():
    request = get_transport("chat_completions").build_request(_route(), HISTORY, TOOLS, RequestParams(), stream=False)
    assert request.url == "https://api.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer k"
    assert request.body["tools"] == TOOLS
    assert request.body["messages"][1] == {"role": "user", "content": "list files"}
    assert request.body["messages"][2] == {"role": "assistant", "content": None, "tool_calls": [CALL]}
    assert request.body["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "name": "terminal", "content": '{"output": "a.txt"}'}
    assert "stream" not in request.body


def test_chat_request_does_not_mutate_the_history():
    snapshot = json.dumps(HISTORY)
    get_transport("chat_completions").build_request(_route(), HISTORY, None, RequestParams(), stream=True)
    assert json.dumps(HISTORY) == snapshot


def test_chat_stream_request_asks_for_usage():
    body = get_transport("chat_completions").build_request(_route(), HISTORY, None, RequestParams(), stream=True).body
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert "tools" not in body


def test_chat_request_parameters_follow_the_profile():
    params = RequestParams(max_tokens=500, temperature=0.2)
    transport = get_transport("chat_completions")
    assert transport.build_request(_route(), HISTORY, None, params, stream=False).body["max_tokens"] == 500

    renamed = transport.build_request(_route(max_tokens_param="max_completion_tokens"), HISTORY, None, params, stream=False).body
    assert renamed["max_completion_tokens"] == 500 and "max_tokens" not in renamed

    assert transport.build_request(_route(fixed_temperature=1.0), HISTORY, None, params, stream=False).body["temperature"] == 1.0
    assert "temperature" not in transport.build_request(_route(fixed_temperature=OMIT_TEMPERATURE), HISTORY, None, params, stream=False).body


def test_chat_cache_marker_moves_onto_a_content_part():
    marker = {"type": "ephemeral"}
    messages = [{"role": "user", "content": "hi", "cache_control": marker},
                {"role": "tool", "tool_call_id": "c", "content": "result", "cache_control": marker}]
    wired = get_transport("chat_completions").build_request(_route(), messages, None, RequestParams(), stream=False).body["messages"]
    assert wired[0]["content"] == [{"type": "text", "text": "hi", "cache_control": marker}]
    assert wired[1]["content"] == [{"type": "text", "text": "result", "cache_control": marker}]
    assert all("cache_control" not in message for message in wired)


def test_chat_response_is_normalised():
    response = get_transport("chat_completions").parse_response({
        "model": "model-x",
        "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "reasoning_content": "hmm", "tool_calls": [CALL]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 60},
                  "completion_tokens_details": {"reasoning_tokens": 5}},
    })
    assert response.finish_reason == "tool_calls"
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [("call_1", "terminal", '{"command": "ls"}')]
    assert response.reasoning == "hmm"
    assert (response.usage.input_tokens, response.usage.cache_read_tokens, response.usage.prompt_tokens) == (40, 60, 100)
    assert response.usage.reasoning_tokens == 5


def test_chat_stream_assembles_text_and_fragmented_tool_calls():
    seen, thoughts = [], []
    accumulator = get_transport("chat_completions").stream_accumulator(seen.append, thoughts.append)
    chunks = [
        {"model": "model-x", "choices": [{"delta": {"role": "assistant", "reasoning": "let me "}}]},
        {"choices": [{"delta": {"reasoning": "think"}}]},
        {"choices": [{"delta": {"content": "Sure"}}]},
        {"choices": [{"delta": {"content": ", listing."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "terminal", "arguments": '{"comm'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'and": "ls"}'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_b", "function": {"name": "read_file", "arguments": "{}"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}},
    ]
    for chunk in chunks:
        assert accumulator.feed("message", json.dumps(chunk)) is True
    assert accumulator.feed("message", "[DONE]") is False
    response = accumulator.finish()
    assert seen == ["Sure", ", listing."] and thoughts == ["let me ", "think"]
    assert response.content == "Sure, listing." and response.reasoning == "let me think"
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("call_a", "terminal", '{"command": "ls"}'), ("call_b", "read_file", "{}")]
    assert response.finish_reason == "tool_calls" and response.usage.prompt_tokens == 9


def test_chat_stream_ignores_junk_lines():
    accumulator = get_transport("chat_completions").stream_accumulator()
    assert accumulator.feed("message", "not json") is True
    assert accumulator.finish().content is None


def test_assistant_message_round_trip():
    response = get_transport("chat_completions").parse_response(
        {"choices": [{"finish_reason": "stop", "message": {"content": "done", "tool_calls": [CALL]}}]})
    message = response.to_assistant_message()
    assert message["role"] == "assistant" and message["tool_calls"] == [CALL]
    assert message["finish_reason"] == "tool_calls"  # a response with tool calls is never "stop"


# ── responses ───────────────────────────────────────────────────────────────────────────


def test_responses_request_and_replay_preserve_items_without_mutating_history():
    transport = get_transport("responses")
    output = [
        {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "plan"}],
         "encrypted_content": "opaque=="},
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
         "phase": "commentary", "content": [{"type": "output_text", "text": "Listing.", "annotations": []}]},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "terminal",
         "arguments": '{"command": "ls"}', "status": "completed"},
    ]
    response = transport.parse_response({
        "status": "completed", "model": "model-x", "output": output,
        "usage": {"input_tokens": 100, "output_tokens": 20, "input_tokens_details": {"cached_tokens": 60},
                  "output_tokens_details": {"reasoning_tokens": 5}},
    })
    assert response.content == "Listing." and response.reasoning == "plan"
    assert response.finish_reason == "tool_calls" and response.model == "model-x"
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [("call_1", "terminal", '{"command": "ls"}')]
    assert (response.usage.input_tokens, response.usage.cache_read_tokens, response.usage.total_tokens) == (40, 60, 120)
    assert response.usage.reasoning_tokens == 5
    history = [*HISTORY[:2], response.to_assistant_message(), HISTORY[-1]]
    snapshot = json.dumps(history)
    request = transport.build_request(_route("responses"), history, TOOLS,
                                      RequestParams(max_tokens=200, temperature=0.2), stream=False)
    assert request.url == "https://api.test/v1/responses"
    assert request.headers["Authorization"] == "Bearer k"
    assert request.body["input"] == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "list files"}, *output,
        {"type": "function_call_output", "call_id": "call_1", "output": '{"output": "a.txt"}'},
    ]
    assert request.body["tools"] == [{"type": "function", **TOOLS[0]["function"], "strict": False}]
    assert request.body["store"] is False and request.body["stream"] is False
    assert request.body["include"] == ["reasoning.encrypted_content"]
    assert request.body["max_output_tokens"] == 200 and request.body["temperature"] == 0.2
    assert "previous_response_id" not in request.body and "messages" not in request.body
    assert json.dumps(history) == snapshot
    request.body["input"][2]["summary"][0]["text"] = "changed"
    output[0]["encrypted_content"] = "changed"
    assert json.dumps(history) == snapshot


def test_responses_converts_content_parts_and_rebuilds_messages_without_foreign_replay():
    history = [
        {"role": "developer", "content": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": [{"type": "text", "text": "look"},
         {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "low"}}]},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}], "tool_calls": [CALL],
         "provider_data": {"anthropic_blocks": [{"type": "thinking", "signature": "foreign"}]}},
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
    ]
    snapshot = json.dumps(history)
    body = get_transport("responses").build_request(_route("responses"), history, None, RequestParams(), stream=True).body
    assert body["input"] == [
        {"role": "developer", "content": [{"type": "input_text", "text": "sys"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "look"},
         {"type": "input_image", "image_url": "data:image/png;base64,AAAA", "detail": "low"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "ok", "annotations": []}]},
        {"type": "function_call", "call_id": "call_1", "name": "terminal", "arguments": '{"command": "ls"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "result"},
    ]
    assert "tools" not in body and json.dumps(history) == snapshot


def test_responses_profile_parameters_use_the_responses_shape_and_explicit_overrides():
    from clite.providers.runtime import resolve_runtime_provider

    route = resolve_runtime_provider("openai", "gpt-5-codex", api_key="test-key", config={})
    route.max_tokens = 321
    transport = get_transport("responses")
    params = RequestParams(reasoning_effort="high", show_reasoning=True)
    body = transport.build_request(route, HISTORY[:2], None, params, stream=True).body
    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert "reasoning_effort" not in body and "temperature" not in body
    assert body["max_output_tokens"] == 321
    assert "reasoning" not in transport.build_request(route, HISTORY[:2], None, RequestParams(), stream=False).body
    params.extra_body = {"max_output_tokens": 12}
    assert transport.build_request(route, HISTORY[:2], None, params, stream=True).body["max_output_tokens"] == 12


def test_responses_stream_assembles_indexed_items_and_uses_final_output_without_duplication():
    seen, thoughts = [], []
    accumulator = get_transport("responses").stream_accumulator(seen.append, thoughts.append)
    events = [
        ("response.created", {"response": {"model": "model-x"}}),
        ("response.output_item.added", {"output_index": 1, "item": {
            "type": "function_call", "id": "fc_1", "call_id": "c1", "name": "terminal", "arguments": ""}}),
        ("response.function_call_arguments.delta", {"output_index": 1, "delta": '{"comm'}),
        ("response.function_call_arguments.delta", {"output_index": 1, "delta": 'and":"ls"}'}),
        ("response.function_call_arguments.done", {"output_index": 1, "arguments": '{"command":"ls"}'}),
        ("response.output_text.delta", {"output_index": 2, "content_index": 0, "delta": "Hi"}),
        ("response.output_text.delta", {"output_index": 2, "content_index": 0, "delta": "!"}),
        ("response.reasoning_summary_text.delta", {"output_index": 0, "summary_index": 0, "delta": "plan"}),
        ("response.output_item.done", {"output_index": 0, "item": {
            "type": "reasoning", "id": "rs", "encrypted_content": "opaque", "summary": [{"type": "summary_text", "text": "plan"}]}}),
        ("response.output_item.done", {"output_index": 2, "item": {
            "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Hi!", "annotations": []}]}}),
    ]
    for event, data in events:
        assert accumulator.feed(event, json.dumps(data)) is True
    # A compatible endpoint may omit output in its terminal event; done items and argument
    # fragments must still be enough. The official final snapshot is tested end-to-end.
    assert accumulator.feed("response.completed", json.dumps({"response": {
        "status": "completed", "usage": {"input_tokens": 9, "output_tokens": 4}}})) is False
    response = accumulator.finish()
    assert seen == ["Hi", "!"] and thoughts == ["plan"]
    assert response.content == "Hi!" and response.reasoning == "plan" and response.model == "model-x"
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [("c1", "terminal", '{"command":"ls"}')]
    assert response.usage.total_tokens == 13
    assert [item["type"] for item in response.provider_data["responses_output"]] == ["reasoning", "function_call", "message"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(("code", "reason", "hint"), [
    ("context_length_exceeded", "context_overflow", "should_compress"),
    ("invalid_encrypted_content", "thinking_signature", "should_drop_replay"),
    ("rate_limit_exceeded", "rate_limit", "retryable"),
    ("server_error", "server_error", "retryable"),
    ("invalid_api_key", "auth", "should_rotate_credential"),
    ("model_not_found", "model_not_found", "should_fallback"),
    ("insufficient_quota", "billing", "should_rotate_credential"),
    ("invalid_request_error", "format_error", None),
])
def test_responses_failures_are_classified_from_the_code_even_with_a_generic_type(stream, code, reason, hint):
    from clite.providers.errors import classify_api_error
    from clite.providers.http import ProviderHTTPError

    payload = {"status": "failed", "error": {"type": "invalid_request_error", "code": code,
                                              "message": "Request failed; check the request."}}
    transport = get_transport("responses")
    with pytest.raises(ProviderHTTPError) as raised:
        if stream:
            transport.stream_accumulator().feed("response.failed", json.dumps({"response": payload}))
        else:
            transport.parse_response(payload)
    classified = classify_api_error(raised.value)
    assert classified.reason.value == reason
    if hint:
        assert getattr(classified, hint) is True
    else:
        assert not classified.should_drop_replay and not classified.retryable


@pytest.mark.parametrize(("detail", "reason"), [("max_output_tokens", "length"), ("content_filter", "content_filter")])
@pytest.mark.parametrize("stream", [False, True])
def test_responses_incomplete_output_never_dispatches_partial_tool_arguments(detail, reason, stream):
    payload = {"status": "incomplete", "incomplete_details": {"reason": detail}, "output": [
        {"type": "function_call", "call_id": "c", "name": "terminal", "arguments": '{"command":'},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "partial"}]},
    ]}
    transport = get_transport("responses")
    if stream:
        accumulator = transport.stream_accumulator()
        assert accumulator.feed("response.incomplete", json.dumps({"response": payload})) is False
        response = accumulator.finish()
    else:
        response = transport.parse_response(payload)
    assert response.finish_reason == reason and response.content == "partial"
    assert response.tool_calls == [] and response.provider_data is None


def test_responses_refusal_and_premature_stream_end_are_not_successful_empty_answers():
    from clite.providers.http import ProviderHTTPError

    transport = get_transport("responses")
    response = transport.parse_response({"status": "completed", "output": [
        {"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "Cannot help."}]}]})
    assert response.content == "Cannot help." and response.finish_reason == "content_filter"
    accumulator = transport.stream_accumulator()
    accumulator.feed("response.output_text.delta", json.dumps({"delta": "partial"}))
    with pytest.raises(ProviderHTTPError, match="ended before"):
        accumulator.finish()
    with pytest.raises(ProviderHTTPError):
        transport.stream_accumulator().feed("error", json.dumps({"type": "error", "code": "server_error", "message": "retry"}))


# ── anthropic messages ───────────────────────────────────────────────────────────────────


def test_anthropic_conversion_moves_system_out_and_wraps_tool_results():
    system, messages = convert_messages(HISTORY)
    assert system == [{"type": "text", "text": "You are helpful."}]
    assert messages == [
        {"role": "user", "content": [{"type": "text", "text": "list files"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1", "name": "terminal", "input": {"command": "ls"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": '{"output": "a.txt"}'}]},
    ]


def test_anthropic_conversion_merges_adjacent_same_role_messages():
    history = [
        {"role": "assistant", "content": None, "tool_calls": [CALL, {**CALL, "id": "call_2"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "one"},
        {"role": "tool", "tool_call_id": "call_2", "content": "two"},
        {"role": "user", "content": "and now?"},
    ]
    _, messages = convert_messages(history)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]  # a leading user turn is inserted
    assert [block["type"] for block in messages[2]["content"]] == ["tool_result", "tool_result", "text"]


def test_anthropic_conversion_replays_signed_thinking_blocks_verbatim():
    blocks = [{"type": "thinking", "thinking": "plan", "signature": "sig=="},
              {"type": "tool_use", "id": "call_1", "name": "terminal", "input": {"command": "ls"}}]
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": None, "tool_calls": [CALL], "provider_data": {REPLAY_KEY: blocks}}]
    _, messages = convert_messages(history)
    assert messages[1]["content"] == blocks


def test_anthropic_cache_markers_land_on_blocks():
    marker = {"type": "ephemeral", "ttl": "1h"}
    system, messages = convert_messages([
        {"role": "system", "content": [{"type": "text", "text": "sys", "cache_control": marker}]},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None, "tool_calls": [CALL], "cache_control": marker},
        {"role": "tool", "tool_call_id": "call_1", "content": "r", "cache_control": marker},
    ])
    assert system[0]["cache_control"] == marker
    assert messages[1]["content"][-1]["cache_control"] == marker
    assert messages[2]["content"][0]["cache_control"] == marker


def test_anthropic_images_and_empty_content():
    _, messages = convert_messages([
        {"role": "user", "content": [{"type": "text", "text": "look"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": ""},
    ])
    assert messages[0]["content"][1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    assert messages[2]["content"][0]["text"]  # an empty text block would be rejected


def test_anthropic_tools_use_input_schema():
    assert convert_tools(TOOLS) == [{"name": "terminal", "description": "run", "input_schema": TOOLS[0]["function"]["parameters"]}]


def test_anthropic_request_shape():
    request = get_transport("anthropic_messages").build_request(
        _route("anthropic_messages", auth_header="x-api-key", auth_scheme=""), HISTORY, TOOLS,
        RequestParams(temperature=0.3), stream=True)
    assert request.url == "https://api.test/v1/messages"
    assert request.headers["x-api-key"] == "k" and request.headers["anthropic-version"]
    assert request.body["max_tokens"] > 0 and request.body["stream"] is True
    assert request.body["system"][0]["text"] == "You are helpful."
    assert request.body["temperature"] == 0.3


def test_anthropic_request_omits_temperature_when_thinking():
    class Thinking(ProviderProfile):
        def build_extra_body(self, **kwargs):
            return {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}

    profile = Thinking(name="p", base_url="https://api.test")
    route = RuntimeRoute(provider="p", model="m", api_mode="anthropic_messages", base_url="https://api.test", profile=profile)
    body = get_transport("anthropic_messages").build_request(route, HISTORY, None, RequestParams(temperature=0.3), stream=False).body
    assert "temperature" not in body and body["output_config"] == {"effort": "high"}


def test_the_profile_decides_whether_a_temperature_is_sent():
    class NoSampling(ProviderProfile):
        def resolve_temperature(self, model, requested):
            return None if model.startswith("locked") else requested

    profile = NoSampling(name="p", base_url="https://api.test")
    for mode in ("anthropic_messages", "chat_completions"):
        def body(model, mode=mode):
            route = RuntimeRoute(provider="p", model=model, api_mode=mode, base_url="https://api.test", profile=profile)
            return get_transport(mode).build_request(route, HISTORY, None, RequestParams(temperature=0.3), stream=False).body

        assert "temperature" not in body("locked-model")
        assert body("open-model")["temperature"] == 0.3


def test_both_transports_tell_the_profile_whether_reasoning_is_shown():
    seen = []

    class Recording(ProviderProfile):
        def build_extra_body(self, *, show_reasoning=False, **kwargs):
            seen.append(show_reasoning)
            return {}

    profile = Recording(name="p", base_url="https://api.test")
    for mode in ("anthropic_messages", "chat_completions"):
        route = RuntimeRoute(provider="p", model="m", api_mode=mode, base_url="https://api.test", profile=profile)
        get_transport(mode).build_request(route, HISTORY, None, RequestParams(show_reasoning=True), stream=False)
        get_transport(mode).build_request(route, HISTORY, None, RequestParams(), stream=False)
    assert seen == [True, False, True, False]


def test_anthropic_response_is_normalised():
    response = get_transport("anthropic_messages").parse_response({
        "model": "claude-x", "stop_reason": "tool_use",
        "content": [{"type": "thinking", "thinking": "plan", "signature": "sig"},
                    {"type": "text", "text": "Listing."},
                    {"type": "tool_use", "id": "toolu_1", "name": "terminal", "input": {"command": "ls"}}],
        "usage": {"input_tokens": 10, "output_tokens": 30, "cache_read_input_tokens": 90, "cache_creation_input_tokens": 5,
                  "output_tokens_details": {"thinking_tokens": 12}},
    })
    assert response.content == "Listing." and response.reasoning == "plan"
    assert response.finish_reason == "tool_calls"
    assert json.loads(response.tool_calls[0].arguments) == {"command": "ls"}
    assert response.provider_data[REPLAY_KEY][0]["signature"] == "sig"
    assert (response.usage.input_tokens, response.usage.prompt_tokens, response.usage.reasoning_tokens) == (10, 105, 12)


def test_anthropic_plain_text_response_needs_no_replay_data():
    response = get_transport("anthropic_messages").parse_response(
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "hi"}], "usage": {}})
    assert response.provider_data is None and response.finish_reason == "stop"


def test_anthropic_stream_assembles_thinking_text_and_tool_input():
    seen, thoughts = [], []
    accumulator = get_transport("anthropic_messages").stream_accumulator(seen.append, thoughts.append)
    events = [
        ("message_start", {"type": "message_start", "message": {"model": "claude-x", "usage": {"input_tokens": 7, "cache_read_input_tokens": 3}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "plan"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("ping", {"type": "ping"}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "On it"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("content_block_start", {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "terminal", "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"command"'}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": ': "ls"}'}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 2}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 42}}),
    ]
    for name, payload in events:
        assert accumulator.feed(name, json.dumps(payload)) is True
    assert accumulator.feed("message_stop", json.dumps({"type": "message_stop"})) is False
    response = accumulator.finish()
    assert seen == ["On it"] and thoughts == ["plan"]
    assert response.content == "On it" and response.finish_reason == "tool_calls"
    assert json.loads(response.tool_calls[0].arguments) == {"command": "ls"}
    assert response.provider_data[REPLAY_KEY][0] == {"type": "thinking", "thinking": "plan", "signature": "sig"}
    assert (response.usage.prompt_tokens, response.usage.output_tokens) == (10, 42)
