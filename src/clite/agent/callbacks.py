"""``AgentCallbacks``: how a surface observes and answers the agent.

A surface (CLI, RPC server, gateway) builds one of these and passes it to ``AIAgent``. Every
field is optional. Observers (``on_*``) must return quickly and must not raise; the two
question callbacks (``approve`` and ``clarify``) block until the user answers.

The agent calls these from whichever thread is running the turn, and tool callbacks may come
from worker threads when tools run in parallel. A surface that owns a UI thread marshals onto
it itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("clite.agent.callbacks")


@dataclass
class AgentCallbacks:
    # Streaming text of the assistant's answer and of its reasoning.
    on_delta: Callable[[str], None] | None = None
    on_reasoning: Callable[[str], None] | None = None
    # A model call is starting (iteration number, 1-based) / the assistant message is complete.
    on_step: Callable[[int], None] | None = None
    on_message: Callable[[dict[str, Any]], None] | None = None
    # Tool lifecycle. ``on_tool_complete`` receives the result string and seconds taken.
    on_tool_start: Callable[[str, str, dict[str, Any]], None] | None = None  # (call_id, name, args)
    on_tool_complete: Callable[[str, str, dict[str, Any], str, float], None] | None = None
    # Lifecycle notices: (kind, text). Kinds: compressing, compressed, retry, fallback, warning.
    on_status: Callable[[str, str], None] | None = None
    # Subagent progress: (event, payload). Events: start, tool, complete.
    on_subagent: Callable[[str, dict[str, Any]], None] | None = None
    # approve(command=, description=, pattern_keys=) -> "once" | "session" | "always" | "deny"
    approve: Callable[..., str] | None = None
    # clarify(question, choices) -> the user's answer
    clarify: Callable[[str, list[str]], str] | None = None

    def emit(self, name: str, *args: Any) -> None:
        """Call an observer if it is set. A failing observer is logged, never propagated."""
        callback = getattr(self, name, None)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  # noqa: BLE001 - a display bug must not break the turn
            logger.warning("callback %s failed", name, exc_info=True)
