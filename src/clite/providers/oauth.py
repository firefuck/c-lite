"""OAuth 2.0 PKCE and device code authorization for model providers.

Tokens are stored in ``<home>/auth.json`` (file mode 0600) and refreshed automatically before
they expire. Access tokens are registered as credentials so they are redacted from transcripts
and kept out of subprocess environments.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from clite.core.constants import get_home
from clite.core.errors import AuthError, ProviderError
from clite.core.io import atomic_write_json, read_json
from clite.core.redact import register_credential_value, unregister_credential_value
from clite.providers.base import ProviderProfile

logger = logging.getLogger(__name__)

AUTH_STORE_VERSION = 1
DEFAULT_PKCE_TIMEOUT = 120.0
DEFAULT_DEVICE_TIMEOUT = 300.0
DEFAULT_REFRESH_LEEWAY_SECONDS = 60.0

_LOCK = threading.Lock()


def get_auth_file_path() -> Path:
    """Path to the user's private OAuth credentials file."""
    return get_home() / "auth.json"


def load_auth_store() -> dict[str, Any]:
    """Read ``auth.json``, registering any stored access tokens as credentials."""
    path = get_auth_file_path()
    with _LOCK:
        raw = read_json(path, default=None)
        if not isinstance(raw, dict) or raw.get("version") != AUTH_STORE_VERSION:
            store: dict[str, Any] = {"version": AUTH_STORE_VERSION, "providers": {}}
        else:
            store = raw
            store.setdefault("providers", {})

        for data in store.get("providers", {}).values():
            if isinstance(data, dict):
                token = data.get("access_token")
                if token and isinstance(token, str):
                    register_credential_value(token)
        return store


def save_auth_store(store: dict[str, Any]) -> None:
    """Save ``store`` to ``auth.json`` with owner-only permissions (0600)."""
    path = get_auth_file_path()
    with _LOCK:
        store["version"] = AUTH_STORE_VERSION
        for data in store.get("providers", {}).values():
            if isinstance(data, dict):
                token = data.get("access_token")
                if token and isinstance(token, str):
                    register_credential_value(token)
        atomic_write_json(path, store, mode=0o600)


def get_provider_tokens(provider: str) -> dict[str, Any] | None:
    """Stored OAuth tokens and metadata for ``provider``, or ``None``."""
    store = load_auth_store()
    entry = store.get("providers", {}).get(provider)
    return dict(entry) if isinstance(entry, dict) else None


def save_provider_tokens(provider: str, data: dict[str, Any]) -> None:
    """Persist updated OAuth tokens for ``provider``."""
    store = load_auth_store()
    providers = store.setdefault("providers", {})
    providers[provider] = data
    save_auth_store(store)


def delete_provider_tokens(provider: str) -> bool:
    """Remove stored tokens for ``provider``. Returns ``True`` if present."""
    store = load_auth_store()
    providers = store.get("providers", {})
    if provider in providers:
        old_data = providers.pop(provider)
        if isinstance(old_data, dict):
            token = old_data.get("access_token")
            if token and isinstance(token, str):
                unregister_credential_value(token)
        save_auth_store(store)
        return True
    return False


def list_auth_statuses() -> dict[str, dict[str, Any]]:
    """Summary of OAuth state for all logged-in providers."""
    store = load_auth_store()
    now = time.time()
    result: dict[str, dict[str, Any]] = {}
    for name, data in store.get("providers", {}).items():
        if not isinstance(data, dict):
            continue
        expires_at = data.get("expires_at")
        is_expired = bool(expires_at and now >= float(expires_at))
        result[name] = {
            "logged_in": True,
            "expired": is_expired,
            "expires_at": expires_at,
            "has_refresh_token": bool(data.get("refresh_token")),
            "scope": data.get("scope", ""),
            "token_type": data.get("token_type", "Bearer"),
        }
    return result


def _http_post(
    url: str,
    *,
    form_data: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Execute an HTTP POST for token exchanges or device requests."""
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    body_bytes: bytes
    if json_data is not None:
        req_headers["Content-Type"] = "application/json"
        body_bytes = json.dumps(json_data).encode("utf-8")
    elif form_data is not None:
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"
        body_bytes = urllib.parse.urlencode(form_data).encode("utf-8")
    else:
        body_bytes = b""

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method="POST")  # noqa: S310 - the provider's token endpoint from its profile
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the provider's token endpoint from its profile
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}
    except urllib.error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw_error)
            if isinstance(parsed, dict):
                parsed["status_code"] = exc.code
                return parsed
        except json.JSONDecodeError:
            pass
        return {"error": f"HTTP {exc.code}", "status_code": exc.code, "message": raw_error}
    except Exception as exc:
        raise AuthError(f"OAuth request failed to {url}: {exc}") from exc


def get_valid_oauth_token(provider: str) -> str | None:
    """Return a usable access token, refreshing it first if close to expiring."""
    data = get_provider_tokens(provider)
    if not data or not data.get("access_token"):
        return None

    expires_at = data.get("expires_at")
    now = time.time()
    needs_refresh = expires_at is not None and now >= (float(expires_at) - DEFAULT_REFRESH_LEEWAY_SECONDS)

    if needs_refresh and data.get("refresh_token"):
        try:
            return refresh_oauth_token(provider)
        except AuthError as exc:
            logger.warning("Could not refresh OAuth token for %s: %s", provider, exc)
            return None

    if expires_at is not None and now >= float(expires_at):
        return None

    return str(data["access_token"])


def has_valid_token(provider: str) -> bool:
    """True when ``provider`` has a valid or refreshable OAuth token."""
    return get_valid_oauth_token(provider) is not None


def get_oauth_credential(provider: str) -> Any:
    """A :class:`~clite.providers.credentials.Credential` for ``provider`` if authenticated."""
    token = get_valid_oauth_token(provider)
    if not token:
        return None
    from clite.providers.credentials import Credential

    return Credential(name=f"oauth:{provider}", value=token)


def refresh_oauth_token(provider: str, profile: ProviderProfile | None = None) -> str:
    """Refresh an expiring token using its refresh token."""
    from clite.providers.registry import get_provider

    prof = profile or get_provider(provider)
    if prof is None:
        raise ProviderError(f"Unknown provider {provider!r}")

    data = get_provider_tokens(provider)
    if not data or not data.get("refresh_token"):
        raise AuthError(
            f"No refresh token available for {provider}. Run `clite auth login {provider}` to re-authenticate.",
            provider=provider,
            code="missing_refresh_token",
        )

    refresh_token = str(data["refresh_token"])
    resp = prof.refresh_oauth_token(refresh_token=refresh_token, http_post=_http_post)

    if "error" in resp or resp.get("status_code", 200) >= 400:
        err = resp.get("error") or "refresh_failed"
        desc = resp.get("error_description") or resp.get("message") or str(err)
        delete_provider_tokens(provider)
        raise AuthError(
            f"OAuth token refresh for {provider} was revoked or expired: {desc}. Run `clite auth login {provider}`.",
            provider=provider,
            code="token_revoked",
        )

    new_access = resp.get("access_token") or resp.get("key")
    if not new_access:
        raise AuthError(
            f"OAuth refresh response from {provider} did not contain an access token.",
            provider=provider,
            code="invalid_refresh_response",
        )

    updated: dict[str, Any] = {
        "access_token": new_access,
        "refresh_token": resp.get("refresh_token") or refresh_token,
        "token_type": resp.get("token_type") or data.get("token_type", "Bearer"),
        "scope": resp.get("scope") or data.get("scope", ""),
        "updated_at": time.time(),
    }
    if "expires_in" in resp:
        updated["expires_at"] = time.time() + float(resp["expires_in"])
    elif "expires_at" in data:
        updated["expires_at"] = data["expires_at"]

    save_provider_tokens(provider, updated)
    return str(new_access)


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            self.__class__.error = params["error"][0]
        if "code" in params:
            self.__class__.code = params["code"][0]
        if "state" in params:
            self.__class__.state = params["state"][0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = (
            "<!DOCTYPE html><html><head><title>Authentication Complete</title>"
            "<style>body { font-family: system-ui, sans-serif; padding: 2rem; text-align: center; background: #0f172a; color: #f8fafc; }</style>"
            "</head><body>"
            "<h2>Authentication Successful</h2>"
            "<p>You can close this tab and return to your terminal.</p>"
            "</body></html>"
        )
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


def login_pkce(
    provider: str,
    profile: ProviderProfile | None = None,
    *,
    open_browser: bool = True,
    timeout: float = DEFAULT_PKCE_TIMEOUT,
    callback_port: int = 0,
    on_auth_url: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Perform OAuth 2.0 PKCE login via a local HTTP callback server."""
    prof = _profile_for(provider, profile)
    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    _CallbackHandler.code = None
    _CallbackHandler.state = None
    _CallbackHandler.error = None

    server = HTTPServer(("127.0.0.1", callback_port or prof.oauth_callback_port), _CallbackHandler)
    server_port = server.server_address[1]
    redirect_path = prof.oauth_redirect_path or "/callback"
    redirect_uri = f"http://127.0.0.1:{server_port}{redirect_path}"

    auth_url = prof.build_oauth_authorize_url(
        redirect_uri=redirect_uri, code_challenge=code_challenge, state=state
    )
    if on_auth_url:
        on_auth_url(auth_url)
    if open_browser:
        _open_browser(auth_url)

    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()
    server_thread.join(timeout=timeout)
    server.server_close()

    if _CallbackHandler.error:
        raise AuthError(f"OAuth authorization error: {_CallbackHandler.error}", provider=provider)
    if not _CallbackHandler.code:
        raise AuthError(f"OAuth authorization timed out for {provider}.", provider=provider, code="timeout")
    if _CallbackHandler.state and _CallbackHandler.state != state:
        raise AuthError("OAuth state parameter mismatch.", provider=provider, code="state_mismatch")

    token_resp = prof.exchange_oauth_code(
        code=_CallbackHandler.code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        http_post=_http_post,
    )
    failure = _failure(token_resp, "token_exchange_failed")
    if failure is not None:
        err, desc = failure
        raise AuthError(f"OAuth code exchange failed: {desc}", provider=provider, code=err)

    access_token = token_resp.get("access_token") or token_resp.get("key")
    if not access_token:
        raise AuthError(
            f"OAuth token response from {provider} missing access token.",
            provider=provider,
            code="missing_access_token",
        )
    return _store_tokens(provider, token_resp, access_token, flow="pkce")


def login_device_code(
    provider: str,
    profile: ProviderProfile | None = None,
    *,
    open_browser: bool = True,
    timeout: float = DEFAULT_DEVICE_TIMEOUT,
    on_device_prompt: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Perform OAuth 2.0 Device Authorization Grant login."""
    prof = _profile_for(provider, profile)
    if not prof.oauth_device_code_url:
        raise AuthError(
            f"Provider {provider!r} does not have an OAuth device code URL configured.",
            provider=provider,
        )

    req_resp = prof.request_device_code(http_post=_http_post)
    failure = _failure(req_resp, "device_request_failed")
    if failure is not None:
        raise AuthError(f"Failed to request device code from {provider}: {failure[1]}", provider=provider)

    device_code = req_resp.get("device_code")
    user_code = req_resp.get("user_code")
    verification_uri = (
        req_resp.get("verification_uri")
        or req_resp.get("verification_url")
        or req_resp.get("verification_uri_complete", "")
    )
    verification_uri_complete = req_resp.get("verification_uri_complete", "")
    interval = float(req_resp.get("interval", 5.0))
    expires_in = float(req_resp.get("expires_in", 300.0))
    if not device_code or not user_code or not verification_uri:
        raise AuthError(
            f"Incomplete device code response from {provider}.", provider=provider, code="invalid_response"
        )

    if on_device_prompt:
        on_device_prompt(verification_uri, user_code, verification_uri_complete)
    if open_browser:
        _open_browser(verification_uri_complete or verification_uri)

    deadline = time.time() + min(timeout, expires_in)
    return _poll_device_token(provider, prof, device_code, deadline=deadline, interval=interval)


def _poll_device_token(
    provider: str, prof: ProviderProfile, device_code: str, *, deadline: float, interval: float
) -> dict[str, Any]:
    """Poll until the user approves the device code, the provider refuses it, or time runs out."""
    poll_interval = max(0.5, interval)
    while time.time() < deadline:
        time.sleep(poll_interval)
        token_resp = prof.poll_device_token(device_code=device_code, http_post=_http_post)

        if token_resp.get("status_code", 200) == 200 and "access_token" in token_resp:
            return _store_tokens(provider, token_resp, token_resp["access_token"], flow="device_code")

        err = token_resp.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            poll_interval += 5.0
            continue
        if err in ("expired_token", "access_denied"):
            raise AuthError(f"Device code authorization rejected: {err}", provider=provider, code=err)
        if "error" in token_resp:
            desc = token_resp.get("error_description") or err
            raise AuthError(f"Device code token exchange failed: {desc}", provider=provider)

    raise AuthError(f"Device code login timed out for {provider}.", provider=provider, code="timeout")


def _profile_for(provider: str, profile: ProviderProfile | None) -> ProviderProfile:
    from clite.providers.registry import get_provider

    prof = profile or get_provider(provider)
    if prof is None:
        raise ProviderError(f"Unknown provider {provider!r}")
    return prof


def _pkce_pair() -> tuple[str, str]:
    """``(code_verifier, code_challenge)`` for the S256 method."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return code_verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - no browser here; the user opens the URL shown
        pass


def _failure(response: dict[str, Any], default_code: str) -> tuple[str, str] | None:
    """``(error code, description)`` when an OAuth endpoint answered with an error."""
    if "error" not in response and response.get("status_code", 200) < 400:
        return None
    err = response.get("error") or default_code
    return str(err), str(response.get("error_description") or response.get("message") or err)


def _store_tokens(provider: str, response: dict[str, Any], access_token: str, *, flow: str) -> dict[str, Any]:
    """Save what a successful token response granted, and return it."""
    token_data: dict[str, Any] = {
        "access_token": access_token,
        "token_type": response.get("token_type", "Bearer"),
        "scope": response.get("scope", ""),
        "updated_at": time.time(),
        "flow": flow,
    }
    if "refresh_token" in response:
        token_data["refresh_token"] = response["refresh_token"]
    if "expires_in" in response:
        token_data["expires_at"] = time.time() + float(response["expires_in"])
    save_provider_tokens(provider, token_data)
    return token_data


def login(
    provider: str,
    flow: str | None = None,
    *,
    open_browser: bool = True,
    timeout: float | None = None,
    on_auth_url: Callable[[str], None] | None = None,
    on_device_prompt: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Authenticate with ``provider`` via PKCE or device code flow."""
    from clite.providers.registry import get_provider

    prof = get_provider(provider)
    if prof is None:
        raise ProviderError(f"Unknown provider {provider!r}")

    chosen_flow = (flow or prof.oauth_flow or "pkce").replace("-", "_")
    if chosen_flow == "device_code":
        return login_device_code(
            provider,
            prof,
            open_browser=open_browser,
            timeout=timeout or DEFAULT_DEVICE_TIMEOUT,
            on_device_prompt=on_device_prompt,
        )
    return login_pkce(
        provider,
        prof,
        open_browser=open_browser,
        timeout=timeout or DEFAULT_PKCE_TIMEOUT,
        on_auth_url=on_auth_url,
    )


def reset_oauth_state() -> None:
    """Clear memory caches for test isolation."""
    load_auth_store()
