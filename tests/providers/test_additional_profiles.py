"""First-wave provider declarations exercised through real routes and local HTTP."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from clite.core.errors import AuthError, ProviderError
from clite.providers.client import LLMClient
from clite.providers.registry import get_provider
from clite.providers.runtime import resolve_runtime_provider
from clite.providers.transports.types import RequestParams

# Expected public contracts, independent of the discovered profiles.
PROFILES = [
    ("xai", "https://api.x.ai/v1", "XAI_API_KEY", "grok-4.7", 500_000),
    ("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile", 131_072),
    ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-2603", 256_000),
    (
        "together",
        "https://api.together.ai/v1",
        "TOGETHER_API_KEY",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        131_072,
    ),
    (
        "fireworks",
        "https://api.fireworks.ai/inference/v1",
        "FIREWORKS_API_KEY",
        "accounts/fireworks/models/llama-v3p3-70b-instruct",
        131_072,
    ),
    (
        "nvidia",
        "https://integrate.api.nvidia.com/v1",
        "NVIDIA_API_KEY",
        "meta/llama-3.3-70b-instruct",
        128_000,
    ),
    ("zai", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY", "glm-4.7", 200_000),
    ("moonshot", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY", "kimi-k2.6", 256_000),
    ("lmstudio", "http://localhost:1234/v1", "", "loaded-model", None),
    ("vllm", "http://localhost:8000/v1", "", "served-model", None),
]


@pytest.mark.parametrize("name,url,key_env,model,context", PROFILES, ids=[p[0] for p in PROFILES])
@pytest.mark.parametrize("stream", [False, True])
def test_additional_profile_resolves_and_sends_chat_to_its_endpoint(
    fake_api,
    monkeypatch,
    name,
    url,
    key_env,
    model,
    context,
    stream,
):
    profile = get_provider(name, config={})
    assert profile is not None
    assert profile.base_url == url
    assert profile.env_vars == ((key_env,) if key_env else ())
    assert profile.base_url_env == name.upper() + "_BASE_URL"
    assert profile.get_model_context_length(model) == context
    assert profile.default_model == ""  # Choosing a provider must not silently choose a paid model.
    assert profile.fallback_models == ((model,) if key_env else ())
    assert profile.context_lengths == ({model: context} if key_env else {})
    if key_env:
        assert profile.auth_type == "api_key"
        with pytest.raises(AuthError, match=key_env):
            resolve_runtime_provider(name, model, config={})
        monkeypatch.setenv(key_env, "synthetic-key")
    else:
        assert profile.auth_type == "none" and profile.auto_select is False
        with pytest.raises(AuthError):
            resolve_runtime_provider(model=model, config={})
    with pytest.raises(ProviderError, match="No model selected"):
        resolve_runtime_provider(name, config={})
    original = resolve_runtime_provider(name, model, config={})
    assert (original.provider, original.model, original.api_mode, original.base_url) == (
        name,
        model,
        "chat_completions",
        url,
    )
    assert original.api_key == ("synthetic-key" if key_env else "")
    assert "synthetic-key" not in str(original.describe())

    # Preserve each vendor's path prefix, but never send a request outside loopback.
    local_url = fake_api.url + urlsplit(url).path
    monkeypatch.setenv(profile.base_url_env, local_url)
    if key_env:
        with pytest.raises(AuthError, match="different host"):
            resolve_runtime_provider(name, model, config={})
    route = resolve_runtime_provider(name, model, config={}, api_key="local-test-key" if key_env else None)
    assert route.base_url == local_url and original.base_url == url
    path = urlsplit(url).path + "/chat/completions"
    message = {"role": "assistant", "content": "hello"}
    usage = {"prompt_tokens": 3, "completion_tokens": 1}
    reply = (
        fake_api.sse(
            {"choices": [{"delta": message}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage},
            done=True,
        )
        if stream
        else {"choices": [{"message": message, "finish_reason": "stop"}], "usage": usage}
    )
    fake_api.on("POST", path, (200, reply))
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    tools = [
        {
            "type": "function",
            "function": {"name": "probe", "parameters": {"type": "object", "properties": {}}},
        }
    ]
    response = LLMClient().complete(
        route, messages, tools, params=RequestParams(max_tokens=64), stream=stream
    )
    assert response.content == "hello" and response.usage.output_tokens == 1
    assert len(fake_api.requests) == 1
    sent = fake_api.requests[0]
    assert (sent["method"], sent["path"]) == ("POST", path)
    assert sent["headers"].get("Authorization") == ("Bearer local-test-key" if key_env else None)
    body = {"model": model, "messages": messages, "tools": tools, "max_tokens": 64}
    if stream:
        body.update(stream=True, stream_options={"include_usage": True})
    assert sent["body"] == body


def test_fixed_sampling_model_omits_temperature_without_changing_other_models(fake_api):
    route = resolve_runtime_provider(
        "moonshot", "kimi-k2.6", base_url=fake_api.url + "/v1", api_key="test-key"
    )
    reply = (200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})
    fake_api.on("POST", "/v1/chat/completions", reply, reply)
    params = RequestParams(temperature=0.7)
    client = LLMClient()
    client.complete(route, [{"role": "user", "content": "hi"}], params=params, stream=False)
    client.complete(
        route.with_model("other-model"), [{"role": "user", "content": "hi"}], params=params, stream=False
    )
    assert "temperature" not in fake_api.requests[0]["body"]
    assert fake_api.requests[1]["body"]["temperature"] == 0.7


def test_setup_discovers_additional_profiles_without_a_static_provider_menu(monkeypatch, capsys):
    from clite.cli.main import main

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def stop_at_menu(prompt):
        assert prompt.startswith("Provider")
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", stop_at_menu)
    assert main(["setup"]) == 130
    output = capsys.readouterr().out
    for name, *_ in PROFILES:
        assert any(line.split()[1:2] == [name] for line in output.splitlines())
