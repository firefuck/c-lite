"""Streamable HTTP transport for the MCP client. Standard library only.

MCP over Streamable HTTP is JSON-RPC 2.0 carried in HTTP POSTs to one endpoint:

* the first ``initialize`` POST gets an ``Mcp-Session-Id`` response header, which every
  later request must echo back;
* a POST whose body is a request returns either a plain ``application/json`` body or a
  single-event ``text/event-stream`` whose ``data:`` line holds the reply;
* a POST whose body is only a notification is answered with ``202 Accepted`` and no body;
* the server may send requests and notifications on a standing ``GET`` stream, but this
  client only needs the reply to what it asked, so it does not open one.

Auth headers come from ``.env``: an ``Authorization`` header is written as
``Authorization: "Bearer ${MY_TOKEN}"`` in the server spec, and the ``${NAME}`` reference is
resolved through :func:`clite.core.env.get_secret`, then the header value is registered as a
credential so it is stripped from commands the agent runs and redacted from what the model
reads. A literal token is accepted but discouraged; a value that looks like a bare secret
name is not guessed at.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from clite.core.env import SecretSpec, get_secret, register_secret

# ``${NAME}`` / ``$NAME`` inside a header value means "read NAME from .env".
_REFERENCE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
DEFAULT_HTTP_TIMEOUT_SECONDS = 60.0


class McpError(Exception):
    """Anything that stops an MCP server from answering: bad spec, dead process, HTTP error."""


def resolve_header_value(value: str, *, header: str, server: str, register: bool = True) -> str:
    """Expand ``${NAME}`` references in a header value from ``.env``.

    A missing variable is an error, not an empty header: sending ``Authorization: Bearer `` and
    getting a bare 401 would send the user hunting for the wrong problem.
    """
    missing: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        secret = get_secret(name)
        if not secret:
            missing.append(name)
            return ""
        if register:
            register_secret(SecretSpec(name, f"MCP server {server!r} header {header}", category="tool"))
        return secret

    resolved = _REFERENCE_RE.sub(substitute, value)
    if missing:
        raise McpError(
            f"mcp server {server!r}: header {header!r} references {', '.join(missing)}, "
            f"which is not set in .env. Add it with `clite setup`, or write the value literally."
        )
    return resolved


def build_headers(spec: dict[str, Any], name: str, *, register: bool = True) -> dict[str, str]:
    """Request headers from ``spec['headers']``, with ``.env`` references resolved."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    for header, value in (spec.get("headers") or {}).items():
        headers[str(header)] = resolve_header_value(
            str(value), header=str(header), server=name, register=register
        )
    return headers


class HttpTransport:
    """JSON-RPC over one Streamable HTTP endpoint.

    ``send`` posts one message and returns the reply object (or ``None`` for a notification,
    which is answered with 202 and no body). The transport owns the session id, so the server
    can hand it out once and the client never has to thread it through every call.
    """

    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name = name
        self.spec = spec
        self.url = str(spec.get("url") or "").rstrip("/")
        self.timeout = float(spec.get("timeout") or DEFAULT_HTTP_TIMEOUT_SECONDS)
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self._closed = True
        self._reachable = True  # flipped by the last request; HTTP has no process to watch

    def start(self) -> None:
        if not self.url:
            raise McpError(f"mcp server {self.name!r} has a url/command entry that is empty")
        # Nothing to spawn: the session id arrives with the first reply. Mark live so the
        # handshake goes through `send`.
        self._closed = False

    def send(self, message: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any] | None:
        if self._closed:
            raise McpError(f"mcp server {self.name!r} is not connected")
        headers = build_headers(self.spec, self.name)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.protocol_version:
            headers["mcp-protocol-version"] = self.protocol_version
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                session_id = response.headers.get("mcp-session-id")
                if session_id:
                    self.session_id = session_id
                if response.status == 202:
                    return None
                raw = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("content-type", "")
                self._reachable = True
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:  # noqa: BLE001 - the status code is the useful part
                pass
            hint = f": {detail[:300]}" if detail else ""
            if exc.code in (401, 403):
                raise McpError(
                    f"mcp server {self.name!r} rejected the request ({exc.code}){hint}. "
                    f"Check the headers and the token in .env."
                ) from exc
            # A 4xx/5xx means the endpoint answered, so it is reachable; only a transport-level
            # failure (below) counts as down.
            self._reachable = True
            raise McpError(f"mcp server {self.name!r} returned HTTP {exc.code}{hint}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._reachable = False
            raise McpError(f"mcp server {self.name!r} is unreachable: {exc}") from exc
        if not raw.strip():
            return None
        if "text/event-stream" in content_type:
            return self._parse_sse(raw)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McpError(f"mcp server {self.name!r} sent a non-JSON reply: {raw[:200]}") from exc
        return parsed if isinstance(parsed, dict) else None

    def _parse_sse(self, raw: str) -> dict[str, Any] | None:
        """The first ``data:`` payload of an event-stream body."""
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise McpError(f"mcp server {self.name!r} sent a non-JSON event: {payload[:200]}") from exc
            return parsed if isinstance(parsed, dict) else None
        return None

    def close(self) -> None:
        self._closed = True

    def is_alive(self) -> bool:
        # HTTP has no process to watch: a connected transport is alive until a request fails at
        # the transport level, which flips `_reachable` back on the next success.
        return not self._closed and self._reachable
