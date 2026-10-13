"""Tests for OAuth 2.0 PKCE and device code flows, token storage, and clite auth."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from clite.cli.main import main
from clite.core.errors import AuthError
from clite.core.redact import redact
from clite.providers.base import ProviderProfile
from clite.providers.credentials import get_credential_pool
from clite.providers.oauth import (
    get_auth_file_path,
    get_provider_tokens,
    get_valid_oauth_token,
    login_device_code,
    login_pkce,
    refresh_oauth_token,
    save_provider_tokens,
)
from clite.providers.registry import register_provider
from clite.providers.runtime import resolve_runtime_provider
from clite.tools.approval import detect_self_access
from clite.tools.environments.local import build_child_env
from clite.tools.file_safety import read_denied_reason, write_denied_reason


class MockOAuthServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, MockOAuthHandler)
        self.code_verifier_received: str | None = None
        self.code_challenge_received: str | None = None
        self.device_polls = 0
        self.revoked = False
        self.last_redirect_uri: str | None = None
        self.last_params: dict[str, list[str]] = {}


class MockOAuthHandler(BaseHTTPRequestHandler):
    server: MockOAuthServer

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/oauth/authorize":
            # Authorization endpoint for PKCE
            self.server.last_params = params
            redirect_uri = params.get("redirect_uri", [""])[0]
            callback_url = params.get("callback_url", [""])[0]
            target_callback = redirect_uri or callback_url
            state = params.get("state", [""])[0]
            self.server.code_challenge_received = params.get("code_challenge", [""])[0]
            self.server.last_redirect_uri = target_callback

            # Simulate browser redirection back to local callback
            cb_parsed = urllib.parse.urlsplit(target_callback)
            query = f"code=auth_code_pkce_123&state={state}"
            cb_url = f"{cb_parsed.scheme}://{cb_parsed.netloc}{cb_parsed.path}?{query}"

            def _redirect() -> None:
                time.sleep(0.05)
                try:
                    urllib.request.urlopen(cb_url, timeout=5)
                except Exception:
                    pass

            threading.Thread(target=_redirect, daemon=True).start()

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Authorizing...</body></html>")
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)

        if parsed.path == "/oauth/token":
            # Token endpoint
            form = urllib.parse.parse_qs(body.decode("utf-8"))
            grant_type = form.get("grant_type", [""])[0]

            if grant_type == "authorization_code":
                code_verifier = form.get("code_verifier", [""])[0]
                self.server.code_verifier_received = code_verifier

                resp = {
                    "access_token": "at_pkce_success_999",
                    "refresh_token": "rt_pkce_success_999",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                self._send_json(200, resp)
                return

            if grant_type == "refresh_token":
                refresh_token = form.get("refresh_token", [""])[0]
                if self.server.revoked or refresh_token == "revoked_rt":
                    self._send_json(
                        400,
                        {"error": "invalid_grant", "error_description": "Token revoked"},
                    )
                    return

                resp = {
                    "access_token": "at_refreshed_new_888",
                    "refresh_token": "rt_refreshed_new_888",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                self._send_json(200, resp)
                return

            if grant_type == "urn:ietf:params:oauth:grant-type:device_code":
                self.server.device_polls += 1
                if self.server.device_polls < 2:
                    self._send_json(400, {"error": "authorization_pending"})
                    return
                resp = {
                    "access_token": "at_device_success_777",
                    "refresh_token": "rt_device_success_777",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                self._send_json(200, resp)
                return

        elif parsed.path == "/oauth/device/code":
            resp = {
                "device_code": "dev_code_abc",
                "user_code": "USER-999",
                "verification_uri": "http://127.0.0.1/verify",
                "interval": 0.05,
                "expires_in": 120,
            }
            self._send_json(200, resp)
            return

        elif parsed.path == "/api/v1/auth/keys":
            # OpenRouter PKCE endpoint
            data = json.loads(body.decode("utf-8"))
            if data.get("code") == "auth_code_pkce_123":
                self._send_json(200, {"key": "sk-or-v1-pkce-key-12345678"})
                return

        self._send_json(404, {"error": "not_found"})

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def mock_oauth_server():
    server = MockOAuthServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_pkce_login_flow_and_file_mode(mock_oauth_server, clite_home):
    port = mock_oauth_server.server_address[1]
    profile = ProviderProfile(
        name="test_oauth_pkce",
        display_name="Test OAuth PKCE",
        auth_type="oauth",
        base_url=f"http://127.0.0.1:{port}/v1",
        oauth_flow="pkce",
        oauth_client_id="test_client_id",
        oauth_authorize_url=f"http://127.0.0.1:{port}/oauth/authorize",
        oauth_token_url=f"http://127.0.0.1:{port}/oauth/token",
    )
    register_provider(profile)

    def _visit(url: str) -> None:
        urllib.request.urlopen(url, timeout=5)

    tokens = login_pkce("test_oauth_pkce", profile, open_browser=False, timeout=10, on_auth_url=_visit)
    assert tokens["access_token"] == "at_pkce_success_999"
    assert tokens["refresh_token"] == "rt_pkce_success_999"

    # Verify verifier matched S256 challenge
    verifier = mock_oauth_server.code_verifier_received
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert mock_oauth_server.code_challenge_received == expected_challenge

    auth_file = get_auth_file_path()
    assert auth_file.is_file()

    # Permissions check: 0600 on POSIX
    if sys.platform != "win32":
        mode = stat.S_IMODE(auth_file.stat().st_mode)
        assert mode == 0o600

    stored = get_provider_tokens("test_oauth_pkce")
    assert stored is not None
    assert stored["access_token"] == "at_pkce_success_999"


def test_pkce_token_auto_refresh(mock_oauth_server, clite_home):
    port = mock_oauth_server.server_address[1]
    profile = ProviderProfile(
        name="test_refresh_provider",
        auth_type="oauth",
        base_url=f"http://127.0.0.1:{port}/v1",
        oauth_flow="pkce",
        oauth_client_id="test_client_id",
        oauth_token_url=f"http://127.0.0.1:{port}/oauth/token",
    )
    register_provider(profile)

    # Save an expiring token
    save_provider_tokens(
        "test_refresh_provider",
        {
            "access_token": "old_expiring_token",
            "refresh_token": "rt_pkce_success_999",
            "expires_at": time.time() + 10.0,  # expiring within leeway
        },
    )

    # Calling get_valid_oauth_token automatically refreshes it
    token = get_valid_oauth_token("test_refresh_provider")
    assert token == "at_refreshed_new_888"

    stored = get_provider_tokens("test_refresh_provider")
    assert stored["access_token"] == "at_refreshed_new_888"
    assert stored["refresh_token"] == "rt_refreshed_new_888"


def test_pkce_token_revocation(mock_oauth_server, clite_home):
    port = mock_oauth_server.server_address[1]
    profile = ProviderProfile(
        name="test_revoked_provider",
        auth_type="oauth",
        base_url=f"http://127.0.0.1:{port}/v1",
        oauth_token_url=f"http://127.0.0.1:{port}/oauth/token",
    )
    register_provider(profile)

    mock_oauth_server.revoked = True
    save_provider_tokens(
        "test_revoked_provider",
        {
            "access_token": "old_token",
            "refresh_token": "revoked_rt",
            "expires_at": time.time() - 10.0,  # expired
        },
    )

    with pytest.raises(AuthError) as exc_info:
        refresh_oauth_token("test_revoked_provider", profile)
    assert "revoked" in str(exc_info.value).lower()

    # After revocation failure, invalid tokens are cleared
    assert get_provider_tokens("test_revoked_provider") is None


def test_device_code_login_and_refresh(mock_oauth_server, clite_home):
    port = mock_oauth_server.server_address[1]
    profile = ProviderProfile(
        name="test_device_provider",
        auth_type="oauth",
        base_url=f"http://127.0.0.1:{port}/v1",
        oauth_flow="device_code",
        oauth_client_id="test_client_id",
        oauth_device_code_url=f"http://127.0.0.1:{port}/oauth/device/code",
        oauth_token_url=f"http://127.0.0.1:{port}/oauth/token",
    )
    register_provider(profile)

    tokens = login_device_code("test_device_provider", profile, open_browser=False, timeout=10)
    assert tokens["access_token"] == "at_device_success_777"
    assert tokens["refresh_token"] == "rt_device_success_777"
    assert tokens["flow"] == "device_code"

    # Refresh works for device code tokens too
    refreshed = refresh_oauth_token("test_device_provider", profile)
    assert refreshed == "at_refreshed_new_888"


def test_auth_json_security_in_file_tools_and_commands(clite_home):
    auth_file = get_auth_file_path()
    auth_file.write_text('{"version": 1, "providers": {}}')

    # 1. read_denied_reason rejects auth.json
    reason = read_denied_reason(auth_file)
    assert reason is not None
    assert "credentials" in reason.lower()

    # 2. write_denied_reason rejects auth.json
    w_reason = write_denied_reason(auth_file)
    assert w_reason is not None
    assert "credentials" in w_reason.lower()

    # 3. detect_self_access flags clite auth commands
    assert detect_self_access("clite auth login openrouter") is not None
    assert detect_self_access("clite auth logout openrouter") is not None
    assert detect_self_access("clite auth status") is not None


def test_access_token_is_redacted_and_kept_from_child_env(clite_home):
    secret_token = "secret_access_token_9876543210"
    save_provider_tokens(
        "test_prov",
        {"access_token": secret_token, "refresh_token": "rt_123"},
    )

    # 1. Exact token value is redacted
    text = f"The token is {secret_token} and Bearer {secret_token}"
    redacted = redact(text)
    assert secret_token not in redacted
    assert "[REDACTED]" in redacted

    # 2. Token value is stripped from child environment
    os.environ["SOME_INADVERTENT_KEY"] = secret_token
    try:
        env = build_child_env()
        assert "SOME_INADVERTENT_KEY" not in env
        assert all(secret_token not in v for v in env.values())
    finally:
        os.environ.pop("SOME_INADVERTENT_KEY", None)


def test_credential_pool_and_route_integration(mock_oauth_server, clite_home):
    port = mock_oauth_server.server_address[1]
    profile = ProviderProfile(
        name="test_pool_oauth",
        auth_type="oauth",
        base_url=f"http://127.0.0.1:{port}/v1",
        default_model="test-model",
    )
    register_provider(profile)

    # Before login: missing oauth error
    with pytest.raises(AuthError) as err:
        resolve_runtime_provider("test_pool_oauth", "test-model")
    assert "clite auth login" in str(err.value)

    # Store OAuth token
    save_provider_tokens(
        "test_pool_oauth",
        {"access_token": "token_for_route_12345"},
    )

    # Now credential pool returns it
    pool = get_credential_pool("test_pool_oauth", ())
    candidate = pool.current()
    assert candidate is not None
    assert candidate.name == "oauth:test_pool_oauth"
    assert candidate.value == "token_for_route_12345"

    # Route resolves with Authorization: Bearer <token>
    route = resolve_runtime_provider("test_pool_oauth", "test-model")
    assert route.api_key == "token_for_route_12345"
    assert route.headers.get("Authorization") == "Bearer token_for_route_12345"


def test_clite_auth_subcommands(mock_oauth_server, clite_home, capsys, monkeypatch):
    port = mock_oauth_server.server_address[1]
    profile = ProviderProfile(
        name="cli_prov",
        auth_type="oauth",
        base_url=f"http://127.0.0.1:{port}/v1",
        oauth_flow="pkce",
        oauth_authorize_url=f"http://127.0.0.1:{port}/oauth/authorize",
        oauth_token_url=f"http://127.0.0.1:{port}/oauth/token",
    )
    register_provider(profile)

    # Monkeypatch webbrowser.open to automatically simulate visiting the authorize URL
    def _open(url: str) -> bool:
        threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=5), daemon=True).start()
        return True

    monkeypatch.setattr("webbrowser.open", _open)

    # 1. Status with nothing logged in
    assert main(["auth", "status"]) == 0
    out, _ = capsys.readouterr()
    assert "No OAuth providers authenticated" in out

    # 2. Login via CLI
    assert main(["auth", "login", "cli_prov"]) == 0
    out, _ = capsys.readouterr()
    assert "Successfully authenticated with cli_prov" in out

    # 3. Status shows logged in
    assert main(["auth", "status"]) == 0
    out, _ = capsys.readouterr()
    assert "cli_prov: logged in" in out

    # 4. JSON status
    assert main(["auth", "status", "--json"]) == 0
    out, _ = capsys.readouterr()
    data = json.loads(out)
    assert data["cli_prov"]["logged_in"] is True

    # 5. Logout
    assert main(["auth", "logout", "cli_prov"]) == 0
    out, _ = capsys.readouterr()
    assert "Logged out from cli_prov" in out

    # 6. Status after logout
    assert main(["auth", "status"]) == 0
    out, _ = capsys.readouterr()
    assert "No OAuth providers authenticated" in out


def test_openrouter_pkce_quirks(mock_oauth_server, clite_home):
    port = mock_oauth_server.server_address[1]
    # Configure OpenRouter-style PKCE
    import importlib

    openrouter_mod = importlib.import_module("clite.bundled.plugins.model-providers.openrouter")
    OpenRouterProfile = openrouter_mod.OpenRouterProfile

    or_profile = OpenRouterProfile(
        name="test_openrouter_custom",
        base_url=f"http://127.0.0.1:{port}/v1",
        oauth_authorize_url=f"http://127.0.0.1:{port}/oauth/authorize",
        oauth_token_url=f"http://127.0.0.1:{port}/api/v1/auth/keys",
    )
    register_provider(or_profile)

    def _visit(url: str) -> None:
        urllib.request.urlopen(url, timeout=5)

    tokens = login_pkce(
        "test_openrouter_custom", or_profile, open_browser=False, timeout=10, on_auth_url=_visit
    )
    assert tokens["access_token"] == "sk-or-v1-pkce-key-12345678"
    assert "callback_url" in mock_oauth_server.last_params


def test_a_token_endpoint_answering_with_a_non_object_is_kept_as_raw_text(fake_api):
    from clite.providers.oauth import _http_post

    fake_api.on("POST", "/token", (200, ["not", "an", "object"]))
    answer = _http_post(f"{fake_api.url}/token", form_data={"grant_type": "x"})
    assert answer == {"raw": '["not", "an", "object"]'}
