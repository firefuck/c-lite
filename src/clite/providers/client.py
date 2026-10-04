"""``LLMClient``: one model call, in any protocol, streamed or not.

The agent loop talks to this interface only. Tests swap in ``ScriptedClient`` (see
``clite.providers.testing``); nothing above this file knows that HTTP exists.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Protocol

from clite.providers.http import CancelHandle, Cancelled, HttpClient
from clite.providers.runtime import RuntimeRoute
from clite.providers.transports.base import get_transport
from clite.providers.transports.types import NormalizedResponse, RequestParams


class ModelClient(Protocol):
    def complete(
        self,
        route: RuntimeRoute,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        params: RequestParams | None = None,
        stream: bool = True,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> NormalizedResponse:
        ...


class LLMClient:
    def __init__(self, http: HttpClient | None = None) -> None:
        self.http = http or HttpClient()

    def complete(
        self,
        route: RuntimeRoute,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        params: RequestParams | None = None,
        stream: bool = True,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> NormalizedResponse:
        """Send one request and return the normalised response.

        ``cancel`` aborts the call from another thread: the socket is shut down and
        ``InterruptedError`` is raised here.
        """
        params = params or RequestParams()
        transport = get_transport(route.api_mode)
        if transport.local:
            return transport.run(route, messages, tools, params, on_delta=on_delta, cancel=cancel)  # type: ignore[attr-defined]

        request = transport.build_request(route, messages, tools, params, stream=stream)
        handle = CancelHandle()
        watcher_done = threading.Event()
        if cancel is not None:
            def watch() -> None:
                while not watcher_done.is_set():
                    if cancel.wait(0.05):
                        handle.cancel()
                        return

            threading.Thread(target=watch, name="clite-cancel-watch", daemon=True).start()
        try:
            if not stream:
                payload = self.http.post_json(request.url, request.body, request.headers,
                                              timeout=params.timeout, cancel=handle)
                return transport.parse_response(payload)
            accumulator = transport.stream_accumulator(on_delta, on_reasoning)
            for event in self.http.stream_sse(request.url, request.body, request.headers,
                                              timeout=params.timeout, cancel=handle):
                if not accumulator.feed(event.event, event.data):
                    break
            if handle.cancelled:
                raise Cancelled()
            return accumulator.finish()
        except Cancelled as exc:
            raise InterruptedError("model call cancelled") from exc
        finally:
            watcher_done.set()
