"""The HTTP seam for model calls: standard library only, cancellable, proxy-aware.

Why not a third-party client: a model call is a POST and a server-sent-event stream, and the
one thing the agent truly needs from the client is to abort a call from another thread the
moment the user interrupts. ``http.client`` gives direct access to the socket, which makes
that reliable. Everything that talks to a model goes through :class:`HttpClient`, so swapping
the implementation later touches one file.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import threading
import urllib.request
from base64 import b64encode
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

from clite import __version__

USER_AGENT = f"clite/{__version__}"
DEFAULT_TIMEOUT = 600.0
CONNECT_TIMEOUT = 30.0


class ProviderHTTPError(Exception):
    """A non-2xx response (or an error event inside a stream)."""

    def __init__(self, status: int, body: str, headers: dict[str, str], url: str) -> None:
        self.status = status
        self.body = body
        self.headers = {key.lower(): value for key, value in headers.items()}
        self.url = url
        super().__init__(f"HTTP {status}: {self.message[:300]}")

    @property
    def payload(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.body)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @property
    def message(self) -> str:
        error = self.payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or self.body)
        if isinstance(error, str):
            return error
        return str(self.payload.get("message") or self.body or "")

    @property
    def error_type(self) -> str:
        error = self.payload.get("error")
        return str(error.get("type") or error.get("code") or "") if isinstance(error, dict) else ""


class Cancelled(Exception):
    """The call was aborted through its :class:`CancelHandle`."""


class CancelHandle:
    """Lets another thread abort an in-flight request by shutting its socket."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self.cancelled = False

    def attach(self, sock: socket.socket | None) -> None:
        """Remember the request's socket.

        The socket is captured right after the request is sent: once the response arrives,
        ``http.client`` may drop its own reference (``Connection: close``) while the response
        keeps reading from the same descriptor.
        """
        with self._lock:
            self._sock = sock
            cancelled = self.cancelled
        if cancelled:
            self._shutdown(sock)

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            sock = self._sock
        self._shutdown(sock)

    @staticmethod
    def _shutdown(sock: socket.socket | None) -> None:
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


@dataclass
class SSEEvent:
    event: str
    data: str


def _is_loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _proxy_for(url: str) -> str | None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    # A local model server (Ollama, vLLM, LM Studio) is never reachable through a proxy.
    if _is_loopback(host) or urllib.request.proxy_bypass(host):
        return None
    return urllib.request.getproxies().get(parts.scheme)


def _open_connection(url: str, timeout: float) -> tuple[http.client.HTTPConnection, str]:
    """A connection for ``url`` and the request target to use on it."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError(f"unsupported URL: {url!r}")
    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    proxy = _proxy_for(url)
    context = ssl.create_default_context() if secure else None
    if proxy is None:
        connection: http.client.HTTPConnection = (
            http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
            if secure else http.client.HTTPConnection(host, port, timeout=timeout)
        )
        return connection, target
    proxy_parts = urlsplit(proxy if "://" in proxy else "http://" + proxy)
    proxy_host = proxy_parts.hostname or ""
    proxy_port = proxy_parts.port or (443 if proxy_parts.scheme == "https" else 8080)
    proxy_headers = {}
    if proxy_parts.username:
        credentials = f"{unquote(proxy_parts.username)}:{unquote(proxy_parts.password or '')}".encode()
        proxy_headers["Proxy-Authorization"] = "Basic " + b64encode(credentials).decode()
    if secure:
        connection = http.client.HTTPSConnection(proxy_host, proxy_port, timeout=timeout, context=context)
        connection.set_tunnel(host, port, headers=proxy_headers)
        return connection, target
    connection = http.client.HTTPConnection(proxy_host, proxy_port, timeout=timeout)
    connection._clite_proxy_headers = proxy_headers  # type: ignore[attr-defined]
    return connection, url


class HttpClient:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def _send(self, method: str, url: str, body: dict[str, Any] | None, headers: dict[str, str],
              timeout: float | None, cancel: CancelHandle | None, accept: str) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
        # Connecting gets a short timeout of its own; the (long) read timeout only bounds the
        # silence between bytes once the request is on its way.
        connection, target = _open_connection(url, CONNECT_TIMEOUT)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request_headers = {"User-Agent": USER_AGENT, "Accept": accept, **headers}
        request_headers.update(getattr(connection, "_clite_proxy_headers", {}))
        try:
            if cancel is not None and cancel.cancelled:
                raise Cancelled()
            connection.connect()
            connection.sock.settimeout(timeout or self.timeout)
            if cancel is not None:
                cancel.attach(connection.sock)
            connection.request(method, target, body=payload, headers=request_headers)
            response = connection.getresponse()
        except Cancelled:
            connection.close()
            raise
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            if cancel is not None and cancel.cancelled:
                raise Cancelled() from exc
            raise
        if response.status >= 400:
            text = response.read().decode("utf-8", errors="replace")
            response_headers = dict(response.getheaders())
            connection.close()
            raise ProviderHTTPError(response.status, text, response_headers, url)
        if 300 <= response.status < 400:
            location = response.getheader("Location", "")
            connection.close()
            raise ProviderHTTPError(response.status, f"unexpected redirect to {location}", {}, url)
        return connection, response

    def request_json(self, method: str, url: str, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                     *, timeout: float | None = None, cancel: CancelHandle | None = None) -> dict[str, Any]:
        connection, response = self._send(method, url, body, headers or {}, timeout, cancel, "application/json")
        try:
            text = response.read().decode("utf-8", errors="replace")
        except (OSError, http.client.HTTPException) as exc:
            if cancel is not None and cancel.cancelled:
                raise Cancelled() from exc
            raise
        finally:
            connection.close()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(response.status, f"response is not JSON: {text[:200]}", {}, url) from exc
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    def post_json(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None, *,
                  timeout: float | None = None, cancel: CancelHandle | None = None) -> dict[str, Any]:
        return self.request_json("POST", url, body, headers, timeout=timeout, cancel=cancel)

    def get_json(self, url: str, headers: dict[str, str] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
        return self.request_json("GET", url, None, headers, timeout=timeout)

    def stream_sse(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None, *,
                   timeout: float | None = None, cancel: CancelHandle | None = None) -> Iterator[SSEEvent]:
        """POST and yield server-sent events. ``timeout`` bounds silence between chunks, so a
        stalled stream raises instead of hanging forever."""
        connection, response = self._send("POST", url, body, headers or {}, timeout, cancel, "text/event-stream")
        try:
            yield from parse_sse(_lines(response))
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if cancel is not None and cancel.cancelled:
                raise Cancelled() from exc
            raise
        finally:
            connection.close()
        if cancel is not None and cancel.cancelled:
            raise Cancelled()


def _lines(response: http.client.HTTPResponse) -> Iterator[str]:
    while True:
        raw = response.readline()
        if not raw:
            return
        yield raw.decode("utf-8", errors="replace")


def parse_sse(lines: Iterator[str]) -> Iterator[SSEEvent]:
    """Server-sent events from an iterator of raw lines."""
    event = ""
    data: list[str] = []
    for line in lines:
        line = line.rstrip("\r\n")
        if not line:
            if data:
                yield SSEEvent(event or "message", "\n".join(data))
            event, data = "", []
        elif line.startswith(":"):
            continue  # comment / keep-alive
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield SSEEvent(event or "message", "\n".join(data))
