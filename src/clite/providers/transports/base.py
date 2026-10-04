"""``ProviderTransport``: one class per wire protocol (``api_mode``).

A transport converts between the internal OpenAI-style message format and one protocol. It
owns no network code: it builds a request, parses a response, and accumulates a stream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from clite.providers.transports.types import HttpRequest, NormalizedResponse, RequestParams

if TYPE_CHECKING:
    from clite.providers.runtime import RuntimeRoute

# Keys that exist on stored messages but must never go on the wire.
INTERNAL_MESSAGE_KEYS = frozenset(
    {"_row_id", "timestamp", "reasoning", "provider_data", "turn_context", "finish_reason", "is_summary", "display_kind",
     "token_count"}
)


class StreamAccumulator(ABC):
    """Fed server-sent events one at a time; yields the final response at the end."""

    def __init__(self, on_delta: Callable[[str], None] | None = None,
                 on_reasoning: Callable[[str], None] | None = None) -> None:
        self.on_delta = on_delta
        self.on_reasoning = on_reasoning

    @abstractmethod
    def feed(self, event: str, data: str) -> bool:
        """Consume one SSE event. Return False when the stream is finished."""

    @abstractmethod
    def finish(self) -> NormalizedResponse:
        ...

    def _emit(self, text: str) -> None:
        if text and self.on_delta is not None:
            self.on_delta(text)

    def _emit_reasoning(self, text: str) -> None:
        if text and self.on_reasoning is not None:
            self.on_reasoning(text)


class ProviderTransport(ABC):
    api_mode: str = ""
    # True for a transport that produces its response without HTTP (the offline mock).
    local: bool = False

    @abstractmethod
    def build_request(
        self,
        route: RuntimeRoute,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        params: RequestParams,
        *,
        stream: bool,
    ) -> HttpRequest:
        ...

    @abstractmethod
    def parse_response(self, payload: dict[str, Any]) -> NormalizedResponse:
        ...

    @abstractmethod
    def stream_accumulator(self, on_delta: Callable[[str], None] | None = None,
                           on_reasoning: Callable[[str], None] | None = None) -> StreamAccumulator:
        ...


_TRANSPORTS: dict[str, ProviderTransport] = {}
_BUILTIN_LOADED = False


def register_transport(transport: ProviderTransport) -> None:
    """Register a transport instance for its ``api_mode`` (the last one registered wins)."""
    if not transport.api_mode:
        raise ValueError("a transport needs an api_mode")
    _TRANSPORTS[transport.api_mode] = transport


def get_transport(api_mode: str) -> ProviderTransport:
    _ensure_builtin()
    try:
        return _TRANSPORTS[api_mode]
    except KeyError:
        raise ValueError(f"no transport for api_mode {api_mode!r}; known: {sorted(_TRANSPORTS)}") from None


def transport_modes() -> list[str]:
    _ensure_builtin()
    return sorted(_TRANSPORTS)


def _ensure_builtin() -> None:
    global _BUILTIN_LOADED
    if _BUILTIN_LOADED:
        return
    _BUILTIN_LOADED = True
    registered_first = dict(_TRANSPORTS)  # a plugin may have registered before first use
    from clite.providers.transports import anthropic_messages, chat_completions, mock  # noqa: F401

    _TRANSPORTS.update(registered_first)
