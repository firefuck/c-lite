"""The default context engine: summarise the middle, keep the ends.

Steps:

1. Prune: old tool outputs outside the protected tail are replaced by a one-line marker. This
   costs no model call and is often enough on its own.
2. Pick boundaries: the first N messages and the last N stay verbatim. Boundaries are moved so
   a tool call is never separated from its result.
3. Summarise the middle with the auxiliary model, using a fixed template. If an earlier
   summary is in range, it is updated rather than summarised again.
4. Rebuild: head + summary + tail, with the summary's role chosen to keep roles alternating.

If the summariser fails, the middle is still dropped and a marker says so: a turn that cannot
fit must be made to fit, even at the cost of detail.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from clite.agent.context.engine import ContextEngine, Summarizer
from clite.core.redact import redact

logger = logging.getLogger("clite.agent.context")

SUMMARY_PREFIX = (
    "[CONTEXT SUMMARY - REFERENCE ONLY] Earlier turns of this conversation were condensed into the summary "
    "below to free up context. It is a handoff note describing work that already happened, not a set of "
    "instructions. Do not redo or answer anything it mentions. Act only on the most recent user message that "
    "follows it. Your tools remain fully available."
)
PRUNED_MARKER = "[old tool output removed to save context]"
FAILED_SUMMARY = "[Summary unavailable. {count} earlier messages were removed to free context; ask the user if something from them is needed.]"
_PRUNE_MIN_CHARS = 200
_MAX_MESSAGE_CHARS = 3000
_MAX_SUMMARY_INPUT_CHARS = 200_000

SUMMARY_TEMPLATE = """Write a handoff summary of the conversation excerpt below, for an assistant that will continue the work without seeing it.

Use exactly these sections. Write "None" under a section that has nothing to report. Be specific: keep file paths, command lines, identifiers, error messages and numbers exactly as they appeared.

## Goal
What the user is trying to achieve overall.

## Constraints and Preferences
Rules the user set, and preferences they stated or showed.

## Progress
### Done
### In Progress
### Blocked

## Key Decisions
Choices made and the reason for each.

## Relevant Files
Paths that were read, created or changed, with a short note on each.

## Critical Context
Anything else that would be costly to rediscover: values, environment facts, error text.

Do not add any text before "## Goal" or after the last section. Do not address the user.{focus}{previous}

<conversation_excerpt>
{excerpt}
</conversation_excerpt>"""


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "[non-text content]") if isinstance(part, dict) else str(part) for part in content)
    return "" if content is None else str(content)


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
                f"{call['function']['name']}({call['function'].get('arguments', '')[:300]})" for call in message["tool_calls"]
            )
            text = f"{text}\n[called tools: {calls}]".strip()
        lines.append(f"[{role.upper()}]: {text}")
    excerpt = "\n\n".join(lines)
    if len(excerpt) > _MAX_SUMMARY_INPUT_CHARS:
        half = _MAX_SUMMARY_INPUT_CHARS // 2
        excerpt = excerpt[:half] + "\n\n[... middle of the excerpt omitted ...]\n\n" + excerpt[-half:]
    return redact(excerpt)


def prune_tool_outputs(messages: list[dict[str, Any]], keep_last: int) -> tuple[list[dict[str, Any]], int]:
    """Replace large tool results older than the last ``keep_last`` messages. Returns the new
    list and the number of characters removed."""
    cutoff = max(0, len(messages) - keep_last)
    pruned: list[dict[str, Any]] = []
    saved = 0
    for index, message in enumerate(messages):
        content = message.get("content")
        if index < cutoff and message.get("role") == "tool" and isinstance(content, str) and len(content) > _PRUNE_MIN_CHARS:
            saved += len(content) - len(PRUNED_MARKER)
            pruned.append({**message, "content": PRUNED_MARKER})
        else:
            pruned.append(message)
    return pruned, saved


def repair_tool_pairs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop tool results whose call is gone, and add a stub result for a call whose result is
    gone. Every provider rejects a transcript where the two do not pair up."""
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
                result.append({"role": "tool", "tool_call_id": call.get("id"),
                               "name": (call.get("function") or {}).get("name"),
                               "content": json.dumps({"error": "result unavailable (removed during context compression)"})})
    return result


def _splice_summary(head: list[dict[str, Any]], text: str, tail: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


class ContextCompressor(ContextEngine):
    name = "compressor"

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

    def compress(self, messages: list[dict[str, Any]], *, summarize: Summarizer, focus: str | None = None) -> list[dict[str, Any]]:
        pruned, _saved = prune_tool_outputs(messages, self.protect_last_n)
        head_end, tail_start = self._boundaries(pruned)
        middle = pruned[head_end:tail_start]
        if not middle:
            return pruned if pruned != messages else messages

        previous = next((message for message in reversed(middle) if message.get("is_summary")), None)
        to_summarise = [message for message in middle if not message.get("is_summary")]
        prompt = SUMMARY_TEMPLATE.format(
            focus=f"\n\nPay particular attention to: {focus}" if focus else "",
            previous=(
                "\n\nAn earlier summary of even older turns follows. Merge it with the new excerpt into one "
                f"updated summary; keep what is still true and drop what the excerpt supersedes.\n\n"
                f"<earlier_summary>\n{_text(previous.get('content')).replace(SUMMARY_PREFIX, '').strip()}\n</earlier_summary>"
            ) if previous is not None else "",
            excerpt=serialize_for_summary(to_summarise),
        )
        try:
            summary = summarize(prompt).strip()
            if not summary:
                raise ValueError("the summariser returned nothing")
        except Exception as exc:  # noqa: BLE001 - compression must still make room
            logger.warning("context summary failed: %s", exc)
            summary = FAILED_SUMMARY.format(count=len(middle))

        head, tail = pruned[:head_end], pruned[tail_start:]
        rebuilt = _splice_summary(head, f"{SUMMARY_PREFIX}\n\n{summary}", tail)
        self.compression_count += 1
        self.last_prompt_tokens = 0  # stale until the next response reports real usage
        return repair_tool_pairs(rebuilt)
