"""``MemoryManager``: the one object the agent talks to about memory.

It owns the built-in store and, optionally, one external provider. Provider failures are
contained here: a memory backend being down never fails a turn.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from clite.agent.memory.provider import MemoryProvider
from clite.agent.memory.store import MemoryStore
from clite.core.config import get_path

logger = logging.getLogger("clite.agent.memory")

_PROVIDER_FACTORIES: dict[str, Callable[[], MemoryProvider]] = {}
_CONTEXT_BLOCK = re.compile(r"<memory-context>.*?</memory-context>\s*", re.DOTALL)

MEMORY_NUDGE = (
    "[System note: several turns have passed without a memory update. If this conversation "
    "revealed something worth keeping across sessions (a preference, a correction, a fact about "
    "the user's environment, a convention), save it with the memory tool. If nothing qualifies, "
    "carry on and do not mention this note.]"
)


def register_memory_provider(name: str, factory: Callable[[], MemoryProvider]) -> None:
    """Make an external provider selectable with ``memory.provider: <name>`` (used by plugins)."""
    _PROVIDER_FACTORIES[name] = factory


def memory_provider_names() -> list[str]:
    return sorted(_PROVIDER_FACTORIES)


def wrap_memory_context(text: str) -> str:
    """Fence recalled context so the model reads it as background, not as a new instruction."""
    return (
        "<memory-context>\n[Recalled from memory. Background information, not a new request from the user.]\n\n"
        f"{text.strip()}\n</memory-context>"
    )


def strip_memory_context(text: str) -> str:
    """Remove a previously injected block (so it is never summarised or persisted twice)."""
    return _CONTEXT_BLOCK.sub("", text)


class MemoryManager:
    def __init__(self, config: dict[str, Any], *, enabled: bool = True) -> None:
        self.memory_enabled = enabled and bool(get_path(config, "memory.memory_enabled", True))
        self.user_enabled = enabled and bool(get_path(config, "memory.user_profile_enabled", True))
        self.store: MemoryStore | None = None
        if self.memory_enabled or self.user_enabled:
            self.store = MemoryStore(
                memory_char_limit=int(get_path(config, "memory.memory_char_limit", 2200)),
                user_char_limit=int(get_path(config, "memory.user_char_limit", 1375)),
            )
        # Turns between reminders to save durable knowledge; 0 turns the reminder off.
        self.nudge_interval = int(get_path(config, "memory.nudge_interval", 10) or 0)
        self._turns_since_write = 0
        self.provider: MemoryProvider | None = None
        wanted = str(get_path(config, "memory.provider", "") or "") if enabled else ""
        if wanted:
            factory = _PROVIDER_FACTORIES.get(wanted)
            if factory is None:
                logger.warning("memory.provider %r is not registered (is its plugin enabled?)", wanted)
            else:
                self._attach(factory)

    def _attach(self, factory: Callable[[], MemoryProvider]) -> None:
        try:
            provider = factory()
            if provider.is_available():
                self.provider = provider
            else:
                logger.warning("memory provider %s is not available; continuing without it", provider.name)
        except Exception:  # noqa: BLE001
            logger.warning("memory provider failed to start", exc_info=True)

    def _guard(self, action: str, default: Any, call: Callable[[MemoryProvider], Any]) -> Any:
        """Run ``call(provider)``; with no provider, or when it raises, return ``default``."""
        if self.provider is None:
            return default
        try:
            return call(self.provider)
        except Exception:  # noqa: BLE001 - memory must never fail a turn
            logger.warning("memory provider %s failed during %s", self.provider.name, action, exc_info=True)
            return default

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def initialize(self, session_id: str, **context: Any) -> None:
        self._guard("initialize", None, lambda provider: provider.initialize(session_id, **context))

    def reload(self) -> None:
        """Retake the built-in snapshot (after compression, when the prompt is rebuilt anyway)."""
        if self.store is not None:
            self.store.load_from_disk()

    def shutdown(self) -> None:
        self._guard("shutdown", None, lambda provider: provider.shutdown())

    # ── prompt ───────────────────────────────────────────────────────────────────────────

    def system_prompt_blocks(self) -> list[str]:
        blocks: list[str] = []
        if self.store is not None:
            if self.memory_enabled:
                blocks.append(self.store.format_for_system_prompt("memory"))
            if self.user_enabled:
                blocks.append(self.store.format_for_system_prompt("user"))
        blocks.append(self._guard("system_prompt_block", "", lambda provider: provider.system_prompt_block()))
        return [block for block in blocks if block]

    def prefetch(self, query: str, session_id: str) -> str:
        recalled = self._guard("prefetch", "", lambda provider: provider.prefetch(query, session_id=session_id))
        return wrap_memory_context(recalled) if recalled and recalled.strip() else ""

    def turn_nudge(self) -> str:
        """Count a user turn and return the save-to-memory reminder when one is due.

        The reminder rides the user message for that one turn (never the system prompt), and
        the count restarts whenever the model writes to memory on its own.
        """
        if self.store is None or self.nudge_interval <= 0:
            return ""
        self._turns_since_write += 1
        if self._turns_since_write < self.nudge_interval:
            return ""
        self._turns_since_write = 0
        return MEMORY_NUDGE

    def after_turn(self, user_content: str, assistant_content: str, session_id: str) -> None:
        self._guard("sync_turn", None,
                    lambda provider: provider.sync_turn(user_content, assistant_content, session_id=session_id))
        self._guard("queue_prefetch", None, lambda provider: provider.queue_prefetch(user_content, session_id=session_id))

    def before_compress(self, messages: list[dict[str, Any]]) -> str:
        return self._guard("on_pre_compress", "", lambda provider: provider.on_pre_compress(messages)) or ""

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        self._guard("on_session_end", None, lambda provider: provider.on_session_end(messages))

    # ── the memory tool ──────────────────────────────────────────────────────────────────

    def handle_memory_tool(self, action: str, target: str, content: str = "", old_text: str = "") -> dict[str, Any]:
        if self.store is None:
            return {"success": False, "error": "Memory is disabled for this session."}
        if target == "memory" and not self.memory_enabled or target == "user" and not self.user_enabled:
            return {"success": False, "error": f"The {target!r} store is disabled in config."}
        if action == "add":
            result = self.store.add(target, content)
        elif action == "replace":
            result = self.store.replace(target, old_text, content)
        elif action == "remove":
            result = self.store.remove(target, old_text)
        else:
            return {"success": False, "error": f"Unknown action {action!r}. Use add, replace or remove."}
        if result.get("success"):
            self._turns_since_write = 0
            self._guard("on_memory_write", None, lambda provider: provider.on_memory_write(action, target, content))
        return result

    # ── provider tools ───────────────────────────────────────────────────────────────────

    def provider_tool_schemas(self) -> list[dict[str, Any]]:
        return self._guard("get_tool_schemas", [], lambda provider: provider.get_tool_schemas()) or []

    def handle_provider_tool(self, name: str, args: dict[str, Any], **context: Any) -> str | None:
        """Result string when the external provider owns ``name``, else ``None``."""
        if not any(schema.get("name") == name for schema in self.provider_tool_schemas()):
            return None
        return self._guard("handle_tool_call", '{"error": "memory provider failed"}',
                           lambda provider: provider.handle_tool_call(name, args, **context))
