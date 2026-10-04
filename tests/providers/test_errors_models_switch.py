"""Error classification, credential rotation, the model catalog, model switching, side tasks."""

from __future__ import annotations

import json

import pytest

from clite.core.config import load_config
from clite.providers.auxiliary import call_auxiliary, resolve_auxiliary_route
from clite.providers.credentials import get_credential_pool
from clite.providers.errors import FailoverReason, classify_api_error
from clite.providers.http import ProviderHTTPError
from clite.providers.model_switch import parse_model_input, switch_model
from clite.providers.models import DEFAULT_CONTEXT_LENGTH, get_context_length, list_models
from clite.providers.runtime import resolve_runtime_provider
from clite.providers.testing import ScriptedClient, mock_route, text_response


def _http(status, message="", error_type="", headers=None):
    return ProviderHTTPError(status, json.dumps({"error": {"message": message, "type": error_type}}), headers or {}, "u")


@pytest.mark.parametrize(
    ("error", "reason", "hints"),
    [
        (_http(401, "invalid api key"), FailoverReason.AUTH, {"should_rotate_credential", "should_fallback"}),
        (_http(403, "forbidden"), FailoverReason.AUTH, {"should_rotate_credential", "should_fallback"}),
        (_http(402, "payment required"), FailoverReason.BILLING, {"should_rotate_credential", "should_fallback"}),
        (_http(429, "You exceeded your current quota"), FailoverReason.BILLING, {"should_rotate_credential", "should_fallback"}),
        (_http(429, "slow down"), FailoverReason.RATE_LIMIT, {"retryable", "should_rotate_credential", "should_fallback"}),
        (_http(529, "Overloaded"), FailoverReason.OVERLOADED, {"retryable", "should_fallback"}),
        (_http(503, "bad gateway"), FailoverReason.SERVER_ERROR, {"retryable", "should_fallback"}),
        (_http(400, "This model's maximum context length is 8192 tokens"), FailoverReason.CONTEXT_OVERFLOW, {"should_compress"}),
        (_http(400, "prompt is too long: 250000 tokens > 200000"), FailoverReason.CONTEXT_OVERFLOW, {"should_compress"}),
        (_http(413, "request entity too large"), FailoverReason.PAYLOAD_TOO_LARGE, {"should_compress"}),
        (_http(404, "not found"), FailoverReason.MODEL_NOT_FOUND, {"should_fallback"}),
        (_http(400, "The model `gpt-x` does not exist"), FailoverReason.MODEL_NOT_FOUND, {"should_fallback"}),
        (_http(400, "messages.1: tool_result block must follow tool_use"), FailoverReason.FORMAT_ERROR, set()),
        (_http(400, "messages.5.content.0: Invalid `signature` in `thinking` block. The block is bound to a "
                    "different conversation."), FailoverReason.THINKING_SIGNATURE, {"should_drop_replay"}),
        (_http(400, "thinking blocks cannot be modified"), FailoverReason.THINKING_SIGNATURE, {"should_drop_replay"}),
        (_http(400, "invalid signature on the uploaded file"), FailoverReason.FORMAT_ERROR, set()),
        (TimeoutError("read timed out"), FailoverReason.TIMEOUT, {"retryable", "should_fallback"}),
        (ConnectionResetError("reset"), FailoverReason.TIMEOUT, {"retryable", "should_fallback"}),
        (InterruptedError(), FailoverReason.CANCELLED, set()),
        (ValueError("bug"), FailoverReason.UNKNOWN, set()),
    ],
)
def test_classification(error, reason, hints):
    classified = classify_api_error(error)
    assert classified.reason is reason
    actual = {name for name in ("retryable", "should_compress", "should_rotate_credential", "should_fallback",
                                "should_drop_replay") if getattr(classified, name)}
    assert actual == hints


def test_retry_after_headers():
    assert classify_api_error(_http(429, "x", headers={"Retry-After": "12"})).retry_after == 12.0
    assert classify_api_error(_http(429, "x", headers={"retry-after-ms": "1500"})).retry_after == 1.5
    assert classify_api_error(_http(429, "x", headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})).retry_after is None


def test_non_json_error_body_still_classifies():
    error = ProviderHTTPError(502, "<html>Bad Gateway</html>", {}, "u")
    assert classify_api_error(error).reason is FailoverReason.SERVER_ERROR
    assert "Bad Gateway" in error.message


# ── credential pool ──────────────────────────────────────────────────────────────────────


def test_pool_finds_numbered_keys_and_rotates(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", "key-one")
    monkeypatch.setenv("ACME_API_KEY_2", "key-two")
    monkeypatch.setenv("ACME_API_KEY_3", "key-one")  # duplicate value: ignored
    pool = get_credential_pool("acme", ("ACME_API_KEY",))
    assert [c.value for c in pool.candidates()] == ["key-one", "key-two"]
    first = pool.current()
    assert first.value == "key-one"
    second = pool.rotate(first)
    assert second.value == "key-two" and pool.current().value == "key-two"
    assert pool.rotate(second) is None  # nothing left
    assert pool.current() is not None  # still returns the one that frees up soonest


def test_pool_with_no_keys():
    assert get_credential_pool("acme", ("ACME_API_KEY",)).current() is None


def test_route_can_switch_credentials(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-one")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "key-two")
    route = resolve_runtime_provider("openrouter", "m")
    rotated = route.with_credential(get_credential_pool("openrouter", ("OPENROUTER_API_KEY",)).rotate(route.credential))
    assert rotated.api_key == "key-two" and rotated.headers["Authorization"] == "Bearer key-two"
    assert route.api_key == "key-one"  # the original route is untouched


# ── model catalog ────────────────────────────────────────────────────────────────────────


def test_models_are_fetched_live_then_served_from_cache(fake_api):
    fake_api.on("GET", "/v1/models", (200, {"data": [{"id": "vendor/a", "context_length": 64000}, {"id": "vendor/b"}]}))
    route = resolve_runtime_provider("openrouter", "vendor/a", base_url=fake_api.url + "/v1", api_key="k")
    assert [m.id for m in list_models("openrouter", route=route)] == ["vendor/a", "vendor/b"]
    assert [m.id for m in list_models("openrouter", route=route)] == ["vendor/a", "vendor/b"]
    assert len(fake_api.requests) == 1  # second call came from the cache
    assert get_context_length(route) == 64000


def test_fallback_models_when_the_catalog_is_unreachable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    models = list_models("anthropic")
    assert models and all(m.id.startswith("claude-") for m in models)
    assert list_models("mock")[0].id == "mock-1"
    assert list_models("unknown-provider") == []


def test_context_length_ladder(clite_home, monkeypatch):
    route = mock_route("mock-1")
    assert get_context_length(route) == 32_000  # declared by the profile
    assert get_context_length(mock_route("other-model", profile=None)) == DEFAULT_CONTEXT_LENGTH

    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  context_length: 50000\n")
    assert get_context_length(mock_route("mock-1")) == 50_000  # the user's override wins

    (clite_home / "config.yaml").write_text("model:\n  provider: openai\n  context_length: 50000\n")
    assert get_context_length(mock_route("mock-1")) == 32_000  # the override belongs to another provider


# ── model switching ──────────────────────────────────────────────────────────────────────


def test_parse_model_input():
    assert parse_model_input("vendor/model-x") == (None, "vendor/model-x")
    assert parse_model_input("mock:mock-2") == ("mock", "mock-2")
    assert parse_model_input("claude:claude-x") == ("anthropic", "claude-x")  # alias
    assert parse_model_input("qwen2.5:14b") == (None, "qwen2.5:14b")  # not a provider prefix
    assert parse_model_input("mock") == ("mock", None)
    assert parse_model_input("  ") == (None, None)


def test_switch_within_the_session_does_not_touch_config(clite_home):
    result = switch_model("mock:mock-2")
    assert result.success and (result.route.provider, result.route.model) == ("mock", "mock-2")
    assert not (clite_home / "config.yaml").exists()


def test_switch_keeps_the_current_provider_for_a_bare_model():
    result = switch_model("mock-7", current=mock_route("mock-1"))
    assert (result.route.provider, result.route.model) == ("mock", "mock-7")


def test_persisted_switch_drops_the_previous_endpoint_settings(clite_home):
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: custom\n  default: old\n  base_url: http://localhost:1/v1\n  api_mode: chat_completions\n"
    )
    result = switch_model("mock:mock-2", persist=True)
    assert result.persisted and "saved as default" in result.message
    assert load_config()["model"]["provider"] == "mock"
    assert load_config()["model"]["default"] == "mock-2"
    assert load_config()["model"]["base_url"] == ""  # back to the default: the stale URL is gone


def test_failed_switch_keeps_the_current_route():
    current = mock_route()
    result = switch_model("anthropic:claude-x", current=current)
    assert result.success is False and result.route is current
    assert "ANTHROPIC_API_KEY" in result.message


# ── auxiliary ────────────────────────────────────────────────────────────────────────────


def test_auxiliary_defaults_to_the_main_route(monkeypatch):
    main = mock_route("mock-1")
    assert resolve_auxiliary_route("compression", main) is main

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    claude = resolve_runtime_provider("anthropic", "claude-big")
    assert resolve_auxiliary_route("compression", claude).model == claude.profile.default_aux_model


def test_auxiliary_route_can_be_configured_per_task(clite_home):
    (clite_home / "config.yaml").write_text(
        "auxiliary:\n  compression: {provider: main, model: cheap-model}\n  title_generation: {provider: mock, model: mock-9}\n"
    )
    main = mock_route("mock-1")
    assert resolve_auxiliary_route("compression", main).model == "cheap-model"
    assert resolve_auxiliary_route("title_generation", main).model == "mock-9"


def test_unusable_auxiliary_route_falls_back_to_main(clite_home):
    (clite_home / "config.yaml").write_text("auxiliary:\n  compression: {provider: anthropic, model: claude-x}\n")
    main = mock_route()
    assert resolve_auxiliary_route("compression", main) is main


def test_call_auxiliary_returns_text_and_never_streams():
    client = ScriptedClient([text_response("  a summary  ")])
    assert call_auxiliary("compression", [{"role": "user", "content": "summarise"}], main_route=mock_route(), client=client) == "a summary"
    assert client.calls[0]["stream"] is False and client.calls[0]["tools"] is None
