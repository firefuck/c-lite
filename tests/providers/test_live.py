"""Against the real provider APIs. Every test skips unless its provider's key is set.

    ANTHROPIC_API_KEY=... OPENAI_API_KEY=... pytest tests/providers/test_live.py -m network

``CLITE_LIVE_ANTHROPIC_MODEL`` / ``CLITE_LIVE_OPENAI_MODEL`` / ``CLITE_LIVE_OPENAI_BASE_URL``
/ ``CLITE_LIVE_OPENAI_RESPONSES_MODEL`` pick other targets (the last one for any OpenAI-compatible endpoint). Each test spends a few
cents. CI sets no keys, so there everything here is skipped.

Not covered here because they cannot be triggered on demand: rate limits and refusals.
"""

from __future__ import annotations

import os
import threading

import pytest

from clite.agent import AgentCallbacks
from clite.core.config import load_config
from clite.providers.client import LLMClient
from clite.providers.errors import FailoverReason, classify_api_error
from clite.providers.runtime import resolve_runtime_provider
from clite.providers.transports.types import RequestParams
from clite.runtime import build_agent
from clite.tools.registry import registry, tool_result

pytestmark = pytest.mark.network

# The autouse fixture clears credentials from the environment before each test, so the keys
# are captured once at import time and handed to each route explicitly.
_KEYS = {name: os.environ.get(name, "") for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
_ANTHROPIC_MODEL = os.environ.get("CLITE_LIVE_ANTHROPIC_MODEL", "claude-fable-5-1")
_ANTHROPIC_LEGACY_MODEL = "claude-haiku-4-5-20251001"
_OPENAI_MODEL = os.environ.get("CLITE_LIVE_OPENAI_MODEL", "gpt-5-mini")
_OPENAI_BASE_URL = os.environ.get("CLITE_LIVE_OPENAI_BASE_URL", "")
_OPENAI_RESPONSES_MODEL = os.environ.get("CLITE_LIVE_OPENAI_RESPONSES_MODEL", "gpt-5-codex")

TARGETS = [
    pytest.param("anthropic", _ANTHROPIC_MODEL, id="anthropic-current"),
    pytest.param("anthropic", _ANTHROPIC_LEGACY_MODEL, id="anthropic-4.5"),
    pytest.param("openai", _OPENAI_MODEL, id="openai-compatible"),
]
MESSAGES = [
    {"role": "system", "content": "Answer in as few words as possible."},
    {"role": "user", "content": "Say the word: pineapple"},
]
ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers and return the sum.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
}


def _key(provider: str) -> str:
    key = _KEYS["ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"]
    if not key:
        pytest.skip(f"no key for {provider}")
    return key


def _route(provider: str, model: str, *, api_key: str | None = None):
    base_url = _OPENAI_BASE_URL if provider == "openai" and _OPENAI_BASE_URL else None
    return resolve_runtime_provider(provider, model, api_key=api_key or _key(provider), base_url=base_url)


@pytest.mark.parametrize(("provider", "model"), TARGETS)
def test_text_streams_in_pieces_and_reports_usage(provider, model):
    deltas: list[str] = []
    response = LLMClient().complete(_route(provider, model), MESSAGES, on_delta=deltas.append)
    assert "pineapple" in (response.content or "").lower()
    assert deltas and "".join(deltas) == response.content
    assert response.finish_reason == "stop"
    assert response.usage.output_tokens > 0 and response.usage.prompt_tokens > 0


@pytest.mark.parametrize(("provider", "model"), TARGETS)
def test_one_tool_round_and_a_parallel_round(provider, model):
    route = _route(provider, model)
    single = LLMClient().complete(
        route, [*MESSAGES[:1], {"role": "user", "content": "Use the add tool for 2 + 3."}], [ADD_TOOL]
    )
    assert [call.name for call in single.tool_calls] == ["add"] and single.finish_reason == "tool_calls"
    parallel = LLMClient().complete(
        route,
        [
            *MESSAGES[:1],
            {"role": "user", "content": "Call the add tool twice in one response: 1 + 2 and 3 + 4."},
        ],
        [ADD_TOOL],
    )
    assert len(parallel.tool_calls) >= 2


@pytest.mark.parametrize(("provider", "model"), TARGETS[:1])
def test_the_second_call_reads_the_prompt_cache(provider, model):
    # Anthropic caches only prefixes above a minimum size; repeat a long system prompt.
    system = "You are a terse assistant. " + "Reference text that never changes. " * 400
    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        },
        {"role": "user", "content": "Reply with: ok"},
    ]
    route = _route(provider, model)
    LLMClient().complete(route, messages, stream=False)
    second = LLMClient().complete(route, messages, stream=False)
    assert second.usage.cache_read_tokens > 0


@pytest.mark.parametrize(("provider", "model"), TARGETS)
def test_a_stream_can_be_cancelled_midway(provider, model):
    cancel = threading.Event()
    pieces: list[str] = []

    def on_delta(text: str) -> None:
        pieces.append(text)
        cancel.set()

    long_task = [*MESSAGES[:1], {"role": "user", "content": "Count from 1 to 400, one number per line."}]
    with pytest.raises(InterruptedError):
        LLMClient().complete(_route(provider, model), long_task, on_delta=on_delta, cancel=cancel)
    assert pieces


@pytest.mark.parametrize(("provider", "model"), TARGETS[:1])
def test_signed_thinking_survives_tool_rounds_a_second_turn_compress_and_model_switch(
    provider, model, clite_home
):
    """Replay of signed reasoning: several tool rounds, a second turn, /compress, /model."""
    calls: list[dict] = []

    def add(args, ctx=None):
        calls.append(args)
        return tool_result(sum=int(args["a"]) + int(args["b"]))

    registry.register("add", "live-probe", ADD_TOOL["function"], add, origin="test")
    config = load_config()
    config["agent"]["reasoning_effort"] = "high"
    config["display"]["show_reasoning"] = True
    reasoning: list[str] = []
    agent = build_agent(
        route=_route(provider, model),
        toolsets=["live-probe"],
        config=config,
        auto_title=False,
        callbacks=AgentCallbacks(on_reasoning=reasoning.append),
    )
    try:
        first = agent.run_conversation(
            "Use the add tool to compute 2+3, then add 10 to that result with the tool "
            "again, then tell me the final number."
        )
        assert first.completed and "15" in first.final_response and len(calls) >= 2
        assert any(m.get("provider_data") for m in agent.messages if m.get("role") == "assistant")
        assert reasoning, "show_reasoning should surface summarized thinking text"

        second = agent.run_conversation("Now use the tool to add 5 to the final number.")
        assert second.completed and "20" in second.final_response

        agent.compress_context(focus="keep the numbers")
        assert agent.run_conversation("What was the last number? Reply with just it.").completed

        agent.switch_model(_route(provider, _ANTHROPIC_LEGACY_MODEL))
        assert not any(m.get("provider_data") for m in agent.messages)
        assert agent.run_conversation("Reply with: done").completed
    finally:
        agent.close()


@pytest.mark.parametrize("stream", [False, True])
def test_openai_responses_replays_reasoning_across_two_tool_rounds(stream, clite_home):
    calls: list[dict] = []

    def add(args, ctx=None):
        calls.append(args)
        return tool_result(sum=int(args["a"]) + int(args["b"]))

    registry.register("add", "live-responses", ADD_TOOL["function"], add, origin="test")
    config = load_config()
    config["agent"]["reasoning_effort"] = "low"
    config["fallback_providers"] = []
    route = _route("openai", _OPENAI_RESPONSES_MODEL)
    assert route.api_mode == "responses"
    agent = build_agent(
        route=route, toolsets=["live-responses"], config=config, auto_title=False, stream=stream
    )
    try:
        result = agent.run_conversation(
            "Use add for 2+3. After that result arrives, use add again to add 10. "
            "Then reply with only the final number."
        )
        assert result.completed and "15" in result.final_response and len(calls) >= 2
        assert any(m.get("provider_data") for m in agent.messages if m.get("role") == "assistant")
    finally:
        agent.close()


@pytest.mark.parametrize(("provider", "model"), TARGETS[::2])
def test_real_errors_are_classified(provider, model):
    route = _route(provider, model)

    def error_of(route, messages, params=None):
        try:
            LLMClient().complete(route, messages, params=params, stream=False)
        except Exception as exc:  # the classification is what is being tested
            return classify_api_error(exc)
        raise AssertionError("the call was expected to fail")

    assert (
        error_of(_route(provider, model, api_key="sk-wrong-key-for-a-live-test"), MESSAGES).reason
        is FailoverReason.AUTH
    )
    assert (
        error_of(route.with_model("no-such-model-clite-live"), MESSAGES).reason
        is FailoverReason.MODEL_NOT_FOUND
    )
    huge = [MESSAGES[0], {"role": "user", "content": "word " * 1_200_000}]
    assert error_of(route, huge).reason in (FailoverReason.CONTEXT_OVERFLOW, FailoverReason.PAYLOAD_TOO_LARGE)
    assert error_of(route, MESSAGES, RequestParams(max_tokens=-1)).reason is FailoverReason.FORMAT_ERROR
