"""``MemoryProvider``: the interface for an external memory backend (a plugin).

The built-in store (MEMORY.md / USER.md) is always on. At most one external provider runs
beside it: two providers would both inject context and both expose tools, which bloats the
prompt and makes it unclear which memory is authoritative.

Every method except ``name`` and ``is_available`` has a safe default, so a provider
implements only what it supports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MemoryProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, also the value of ``memory.provider`` in config."""

    @abstractmethod
    def is_available(self) -> bool:
        """True when the provider is configured and usable. Must not make network calls."""

    def initialize(self, session_id: str, **context: Any) -> None:
        """Called once per session. ``context`` carries ``platform``, ``home`` and similar."""

    def system_prompt_block(self) -> str:
        """Static text for the system prompt (volatile tier). Fixed for the session."""
        return ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Context recalled for this turn. It is attached to the user message, never to the
        system prompt. Should return quickly; do slow work in ``queue_prefetch``."""
        return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Start recall for the *next* turn in the background."""

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Persist a finished turn. Must not block: queue the write."""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Tools this provider adds, as ``{"name", "description", "parameters"}`` schemas."""
        return []

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context: Any) -> str:
        raise NotImplementedError(f"{self.name} does not handle tool {tool_name!r}")

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror a write made to the built-in store."""

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        """Extract anything worth keeping before these messages are summarised away."""
        return ""

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """Final extraction when a session ends."""

    def shutdown(self) -> None:
        """Flush queues and close connections."""
