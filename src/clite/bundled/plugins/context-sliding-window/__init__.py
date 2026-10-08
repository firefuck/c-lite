"""Sliding-window context engine: keep a protected head and tail, drop everything between.

The cheap end of the trade the built-in compressor sits at the expensive end of: instead of
summarising the middle with an auxiliary model, this engine drops it. It never calls the
summariser, so one compression costs nothing but the bookkeeping. It is auto-loaded as a
bundled backend plugin, so ``context.engine: sliding-window`` selects it out of the box.
"""

from __future__ import annotations

from typing import Any

from clite.agent.context.engine import ContextEngine, Summarizer, repair_tool_pairs


def _alternate_roles(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a message whose role repeats the previous non-tool role. Cutting the middle can
    leave two same-role messages facing each other at the join, which providers reject."""
    kept: list[dict[str, Any]] = []
    previous: str | None = None
    for message in messages:
        role = message.get("role")
        if role == "tool":
            kept.append(message)
            continue
        if role == previous:
            continue
        kept.append(message)
        previous = role
    return kept


class SlidingWindowEngine(ContextEngine):
    name = "sliding-window"

    def compress(
        self,
        messages: list[dict[str, Any]],
        *,
        summarize: Summarizer,
        focus: str | None = None,
    ) -> list[dict[str, Any]]:
        head = list(messages[: self.protect_first_n])
        tail = list(messages[-self.protect_last_n :]) if self.protect_last_n > 0 else []
        if not head and not tail:
            return messages
        if len(head) + len(tail) >= len(messages):
            return messages
        # Cutting can orphan a tool result (its call was dropped) or a call (its result was
        # dropped); repair_tool_pairs fixes both, and the role pass can drop a call in turn,
        # so repair once more afterwards.
        kept = repair_tool_pairs([*head, *tail])
        kept = _alternate_roles(kept)
        kept = repair_tool_pairs(kept)
        if len(kept) >= len(messages):
            return messages
        self.compression_count += 1
        return kept


def register(ctx) -> None:
    ctx.register_context_engine(SlidingWindowEngine.name, SlidingWindowEngine)
