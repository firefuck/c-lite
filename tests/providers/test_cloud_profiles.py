"""Cloud profiles use real local HTTP; credentials and remote replies are synthetic."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from clite.core.errors import AuthError
from clite.providers.client import LLMClient
from clite.providers.registry import get_provider
from clite.providers.runtime import resolve_runtime_provider


@pytest.mark.parametrize("stream", [False, True])
def test_azure_deployment_and_api_version_are_encoded_in_the_request_url(fake_api, monkeypatch, stream):
    profile = get_provider("azure", config={})
    assert profile is not None
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://resource.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "cloud-key")
    original = resolve_runtime_provider("azure", "my deployment", config={})
    assert original.base_url == "https://resource.openai.azure.com"
    with pytest.raises(AuthError):
        resolve_runtime_provider("azure", "my deployment", base_url=fake_api.url, config={})
    route = resolve_runtime_provider(
        "azure",
        "my deployment",
        api_key="local-key",
        base_url=fake_api.url + "?api-version=2024-10-21",
        config={},
    )
    path = "/openai/deployments/my%20deployment/chat/completions?api-version=2024-10-21"
    reply = (
        fake_api.sse({"choices": [{"delta": {"content": "ok"}}]}, done=True)
        if stream
        else {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        }
    )
    fake_api.on("POST", path, (200, reply))
    messages = [{"role": "user", "content": "héllo"}]
    assert LLMClient().complete(route, messages, stream=stream).content == "ok"
    sent = fake_api.requests[0]
    assert sent["headers"]["api-key"] == "local-key"
    assert "Authorization" not in sent["headers"]
    assert sent["body"]["messages"] == messages
    assert "model" not in sent["body"]
    assert route.with_model("next").model == "next" and original.model == "my deployment"


@pytest.mark.parametrize("stream", [False, True])
def test_bedrock_signs_the_exact_utf8_body_and_session_token(fake_api, monkeypatch, stream):
    pytest.importorskip("botocore")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "synthetic-session")
    profile = get_provider("bedrock", config={})
    assert profile is not None
    url = "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"
    original = resolve_runtime_provider("bedrock", "openai.gpt-oss-120b-1:0", base_url=url, config={})
    assert original.base_url == url
    with pytest.raises(AuthError):
        resolve_runtime_provider("bedrock", "model", base_url=fake_api.url, config={})
    credential = json.dumps(
        {
            "access_key": "AKIDEXAMPLE",
            "secret_key": "synthetic-secret",
            "session_token": "synthetic-session",
            "region": "us-west-2",
        }
    )
    route = resolve_runtime_provider(
        "bedrock",
        "openai.gpt-oss-120b-1:0",
        base_url=fake_api.url + "/openai/v1",
        api_key=credential,
        config={},
    )
    path = "/openai/v1/chat/completions"
    reply = (
        fake_api.sse({"choices": [{"delta": {"content": "ok"}}]}, done=True)
        if stream
        else {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        }
    )
    fake_api.on("POST", path, (200, reply))
    assert LLMClient().complete(route, [{"role": "user", "content": "héllo"}], stream=stream).content == "ok"
    sent = fake_api.requests[0]
    headers = {k.lower(): v for k, v in sent["headers"].items()}
    assert headers["x-amz-security-token"] == "synthetic-session"
    auth = headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    scope = auth.split("Credential=AKIDEXAMPLE/", 1)[1].split(",", 1)[0]
    date, region, service, end = scope.split("/")
    assert (region, service, end) == ("us-west-2", "bedrock", "aws4_request")
    signed = auth.split("SignedHeaders=", 1)[1].split(",", 1)[0]
    payload_hash = hashlib.sha256(sent["raw_body"]).hexdigest()
    canonical = (
        "POST\n"
        + path
        + "\n\n"
        + "".join(key + ":" + headers[key] + "\n" for key in signed.split(";"))
        + "\n"
        + signed
        + "\n"
        + payload_hash
    )
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        + headers["x-amz-date"]
        + "\n"
        + scope
        + "\n"
        + hashlib.sha256(canonical.encode()).hexdigest()
    )
    key = b"AWS4synthetic-secret"
    for part in (date, region, service, end):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    assert auth.endswith("Signature=" + hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest())
    assert "synthetic-secret" not in str(route.describe())
    route.base_url = "https://other.invalid"
    with pytest.raises(AuthError):
        LLMClient().complete(route, [], stream=False)


@pytest.fixture
def service_account():
    pytest.importorskip("google.auth")
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return {
        "type": "service_account",
        "client_email": "test@example.iam.gserviceaccount.com",
        "private_key": pem,
        "private_key_id": "test-id",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@pytest.mark.parametrize("stream", [False, True])
def test_vertex_refreshes_service_account_token_before_each_request(
    fake_api, monkeypatch, service_account, stream
):
    from urllib.parse import parse_qs

    from google.auth import jwt

    from clite.providers.http import HttpClient

    profile = get_provider("vertex", config={})
    assert profile is not None
    secret = json.dumps(service_account)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", secret)
    url = "https://us-central1-aiplatform.googleapis.com/v1/projects/project/locations/us-central1/endpoints/openapi"
    original = resolve_runtime_provider("vertex", "google/gemini-2.0-flash-001", base_url=url, config={})
    assert original.base_url == url
    with pytest.raises(AuthError):
        resolve_runtime_provider("vertex", "model", base_url=fake_api.url, config={})
    route = resolve_runtime_provider(
        "vertex",
        "google/gemini-2.0-flash-001",
        api_key=secret,
        base_url=fake_api.url + "/v1/projects/project/locations/us-central1/endpoints/openapi",
        config={},
    )
    assertions = []
    fake_api.on(
        "POST",
        "/token",
        (200, {"access_token": "token-1", "expires_in": 3600, "token_type": "Bearer"}),
        (200, {"access_token": "token-2", "expires_in": 3600, "token_type": "Bearer"}),
    )

    class TokenEndpoint(HttpClient):
        def request_json(self, method, url, body=None, headers=None, **kwargs):
            if url == "https://oauth2.googleapis.com/token":
                assert method == "POST" and isinstance(body, bytes)
                form = parse_qs(body.decode())
                assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
                assertion = form["assertion"][0]
                claims = jwt.decode(assertion, verify=False)
                assert claims["iss"] == service_account["client_email"]
                assert claims["scope"] == "https://www.googleapis.com/auth/cloud-platform"
                assert claims["aud"] == url and claims["exp"] > claims["iat"]
                # Verify a real RSA signature, not just the decoded claims.
                from cryptography.hazmat.primitives import serialization

                private = serialization.load_pem_private_key(service_account["private_key"].encode(), None)
                public = private.public_key().public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                )
                assert jwt.decode(assertion, certs=public) == claims
                assertions.append(assertion)
                return super().request_json(method, fake_api.url + "/token", body, headers, **kwargs)
            return super().request_json(method, url, body, headers, **kwargs)

    path = "/v1/projects/project/locations/us-central1/endpoints/openapi/chat/completions"
    reply = (
        fake_api.sse({"choices": [{"delta": {"content": "ok"}}]}, done=True)
        if stream
        else {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        }
    )
    fake_api.on("POST", path, (200, reply))
    client = LLMClient(TokenEndpoint())
    for _ in range(2):
        assert client.complete(route, [{"role": "user", "content": "hello"}], stream=stream).content == "ok"
    assert len(assertions) == 2
    inference = [r for r in fake_api.requests if r["path"] == path]
    exchanges = [r for r in fake_api.requests if r["path"] == "/token"]
    assert len(exchanges) == 2
    assert all(
        parse_qs(r["raw_body"].decode())["assertion"][0] == assertion
        for r, assertion in zip(exchanges, assertions, strict=True)
    )
    assert [r["headers"]["Authorization"] for r in inference] == ["Bearer token-1", "Bearer token-2"]
    assert inference[0]["body"]["model"] == "google/gemini-2.0-flash-001"
    assert "private_key" not in str(route.describe())
    route.base_url = "https://other.invalid"
    with pytest.raises(AuthError):
        client.complete(route, [], stream=False)
    assert len(assertions) == 2


@pytest.mark.parametrize("name", ["azure", "bedrock", "vertex"])
def test_cloud_profiles_are_discoverable_without_extras_and_do_not_invent_models(monkeypatch, name):
    import builtins

    original_import = builtins.__import__

    def no_sdk(module, *args, **kwargs):
        if module.startswith(("google", "botocore")):
            raise ImportError("optional SDK absent")
        return original_import(module, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    profile = get_provider(name, config={})
    assert profile is not None
    assert profile.default_model == "" and profile.fallback_models == () and profile.context_lengths == {}
    assert profile.auto_select is False and profile.supports_model_listing is False


def test_setup_discovers_all_cloud_profiles_without_network(monkeypatch, capsys):
    from clite.cli.main import main

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def stop(prompt):
        assert prompt.startswith("Provider")
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", stop)
    assert main(["setup"]) == 130
    output = capsys.readouterr().out
    for name in ("azure", "bedrock", "vertex"):
        assert any(line.split()[1:2] == [name] for line in output.splitlines())


@pytest.mark.parametrize(
    "name,url,values",
    [
        ("azure", "https://resource.openai.azure.com", {"AZURE_OPENAI_API_KEY": "key-example"}),
        (
            "bedrock",
            "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
            {
                "AWS_ACCESS_KEY_ID": "access-example",
                "AWS_SECRET_ACCESS_KEY": "secret-example",
                "AWS_SESSION_TOKEN": "session-example",
            },
        ),
        (
            "vertex",
            "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1/endpoints/openapi",
            {
                "GOOGLE_SERVICE_ACCOUNT_JSON": '{"type":"service_account","client_email":"test@example.com","private_key":"private-example","token_uri":"https://oauth2.googleapis.com/token"}'
            },
        ),
    ],
)
def test_cloud_credentials_obey_secret_scope_and_are_registered(name, url, values, monkeypatch):
    from clite.core.env import secret_names, secret_scope

    profile = get_provider(name, config={})
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    assert set(values) <= secret_names()
    with secret_scope({}):
        assert not profile.is_configured()
        with pytest.raises(AuthError):
            resolve_runtime_provider(name, "model", base_url=url, config={})
    with secret_scope(values):
        assert profile.is_configured()
        route = resolve_runtime_provider(name, "model", base_url=url, config={})
        assert route.credential_pool() is None if name != "azure" else route.credential_pool() is not None
        assert all(value not in str(route.describe()) for value in values.values())


@pytest.mark.parametrize(
    "name,secret",
    [
        ("bedrock", "not-json"),
        ("bedrock", '{"access_key":"secret-leak"}'),
        ("vertex", "not-json"),
        ("vertex", '{"type":"authorized_user","refresh_token":"secret-leak"}'),
        (
            "vertex",
            '{"type":"service_account","client_email":"a","private_key":"secret-leak","token_uri":"https://evil.invalid"}',
        ),
    ],
)
def test_malformed_cloud_credentials_fail_closed_without_echoing_secrets(fake_api, name, secret):
    with pytest.raises(AuthError) as error:
        resolve_runtime_provider(name, "model", api_key=secret, base_url=fake_api.url, config={})
    assert secret not in str(error.value) and "secret-leak" not in str(error.value)
    assert fake_api.requests == []


@pytest.mark.parametrize(
    "name,sdk,extra", [("bedrock", "botocore", "bedrock"), ("vertex", "google", "vertex")]
)
def test_missing_cloud_extra_gives_an_actionable_error_before_http(
    fake_api, monkeypatch, service_account, name, sdk, extra
):
    import builtins

    from clite.core.errors import ProviderError

    secret = json.dumps(
        service_account
        if name == "vertex"
        else {
            "access_key": "a",
            "secret_key": "b",
            "region": "us-east-1",
        }
    )
    route = resolve_runtime_provider(name, "model", api_key=secret, base_url=fake_api.url, config={})
    original_import = builtins.__import__

    def no_sdk(module, *args, **kwargs):
        if module.startswith(sdk):
            raise ImportError("optional SDK absent")
        return original_import(module, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    with pytest.raises(ProviderError, match=r"Install c-lite\[" + extra):
        LLMClient().complete(route, [], stream=False)
    assert fake_api.requests == []


def test_vertex_token_errors_are_sanitized_and_never_send_inference(fake_api, service_account):
    from clite.providers.http import HttpClient, ProviderHTTPError

    class BrokenTokenEndpoint(HttpClient):
        def request_json(self, *args, **kwargs):
            raise ProviderHTTPError(400, "private-secret-echo", {}, "https://oauth2.googleapis.com/token")

    route = resolve_runtime_provider(
        "vertex", "model", api_key=json.dumps(service_account), base_url=fake_api.url, config={}
    )
    with pytest.raises(AuthError) as error:
        LLMClient(BrokenTokenEndpoint()).complete(route, [], stream=False)
    assert "private-secret-echo" not in str(error.value)
    assert fake_api.requests == []


@pytest.mark.parametrize("query", ["", "?api-version=2099-01-01"])
def test_azure_model_switch_rebuilds_deployment_url_and_preserves_tools(fake_api, query):
    from clite.providers.transports.types import RequestParams

    version = "2099-01-01" if query else "2024-10-21"
    route = resolve_runtime_provider(
        "azure", "first", api_key="key", base_url=fake_api.url + query, config={}
    )
    client = LLMClient()
    tools = [{"type": "function", "function": {"name": "probe", "parameters": {"type": "object"}}}]
    for selected in (route, route.with_model("second")):
        path = f"/openai/deployments/{selected.model}/chat/completions?api-version={version}"
        fake_api.on("POST", path, (200, {"choices": [{"message": {"content": "ok"}}]}))
        client.complete(
            selected,
            [{"role": "user", "content": "hi"}],
            tools,
            params=RequestParams(max_tokens=17),
            stream=False,
        )
    assert [r["body"] for r in fake_api.requests] == [
        {"messages": [{"role": "user", "content": "hi"}], "tools": tools, "max_tokens": 17},
    ] * 2
    assert route.model == "first"


@pytest.mark.parametrize(
    "suffix", ["/bad", "?unknown=1", "?api-version=", "?api-version=a&api-version=b", "#fragment"]
)
def test_azure_rejects_malformed_resource_urls_before_http(fake_api, suffix):
    from clite.core.errors import ProviderError

    route = resolve_runtime_provider(
        "azure", "model", api_key="key", base_url=fake_api.url + suffix, config={}
    )
    with pytest.raises(ProviderError):
        LLMClient().complete(route, [], stream=False)
    assert fake_api.requests == []


@pytest.mark.parametrize(
    "name,url",
    [
        ("bedrock", "http://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"),
        ("bedrock", "https://bedrock-runtime.us-east-1.amazonaws.com.evil.invalid/openai/v1"),
        ("bedrock", "https://bedrock-runtime.us-east-1.amazonaws.com:444/openai/v1"),
        (
            "vertex",
            "http://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/l/endpoints/openapi",
        ),
        (
            "vertex",
            "https://aiplatform.googleapis.com.evil.invalid/v1/projects/p/locations/l/endpoints/openapi",
        ),
        ("vertex", "https://aiplatform.googleapis.com:444/v1/projects/p/locations/l/endpoints/openapi"),
    ],
)
def test_cloud_environment_credentials_refuse_lookalike_or_insecure_endpoints(name, url):
    with pytest.raises(AuthError, match="endpoint"):
        resolve_runtime_provider(name, "model", base_url=url, config={})


@pytest.mark.parametrize("name", ["azure", "bedrock", "vertex"])
def test_cloud_profiles_reject_unsupported_protocol_overrides_before_http(fake_api, service_account, name):
    from clite.core.errors import ProviderError

    secret = (
        "key"
        if name == "azure"
        else json.dumps(
            service_account
            if name == "vertex"
            else {
                "access_key": "a",
                "secret_key": "b",
                "region": "us-east-1",
            }
        )
    )
    route = resolve_runtime_provider(
        name,
        "model",
        api_key=secret,
        base_url=fake_api.url,
        config={"model": {"provider": name, "api_mode": "responses"}},
    )
    with pytest.raises(ProviderError, match="chat_completions"):
        LLMClient().complete(route, [], stream=False)
    assert fake_api.requests == []


def test_vertex_token_exchange_preserves_cancellation(fake_api, service_account):
    from clite.providers.http import Cancelled, HttpClient

    class CancelledExchange(HttpClient):
        def request_json(self, *args, **kwargs):
            kwargs["cancel"].cancel()
            raise Cancelled()

    route = resolve_runtime_provider(
        "vertex", "model", api_key=json.dumps(service_account), base_url=fake_api.url, config={}
    )
    with pytest.raises(InterruptedError, match="cancelled"):
        LLMClient(CancelledExchange()).complete(route, [], stream=False)
    assert fake_api.requests == []
