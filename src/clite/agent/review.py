"""Background review: learn from a long turn without touching it.

After a turn that used enough tool calls, a small forked agent reads a *copy* of that turn and
decides whether anything is worth keeping: a fact for memory, a procedure for a skill. The
review runs on its own thread with a narrow toolset (``memory`` and ``skills``) and a small
turn budget, so it can never hold up the next turn or rewrite the conversation it is reviewing.

Rules this module keeps:

* The main transcript and the system prompt are never touched. The fork is a separate
  ``AIAgent`` with persistence off; it only ever writes through the memory and skill tools.
* Nothing here raises into a turn. A review that fails or times out is a logged note and a
  status line, nothing more.
* Reviews are optional (``background_review.enabled``), rate-limited per session
  (``background_review.min_interval_seconds``), and skipped for subagents, cron runs and a
  session that is already busy.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from clite.agent.callbacks import AgentCallbacks
from clite.core.config import get_path
from clite.core.threads import start_thread

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent
    from clite.agent.state import TurnState

logger = logging.getLogger("clite.agent.review")

# Narrow by design: the reviewer learns from a turn, it does not replay it.
REVIEW_TOOLSETS: tuple[str, ...] = ("memory", "skills")
REVIEW_MAX_TURNS = 3

# Sessions reviewed recently, so a long conversation is not reviewed on every turn.
_LAST_REVIEWED: dict[str, float] = {}
_LOCK = threading.Lock()

_MEMORY_PROMPT = (
    "You are reviewing a conversation turn that just finished. It ran for {tool_calls} tool "
    "calls, so it may have taught something durable.\n\n"
    "--- The turn (what the user asked, what happened, what was answered) ---\n{transcript}\n"
    "--- End of the turn ---\n\n"
    "You may only use the memory and skill tools.\n\n"
    "1. Memory: did the user reveal a fact, preference, correction or environment detail worth "
    "keeping across sessions? If so, save it with the memory tool.\n"
    "2. Skills: did the turn work out a non-trivial procedure that a future session would "
    "repeat? If so, save or patch it with skill_manage.\n\n"
    "If nothing is worth saving, reply 'Nothing to save.' and stop. Do not mention this review "
    "in memory or skills."
)


@dataclass
class ReviewOutcome:
    """What one review pass did, for the status line and the log."""

    actions: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def summary(self) -> str:
        if self.error:
            return f"review failed: {self.error}"
        return " · ".join(dict.fromkeys(self.actions)) if self.actions else "nothing to save"


# ── process state ────────────────────────────────────────────────────────────────────────


def reset_review_state() -> None:
    """Forget which sessions were reviewed recently (tests, and a fresh process)."""
    with _LOCK:
        _LAST_REVIEWED.clear()


def _mark_reviewed(session_id: str) -> None:
    with _LOCK:
        _LAST_REVIEWED[session_id] = time.time()


def _reviewed_within_interval(session_id: str, interval_seconds: float) -> bool:
    with _LOCK:
        last = _LAST_REVIEWED.get(session_id)
    return last is not None and (time.time() - last) < interval_seconds


# ── gates ────────────────────────────────────────────────────────────────────────────────


def review_enabled(config: dict[str, Any]) -> bool:
    return bool(get_path(config, "background_review.enabled", True))


def turn_tool_calls(agent: AIAgent, state: TurnState) -> int:
    """Tool calls the finished turn made, counted from the messages it added."""
    calls = 0
    for message in agent.messages[state.first_message_index :]:
        calls += len(message.get("tool_calls") or [])
    return calls


def should_review(agent: AIAgent, state: TurnState, *, ignore_busy: bool = False) -> bool:
    """Whether this finished turn should be reviewed. Every gate must pass.

    ``ignore_busy`` skips the busy check for a caller that is at the tail of its own turn (the
    lock is still held then); anywhere else, a running turn blocks a review.
    """
    if not review_enabled(agent.config):
        return False
    if not state.completed or state.interrupted:
        return False
    if agent.memory is None:  # memory disabled: nothing the reviewer may write
        return False
    # A subagent and a cron run have no user behind them to learn for.
    if agent.depth > 0 or agent.platform == "cron":
        return False
    if not ignore_busy and agent.busy:  # a turn is still running; never compete with it
        return False
    threshold = int(get_path(agent.config, "background_review.min_tool_calls", 8) or 0)
    if turn_tool_calls(agent, state) < threshold:
        return False
    interval = float(get_path(agent.config, "background_review.min_interval_seconds", 900) or 0)
    return not _reviewed_within_interval(agent.session_id, interval)


# ── the turn copy ────────────────────────────────────────────────────────────────────────


def build_turn_transcript(agent: AIAgent, state: TurnState, *, max_chars: int = 8000) -> str:
    """A compact, text-only copy of the turn: what was asked, the tools used, the answer.

    This is the reviewer's whole window on the turn. It is a fresh string, not the live
    transcript, so the reviewer cannot reach anything that was not put here.
    """
    lines: list[str] = []
    for message in agent.messages[state.first_message_index :]:
        role = message.get("role")
        content = message.get("content")
        if role == "user" and isinstance(content, str):
            lines.append(f"USER: {content}")
        elif role == "assistant":
            text = content if isinstance(content, str) else ""
            for call in message.get("tool_calls") or []:
                name = (call.get("function") or {}).get("name", "?")
                lines.append(f"TOOL CALL: {name}")
            if text.strip():
                lines.append(f"ASSISTANT: {text}")
        elif role == "tool":
            name = message.get("name") or "tool"
            snippet = (content if isinstance(content, str) else "")[:400]
            lines.append(f"TOOL RESULT ({name}): {snippet}")
    transcript = "\n".join(lines)
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n[... turn truncated for review ...]"
    return transcript


def review_prompt(agent: AIAgent, state: TurnState) -> str:
    return _MEMORY_PROMPT.format(
        tool_calls=turn_tool_calls(agent, state), transcript=build_turn_transcript(agent, state)
    )


# ── running the review ───────────────────────────────────────────────────────────────────


def _collect_actions(fork: AIAgent) -> list[str]:
    """Human-readable actions the reviewer took, read from its own tool results."""
    actions: list[str] = []
    for message in fork.messages:
        if message.get("role") != "tool":
            continue
        name = message.get("name")
        if name not in ("memory", "skill_manage"):
            continue
        try:
            data = json.loads(message.get("content") or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("success"):
            continue
        if name == "skill_manage":
            actions.append("Skill created" if data.get("created") else "Skill updated")
        else:
            actions.append("Memory updated")
    return list(dict.fromkeys(actions))


def _build_fork(agent: AIAgent) -> AIAgent:
    """A separate, non-persistent agent for the review: same route, narrow tools, small budget.

    It shares the parent's model client so a test (and a warm prompt cache) sees the same model,
    but it is otherwise detached: no session rows, no shared transcript, no title, no children.
    """
    from clite.agent.agent import AIAgent as _AIAgent

    max_turns = int(
        get_path(agent.config, "background_review.max_turns", REVIEW_MAX_TURNS) or REVIEW_MAX_TURNS
    )
    fork = _AIAgent(
        agent.route,
        platform=agent.platform,
        cwd=agent.cwd,
        enabled_toolsets=list(REVIEW_TOOLSETS),
        disabled_toolsets=[],
        max_turns=max_turns,
        callbacks=AgentCallbacks(),
        config=agent.config,
        client=agent.client,
        skip_context_files=True,
        persist=False,
        stream=False,
        auto_title=False,
    )
    return fork


def run_review(agent: AIAgent, state: TurnState, *, timeout: float | None = None) -> ReviewOutcome:
    """Run one review pass synchronously and return what it did.

    Never raises: a failure or a timeout is an ``error`` on the outcome. Used directly by tests
    and by :func:`spawn_background_review` on its worker thread.
    """
    if timeout is None:
        timeout = float(get_path(agent.config, "background_review.timeout_seconds", 120) or 0) or None
    outcome = ReviewOutcome()
    fork: AIAgent | None = None
    done = threading.Event()

    def work() -> None:
        nonlocal fork
        try:
            fork = _build_fork(agent)
            result = fork.run_conversation(review_prompt(agent, state))
            if result.error and not result.completed:
                outcome.error = result.error
                logger.warning("background review failed in session %s: %s", agent.session_id, result.error)
        except Exception as exc:  # noqa: BLE001 - a review must never fail a turn
            outcome.error = f"{type(exc).__name__}: {exc}"
            logger.warning("background review failed in session %s: %s", agent.session_id, exc)
        finally:
            if fork is not None:
                try:
                    fork.close("review")
                except Exception:  # noqa: BLE001
                    logger.debug("review fork cleanup failed", exc_info=True)
            done.set()

    start_thread(work, name="clite-review")
    if not done.wait(timeout):
        outcome.error = "timed out"
        logger.warning("background review timed out in session %s", agent.session_id)
        _mark_reviewed(agent.session_id)
        return outcome
    if outcome.error is None and fork is not None:
        outcome.actions = _collect_actions(fork)
    _mark_reviewed(agent.session_id)
    logger.info("background review in session %s: %s", agent.session_id, outcome.summary)
    return outcome


def spawn_background_review(agent: AIAgent, state: TurnState) -> threading.Thread:
    """Run a review on a background thread and report it when it finishes.

    Returns the worker thread so a caller that wants to wait can; the turn itself never does.
    The session is marked as reviewed now, so a later long turn does not start a second review
    while this one is still in flight.
    """
    _mark_reviewed(agent.session_id)

    def work() -> None:
        outcome = run_review(agent, state)
        agent.callbacks.emit("on_status", "review", f"self-improvement review: {outcome.summary}")

    return start_thread(work, name="clite-review-dispatch")
