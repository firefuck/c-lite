"""``ContextEngine``: the strategy that keeps a conversation inside the model's window.

The built-in engine is the lossy summariser in ``compressor.py``. A plugin can register
another (``context.engine: <name>`` selects it), for example one that stores every message
and retrieves by relevance instead of summarising.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from clite.core.config import get_path
from clite.providers.transports.types import Usage

logger = logging.getLogger("clite.agent.context")

# Below this window size the threshold is floored: at 50% of a small window, the part that
# cannot be compressed (system prompt, tools, protected messages) eats what was reclaimed and
# compression fires again every turn or two.
SMALL_WINDOW_LIMIT = 512_000
SMALL_WINDOW_THRESHOLD = 0.75

Summarizer = Callable[[str], str]  # prompt text in, summary text out; raises on failure


def repair_tool_pairs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop tool results whose call is gone, and add a stub result for a call whose result is
    gone. Every provider rejects a transcript where the two do not pair up.

    Any engine that cuts a conversation in two needs this: the cut can land between a call and
    its result. It lives next to the base class because it is part of the engine contract, not
    of any one engine.
    """
    call_ids = {call.get("id") for message in messages for call in message.get("tool_calls") or []}
    repaired: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "tool" and message.get("tool_call_id") not in call_ids:
            continue
        repaired.append(message)
    answered = {message.get("tool_call_id") for message in repaired if message.get("role") == "tool"}
    result: list[dict[str, Any]] = []
    for message in repaired:
        result.append(message)
        for call in message.get("tool_calls") or []:
            if call.get("id") not in answered:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": (call.get("function") or {}).get("name"),
                        "content": json.dumps(
                            {"error": "result unavailable (removed during context compression)"}
                        ),
                    }
                )
    return result


class ContextEngine(ABC):
    name = ""

    def __init__(self) -> None:
        self.context_length = 0
        self.threshold_percent = 0.5
        self.threshold_tokens = 0
        self.protect_first_n = 3
        self.protect_last_n = 20
        self.last_prompt_tokens = 0
        # How many messages the request carried when the provider reported the last real
        # prompt size. Everything up to that point is measured, not estimated.
        self.anchor_message_count = 0
        # Window of the auxiliary model used to summarise. 0 means "unknown": summarisers
        # then fall back to their own conservative bound.
        self.auxiliary_context_length = 0
        self.compression_count = 0
        self.last_compression_calls = 0

    def configure(
        self, *, context_length: int, config: dict[str, Any], auxiliary_context_length: int | None = None
    ) -> None:
        """Called at session start and whenever the model (hence the window) changes."""
        percent = float(get_path(config, "compression.threshold", 0.5) or 0.5)
        if context_length < SMALL_WINDOW_LIMIT:
            percent = max(percent, SMALL_WINDOW_THRESHOLD)
        self.context_length = context_length
        self.threshold_percent = percent
        self.threshold_tokens = int(context_length * percent)
        self.protect_first_n = int(get_path(config, "compression.protect_first_n", 3))
        self.protect_last_n = int(get_path(config, "compression.protect_last_n", 20))
        if auxiliary_context_length is not None:
            self.auxiliary_context_length = max(0, int(auxiliary_context_length))

    def update_from_response(self, usage: Usage | None, *, message_count: int | None = None) -> None:
        if usage is not None and usage.prompt_tokens:
            self.last_prompt_tokens = usage.prompt_tokens
            if message_count is not None:
                self.anchor_message_count = message_count

    def anchored_prompt_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Prompt size using the provider's last number as an anchor, estimates only after."""
        from clite.agent.context.tokens import estimate_prompt_tokens

        return estimate_prompt_tokens(
            messages,
            system_prompt=system_prompt,
            tools=tools,
            anchor_tokens=self.last_prompt_tokens,
            anchor_message_count=self.anchor_message_count,
        )

    def should_compress(self, prompt_tokens: int | None = None) -> bool:
        tokens = self.last_prompt_tokens if prompt_tokens is None else prompt_tokens
        return bool(self.threshold_tokens) and tokens >= self.threshold_tokens

    @abstractmethod
    def compress(
        self, messages: list[dict[str, Any]], *, summarize: Summarizer, focus: str | None = None
    ) -> list[dict[str, Any]]:
        """Return a shorter message list. Must keep every tool call paired with its result and
        must not mutate ``messages``. Returning the input unchanged means "nothing to do"."""

    def on_session_start(self, session_id: str) -> None:
        """A session began or was resumed."""

    def on_session_reset(self) -> None:
        self.last_prompt_tokens = 0
        self.anchor_message_count = 0
        self.compression_count = 0
        self.last_compression_calls = 0

    def on_session_end(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """The session is closing."""

    def status(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "context_length": self.context_length,
            "threshold_tokens": self.threshold_tokens,
            "last_prompt_tokens": self.last_prompt_tokens,
            "compression_count": self.compression_count,
            "usage_percent": round(self.last_prompt_tokens * 100 / self.context_length, 1)
            if self.context_length
            else 0.0,
        }


_ENGINES: dict[str, Callable[[], ContextEngine]] = {}


def register_context_engine(name: str, factory: Callable[[], ContextEngine]) -> None:
    _ENGINES[name] = factory


def engine_names() -> list[str]:
    """Names a ``context.engine`` value can take, sorted. ``compressor`` is always present."""
    _ensure_builtin()
    return sorted(_ENGINES)


def reset_context_engines() -> None:
    """Forget every registered engine (called between tests). ``compressor`` comes back on use."""
    _ENGINES.clear()


def _ensure_builtin() -> None:
    from clite.agent.context.compressor import ContextCompressor

    _ENGINES.setdefault("compressor", ContextCompressor)


def create_context_engine(name: str) -> ContextEngine:
    """Build the engine ``context.engine`` names. An unknown name is a typo in config, not a
    reason to fail: fall back to the built-in compressor and say so in the log."""
    _ensure_builtin()
    factory = _ENGINES.get(name)
    if factory is None:
        logger.warning(
            "unknown context.engine %r; falling back to 'compressor'. Available: %s",
            name,
            ", ".join(engine_names()),
        )
        factory = _ENGINES["compressor"]
    return factory()
