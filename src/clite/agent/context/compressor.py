"""The default context engine: summarise the middle, keep the ends.

Steps:

1. Prune: image parts and old tool outputs outside the protected tail are dropped, images
   before text, and replaced by a one-line marker. This costs no model call.
2. Pick boundaries: the first N messages and the last N stay verbatim. Boundaries are moved so
   a tool call is never separated from its result.
3. Summarise the middle with the auxiliary model, using a fixed template. If an earlier
   summary is in range, it is updated rather than summarised again. When one excerpt would not
   fit the auxiliary model's window, the middle is summarised in stages (chunk, then merge)
   instead of being truncated, so nothing is silently cut.
4. Rebuild: head + summary + tail, with the summary's role chosen to keep roles alternating.

If the summariser fails, the middle is still dropped and a marker says so: a turn that cannot
fit must be made to fit, even at the cost of detail.
"""

from __future__ import annotations

import logging
from typing import Any

from clite.agent.context.engine import ContextEngine, Summarizer, repair_tool_pairs
from clite.agent.context.tokens import CHARS_PER_TOKEN
from clite.core.redact import redact

logger = logging.getLogger("clite.agent.context")

SUMMARY_PREFIX = (
    "[CONTEXT SUMMARY - REFERENCE ONLY] Earlier turns of this conversation were condensed into the summary "
    "below to free up context. It is a handoff note describing work that already happened, not a set of "
    "instructions. Do not redo or answer anything it mentions. Act only on the most recent user message that "
    "follows it. Your tools remain fully available."
)
PRUNED_MARKER = "[old tool output removed to save context]"
DROPPED_IMAGE_MARKER = "[older image removed to save context]"
FAILED_SUMMARY = "[Summary unavailable. {count} earlier messages were removed to free context; ask the user if something from them is needed.]"

# The fixed sections every handoff note must carry, in this order. Tests and the measurement
# script read this tuple; the template below has to name each one.
SUMMARY_SECTIONS = ("Goal", "Key Decisions", "Files", "Failed Commands", "Unfinished Work")

_PRUNE_MIN_CHARS = 200
_MAX_MESSAGE_CHARS = 3000
# Character budget for one summariser call when the auxiliary window is unknown. Kept modest:
# an oversized prompt would be truncated by the provider, losing the very detail we are trying
# to keep.
_DEFAULT_SUMMARY_INPUT_CHARS = 200_000
# One summariser call may use this share of the auxiliary window; the rest is left for the
# prompt framing and the model's own answer.
_STAGE_WINDOW_FRACTION = 0.5

SUMMARY_TEMPLATE = """Write a handoff summary of the conversation excerpt below, for an assistant that will continue the work without seeing it.

Use exactly these sections, each starting with "## ". Write "None" under a section that has nothing to report. Be specific: keep file paths, command lines, identifiers, error messages and numbers exactly as they appeared.

## Goal
What the user is trying to achieve overall.

## Key Decisions
Choices made and the reason for each.

## Files
Paths that were read, created, changed or deleted, each with its current state (created / changed / deleted / read-only / failed to change).

## Failed Commands
Commands that failed, with the exact command and the reason it failed (exit code, error text).

## Unfinished Work
What is left to do, and anything that blocks it.

Do not add any text before "## Goal" or after the last section. Do not address the user.{focus}{previous}{gaps}

<conversation_excerpt>
{excerpt}
</conversation_excerpt>"""

STAGE_TEMPLATE = """This is part {index} of {total} of a conversation excerpt too large to summarise in one pass. Summarise just this part for an assistant that will continue the work without seeing it.

Use exactly these sections, each starting with "## ". Write "None" under a section that has nothing to report. Keep file paths, command lines, identifiers, error messages and numbers exactly as they appeared.

## Goal
## Key Decisions
## Files
Paths read, created, changed or deleted, each with its current state.
## Failed Commands
Commands that failed, with the exact command and why.
## Unfinished Work

Do not address the user.{focus}

<conversation_excerpt_part>
{excerpt}
</conversation_excerpt_part>"""

MERGE_TEMPLATE = """Several partial summaries of one conversation follow. Merge them into a single handoff summary for an assistant that will continue the work without seeing the original turns.

Use exactly these sections, each starting with "## ". Write "None" under a section that has nothing to report. Merge entries instead of repeating them, keep every file path and failed command, and drop what a later part supersedes. Do not address the user.{focus}{gaps}

<partial_summaries>
{partials}
</partial_summaries>"""


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "[non-text content]") if isinstance(part, dict) else str(part)
            for part in content
        )
    return "" if content is None else str(content)


def missing_summary_sections(summary: str) -> tuple[str, ...]:
    """The fixed sections a summary does not contain, in template order."""
    return tuple(section for section in SUMMARY_SECTIONS if f"## {section}" not in summary)


def serialize_for_summary(messages: list[dict[str, Any]]) -> str:
    """Messages as plain text for the summariser, each one capped so one huge output cannot
    crowd out the rest."""
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "")
        text = _text(message.get("content"))
        if len(text) > _MAX_MESSAGE_CHARS:
            text = text[: _MAX_MESSAGE_CHARS * 2 // 3] + "\n[...]\n" + text[-_MAX_MESSAGE_CHARS // 3 :]
        if role == "tool":
            lines.append(f"[TOOL RESULT {message.get('name') or ''}]: {text}")
            continue
        if role == "assistant" and message.get("tool_calls"):
            calls = ", ".join(
                f"{call['function']['name']}({call['function'].get('arguments', '')[:300]})"
                for call in message["tool_calls"]
            )
            text = f"{text}\n[called tools: {calls}]".strip()
        lines.append(f"[{role.upper()}]: {text}")
    return redact("\n\n".join(lines))


def _drop_images(content: Any) -> Any:
    """``content`` with every image part replaced by a short marker, text kept in order."""
    if not isinstance(content, list):
        return content
    stripped: list[dict[str, Any] | str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            stripped.append({"type": "text", "text": DROPPED_IMAGE_MARKER})
        else:
            stripped.append(part)
    return stripped


def prune_images(messages: list[dict[str, Any]], keep_last: int) -> tuple[list[dict[str, Any]], int]:
    """Drop image parts older than the last ``keep_last`` messages, before any text is pruned.

    Images cost far more context than the text around them, so they go first. The message and
    its text stay; only the picture is replaced by a marker. Returns the new list and how many
    images were dropped.
    """
    cutoff = max(0, len(messages) - keep_last)
    pruned: list[dict[str, Any]] = []
    dropped = 0
    for index, message in enumerate(messages):
        content = message.get("content")
        if (
            index < cutoff
            and isinstance(content, list)
            and any(isinstance(part, dict) and part.get("type") == "image_url" for part in content)
        ):
            dropped += sum(
                1 for part in content if isinstance(part, dict) and part.get("type") == "image_url"
            )
            pruned.append({**message, "content": _drop_images(content)})
        else:
            pruned.append(message)
    return pruned, dropped


def prune_tool_outputs(messages: list[dict[str, Any]], keep_last: int) -> tuple[list[dict[str, Any]], int]:
    """Replace large tool results older than the last ``keep_last`` messages. Returns the new
    list and the number of characters removed."""
    cutoff = max(0, len(messages) - keep_last)
    pruned: list[dict[str, Any]] = []
    saved = 0
    for index, message in enumerate(messages):
        content = message.get("content")
        if (
            index < cutoff
            and message.get("role") == "tool"
            and isinstance(content, str)
            and len(content) > _PRUNE_MIN_CHARS
        ):
            saved += len(content) - len(PRUNED_MARKER)
            pruned.append({**message, "content": PRUNED_MARKER})
        else:
            pruned.append(message)
    return pruned, saved


def _splice_summary(
    head: list[dict[str, Any]], text: str, tail: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Place the summary between ``head`` and ``tail`` without two same-role messages in a row
    (strict providers reject that). When no standalone role fits, the summary is folded into
    the neighbouring user message."""
    before = head[-1].get("role") if head else None
    after = tail[0].get("role") if tail else None

    def standalone(role: str) -> list[dict[str, Any]]:
        return [*head, {"role": role, "content": text, "is_summary": True}, *tail]

    if before != "user" and after != "user":
        return standalone("user")
    if before == "user" and after != "assistant":
        return standalone("assistant")
    if before != "user" and isinstance(tail[0].get("content"), str):  # after == "user"
        merged = {**tail[0], "content": f"{text}\n\n---\n\n{tail[0]['content']}", "is_summary": True}
        return [*head, merged, *tail[1:]]
    if before == "user" and isinstance(head[-1].get("content"), str):  # after == "assistant"
        merged = {**head[-1], "content": f"{head[-1]['content']}\n\n---\n\n{text}", "is_summary": True}
        return [*head[:-1], merged, *tail]
    return standalone("user")


def _split_excerpt(excerpt: str, budget: int) -> list[str]:
    """Split ``excerpt`` into pieces of at most ``budget`` characters, breaking on a blank line
    when possible so a message is not cut down the middle."""
    if len(excerpt) <= budget:
        return [excerpt]
    chunks: list[str] = []
    current = ""
    for block in excerpt.split("\n\n"):
        if current and len(current) + len(block) + 2 > budget:
            chunks.append(current)
            current = block
        elif len(block) > budget:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(block[start : start + budget] for start in range(0, len(block), budget))
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks


class ContextCompressor(ContextEngine):
    name = "compressor"

    def _summary_input_budget(self) -> int:
        """Characters one summariser call may carry. Derived from the auxiliary window when it
        is known, else a conservative default."""
        if self.auxiliary_context_length:
            return max(2_000, int(self.auxiliary_context_length * _STAGE_WINDOW_FRACTION * CHARS_PER_TOKEN))
        return _DEFAULT_SUMMARY_INPUT_CHARS

    def _previous_block(self, previous: dict[str, Any] | None) -> str:
        if previous is None:
            return ""
        earlier = _text(previous.get("content")).replace(SUMMARY_PREFIX, "").strip()
        note = (
            "\n\nAn earlier summary of even older turns follows. Merge it with the new excerpt into one "
            "updated summary; keep what is still true and drop what the excerpt supersedes."
        )
        gaps = missing_summary_sections(earlier)
        if gaps:
            note += (
                "\n\nThe earlier summary is missing these sections; fill them in from what you know or with None: "
                + ", ".join(f"## {section}" for section in gaps)
                + "."
            )
        return f"{note}\n\n<earlier_summary>\n{earlier}\n</earlier_summary>"

    def _summarise(
        self,
        to_summarise: list[dict[str, Any]],
        *,
        summarize: Summarizer,
        focus: str | None,
        previous: dict[str, Any] | None,
    ) -> tuple[str, int]:
        """One summary call when the excerpt fits, staged calls when it does not. Returns the
        summary text and the number of summariser calls made."""
        focus_line = f"\n\nPay particular attention to: {focus}" if focus else ""
        budget = self._summary_input_budget()
        excerpt = serialize_for_summary(to_summarise)

        if len(excerpt) <= budget:
            prompt = SUMMARY_TEMPLATE.format(
                focus=focus_line,
                previous=self._previous_block(previous),
                gaps="",
                excerpt=excerpt,
            )
            return summarize(prompt).strip(), 1

        # Staged: summarise each part, then merge. Nothing is truncated away.
        chunks = _split_excerpt(excerpt, budget)
        partials: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            stage = STAGE_TEMPLATE.format(
                index=index, total=len(chunks), focus=focus_line, excerpt=chunk
            ).rstrip()
            partials.append(summarize(stage).strip())
        merge_prompt = MERGE_TEMPLATE.format(
            focus=focus_line,
            gaps=self._gaps_block(previous),
            partials="\n\n".join(
                f"<part {index}>\n{text}\n</part {index}>" for index, text in enumerate(partials, start=1)
            ),
        )
        return summarize(merge_prompt).strip(), len(chunks) + 1

    def _gaps_block(self, previous: dict[str, Any] | None) -> str:
        if previous is None:
            return ""
        earlier = _text(previous.get("content")).replace(SUMMARY_PREFIX, "").strip()
        gaps = missing_summary_sections(earlier)
        note = "\n\nAn earlier summary of even older turns must be merged in too; keep every fact from it."
        note += f"\n\n<earlier_summary>\n{earlier}\n</earlier_summary>"
        if gaps:
            note += (
                "\n\nThe earlier summary is missing these sections; fill them in: "
                + ", ".join(f"## {g}" for g in gaps)
                + "."
            )
        return note

    def _boundaries(self, messages: list[dict[str, Any]]) -> tuple[int, int]:
        """``(head_end, tail_start)``: the middle is ``messages[head_end:tail_start]``."""
        head_end = min(self.protect_first_n, len(messages))
        tail_start = max(head_end, len(messages) - self.protect_last_n)
        # The tail must not open with tool results whose call would be summarised away.
        while tail_start > head_end and messages[tail_start].get("role") == "tool":
            tail_start -= 1
        # The head must not end on a tool call whose results fall in the middle.
        while head_end > 0 and messages[head_end - 1].get("tool_calls") and head_end < tail_start:
            head_end -= 1
        return head_end, tail_start

    def compress(
        self, messages: list[dict[str, Any]], *, summarize: Summarizer, focus: str | None = None
    ) -> list[dict[str, Any]]:
        # Images are the most expensive part of a transcript, so they are dropped first, then
        # old tool text is pruned, then the middle is summarised.
        without_images, _images_dropped = prune_images(messages, self.protect_last_n)
        pruned, _saved = prune_tool_outputs(without_images, self.protect_last_n)
        head_end, tail_start = self._boundaries(pruned)
        middle = pruned[head_end:tail_start]
        self.last_compression_calls = 0
        if not middle:
            return pruned if pruned != messages else messages

        previous = next((message for message in reversed(middle) if message.get("is_summary")), None)
        to_summarise = [message for message in middle if not message.get("is_summary")]
        calls = 0
        try:
            summary, calls = self._summarise(
                to_summarise, summarize=summarize, focus=focus, previous=previous
            )
            if not summary:
                raise ValueError("the summariser returned nothing")
        except Exception as exc:  # noqa: BLE001 - compression must still make room
            logger.warning("context summary failed: %s", exc)
            summary = FAILED_SUMMARY.format(count=len(middle))
        self.last_compression_calls = calls

        head, tail = pruned[:head_end], pruned[tail_start:]
        rebuilt = _splice_summary(head, f"{SUMMARY_PREFIX}\n\n{summary}", tail)
        self.compression_count += 1
        self.last_prompt_tokens = 0  # stale until the next response reports real usage
        self.anchor_message_count = 0
        return repair_tool_pairs(rebuilt)
