"""Questions a turn waits on in a chat: command approvals and clarifications, and their answers.

The agent's ``approve`` and ``clarify`` callbacks block the turn's thread until the user answers
or ``approvals.timeout`` passes; for an approval, silence is a no. The answer arrives on another
thread: as the next message from the chat (:meth:`PendingQuestions.answer`), or, on a platform
that can show buttons, as a press on the approval prompt. A press counts only from the prompt's
owner, in its chat and thread, for the very question that is still pending.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from clite.gateway.controls import APPROVAL_PREFIX, approval_keyboard
from clite.gateway.event import SessionSource

if TYPE_CHECKING:
    from clite.gateway.runner import GatewayRunner, GatewaySession

_APPROVAL_WORDS = {
    "approve": "once",
    "yes": "once",
    "y": "once",
    "ok": "once",
    "once": "once",
    "session": "session",
    "always": "always",
    "deny": "deny",
    "no": "deny",
    "n": "deny",
}
_APPROVAL_TRAILING_PUNCTUATION = ".,;:!?"


@dataclass
class Pending:
    """A question the agent asked that the next message from this chat answers."""

    kind: str  # "approval" | "clarify"
    choices: list[str] = field(default_factory=list)
    answered: threading.Event = field(default_factory=threading.Event)
    answer: str = ""


@dataclass
class _ApprovalPrompt:
    """An approval button prompt tied to the one pending question that created it."""

    key: str
    session_key: str
    source: SessionSource
    pending: Pending
    message_id: str


class PendingQuestions:
    """Ask a chat's user on behalf of a turn, and release the turn when an answer comes.

    Part of the runner, kept apart for readability: it reads the runner's sessions and adapters,
    and replies through the runner. ``lock`` is the one that guards the runner's sessions; the
    approval prompts are kept under it too, so a button press is checked against the session in
    the same step that records the answer.
    """

    def __init__(self, runner: GatewayRunner, *, lock: threading.RLock) -> None:
        self._runner = runner
        self._lock = lock
        self._prompts: dict[str, _ApprovalPrompt] = {}

    # ── asking, on the turn's thread ─────────────────────────────────────────────────────

    def approve(
        self, session_key: str, source: SessionSource, *, command: str, description: str, timeout: float
    ) -> str:
        """Ask whether ``command`` may run and wait for the answer; ``deny`` when none comes."""
        message = (
            f"This command needs your approval ({description}):\n\n{command}\n\n"
            "Reply /approve (once), /approve session, /approve always, or /deny."
        )
        pending = Pending("approval")
        session = self._runner.sessions.get(session_key)
        if session is None:
            return "deny"
        session.pending = pending
        if not self._send_approval_buttons(session, pending, command, description):
            self._runner.reply(source, message)
        pending.answered.wait(timeout)
        self._close_approval_prompt_for(pending, f"Approval: {pending.answer or 'denied'}.")
        session.pending = None
        return pending.answer or "deny"  # silence is a no

    def clarify(
        self, session_key: str, source: SessionSource, question: str, choices: list[str], *, timeout: float
    ) -> str:
        """Ask ``question`` with numbered ``choices`` and wait; ``""`` when no answer comes."""
        options = "".join(f"\n{number}. {choice}" for number, choice in enumerate(choices, start=1))
        return self._ask(session_key, source, Pending("clarify", choices), f"{question}{options}", timeout)

    def _ask(
        self, session_key: str, source: SessionSource, pending: Pending, message: str, timeout: float
    ) -> str:
        session = self._runner.sessions.get(session_key)
        if session is None:
            return ""
        session.pending = pending
        self._runner.reply(source, message)
        pending.answered.wait(timeout)
        session.pending = None
        return pending.answer

    # ── answering, on a receive thread ───────────────────────────────────────────────────

    def answer(self, session: GatewaySession, text: str) -> bool:
        """Answer the session's pending question with ``text``; ``True`` as the message is used.

        An approval accepts only the approval words; anything else gets the list of them back,
        and the question stays open.
        """
        pending = session.pending
        assert pending is not None
        if pending.kind == "approval":
            words = text.lower().lstrip("/").split()
            word = words[1] if len(words) > 1 and words[0] == "approve" else (words[0] if words else "")
            choice = _APPROVAL_WORDS.get(word.rstrip(_APPROVAL_TRAILING_PUNCTUATION))
            if choice is None:
                self._runner.reply(
                    session.source, "Please answer /approve, /approve session, /approve always, or /deny."
                )
                return True
            pending.answer = choice
        else:
            pending.answer = (
                pending.choices[int(text) - 1]
                if text.isdigit() and 1 <= int(text) <= len(pending.choices)
                else text
            )
        pending.answered.set()
        return True

    def handle_approval_callback(
        self, source: SessionSource, callback_id: str, data: str, message_id: str
    ) -> None:
        """Resolve an approval button only for its authorized owner and live pending session."""
        adapter = self._runner.adapters.get(source.platform)
        if adapter is None:
            return
        parts = data.split(":", 2)
        if len(parts) != 3 or parts[0] != APPROVAL_PREFIX or parts[2] not in _APPROVAL_WORDS.values():
            adapter.answer_callback(callback_id, "Invalid approval selection.")
            return
        _prefix, key, choice = parts
        if not self._runner.is_authorized(source):
            adapter.answer_callback(callback_id, "You are not authorized.")
            return
        with self._lock:
            prompt = self._prompts.get(key)
            if (
                prompt is None
                or prompt.message_id != message_id
                or prompt.source.platform != source.platform
                or prompt.source.chat_id != source.chat_id
                or prompt.source.thread_id != source.thread_id
                or prompt.source.user_id != source.user_id
                or prompt.pending.answered.is_set()
                or not (session := self._runner.sessions.get(prompt.session_key))
                or session.pending is not prompt.pending
            ):
                adapter.answer_callback(callback_id, "This approval has expired.")
                return
            prompt.pending.answer = choice
            prompt.pending.answered.set()
        self._close_approval_prompt(prompt, f"Approval: {choice}.")
        adapter.answer_callback(callback_id, "Approval recorded.")

    # ── approval buttons ─────────────────────────────────────────────────────────────────

    def _send_approval_buttons(
        self, session: GatewaySession, pending: Pending, command: str, description: str
    ) -> bool:
        """Send approval buttons and bind them to this exact pending question."""
        adapter = self._runner.adapters.get(session.source.platform)
        if adapter is None or not adapter.can_send_buttons():
            return False
        import secrets

        key = secrets.token_urlsafe(8)
        keyboard = approval_keyboard(key)
        text = f"This command needs your approval ({description}):\n\n{command}\n\nChoose an approval option."
        result = adapter.send_approval_prompt(
            session.source.chat_id, text, keyboard, thread_id=session.source.thread_id
        )
        if not result.success or not result.message_id:
            return False
        with self._lock:
            still_pending = session.pending is pending
            if still_pending:
                self._prompts[key] = _ApprovalPrompt(
                    key, session.key, session.source, pending, result.message_id
                )
        if not still_pending:
            # A text reply may arrive between sendMessage returning and this bookkeeping step.
            # Do not leave a live keyboard for an approval that was already resolved.
            adapter.edit_approval_prompt(session.source.chat_id, result.message_id, "Approval: expired.", [])
        return True

    def _close_approval_prompt(self, prompt: _ApprovalPrompt, text: str) -> None:
        """Disable consumed or expired buttons. A failed cosmetic edit never reopens approval."""
        with self._lock:
            if self._prompts.get(prompt.key) is not prompt:
                return
            self._prompts.pop(prompt.key, None)
        adapter = self._runner.adapters.get(prompt.source.platform)
        if adapter is not None:
            adapter.edit_approval_prompt(prompt.source.chat_id, prompt.message_id, text, [])

    def _close_approval_prompt_for(self, pending: Pending, text: str) -> None:
        """Remove the buttons of an approval answered by text or left to time out."""
        with self._lock:
            prompt = next(
                (candidate for candidate in self._prompts.values() if candidate.pending is pending),
                None,
            )
        if prompt is not None:
            self._close_approval_prompt(prompt, text)
