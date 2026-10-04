"""``ContextEngine``: the strategy that keeps a conversation inside the model's window.

The built-in engine is the lossy summariser in ``compressor.py``. A plugin can register
another (``context.engine: <name>`` selects it), for example one that stores every message
and retrieves by relevance instead of summarising.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from clite.core.config import get_path
from clite.providers.transports.types import Usage

# Below this window size the threshold is floored: at 50% of a small window, the part that
# cannot be compressed (system prompt, tools, protected messages) eats what was reclaimed and
# compression fires again every turn or two.
SMALL_WINDOW_LIMIT = 512_000
SMALL_WINDOW_THRESHOLD = 0.75

Summarizer = Callable[[str], str]  # prompt text in, summary text out; raises on failure


class ContextEngine(ABC):
    name = ""

    def __init__(self) -> None:
        self.context_length = 0
        self.threshold_percent = 0.5
        self.threshold_tokens = 0
        self.protect_first_n = 3
        self.protect_last_n = 20
        self.last_prompt_tokens = 0
        self.compression_count = 0

    def configure(self, *, context_length: int, config: dict[str, Any]) -> None:
        """Called at session start and whenever the model (hence the window) changes."""
        percent = float(get_path(config, "compression.threshold", 0.5) or 0.5)
        if context_length < SMALL_WINDOW_LIMIT:
            percent = max(percent, SMALL_WINDOW_THRESHOLD)
        self.context_length = context_length
        self.threshold_percent = percent
        self.threshold_tokens = int(context_length * percent)
        self.protect_first_n = int(get_path(config, "compression.protect_first_n", 3))
        self.protect_last_n = int(get_path(config, "compression.protect_last_n", 20))

    def update_from_response(self, usage: Usage | None) -> None:
        if usage is not None and usage.prompt_tokens:
            self.last_prompt_tokens = usage.prompt_tokens

    def should_compress(self, prompt_tokens: int | None = None) -> bool:
        tokens = self.last_prompt_tokens if prompt_tokens is None else prompt_tokens
        return bool(self.threshold_tokens) and tokens >= self.threshold_tokens

    @abstractmethod
    def compress(self, messages: list[dict[str, Any]], *, summarize: Summarizer, focus: str | None = None) -> list[dict[str, Any]]:
        """Return a shorter message list. Must keep every tool call paired with its result and
        must not mutate ``messages``. Returning the input unchanged means "nothing to do"."""

    def on_session_start(self, session_id: str) -> None:
        """A session began or was resumed."""

    def on_session_reset(self) -> None:
        self.last_prompt_tokens = 0
        self.compression_count = 0

    def on_session_end(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """The session is closing."""

    def status(self) -> dict[str, Any]:
        return {
            "engine": self.name, "context_length": self.context_length, "threshold_tokens": self.threshold_tokens,
            "last_prompt_tokens": self.last_prompt_tokens, "compression_count": self.compression_count,
            "usage_percent": round(self.last_prompt_tokens * 100 / self.context_length, 1) if self.context_length else 0.0,
        }


_ENGINES: dict[str, Callable[[], ContextEngine]] = {}


def register_context_engine(name: str, factory: Callable[[], ContextEngine]) -> None:
    _ENGINES[name] = factory


def create_context_engine(name: str) -> ContextEngine:
    from clite.agent.context.compressor import ContextCompressor

    _ENGINES.setdefault("compressor", ContextCompressor)
    factory = _ENGINES.get(name)
    if factory is None:
        raise ValueError(f"unknown context.engine {name!r}; available: {sorted(_ENGINES)}")
    return factory()
