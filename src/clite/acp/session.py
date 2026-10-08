"""``AcpSession``: a ``ChatSession`` as one ACP session.

This is the translation layer and nothing else — the conversation, the tools and the
approvals all live in ``clite.runtime``. A prompt becomes a turn, the agent's callbacks
become ``session/update`` notifications, and an approval the agent asks for becomes a
``session/request_permission`` to the editor.

What is translated here is the vocabulary: a tool name becomes an ACP ``kind``, a tool result
becomes a ``tool_call_update``, and the client's answer to a permission request becomes the
choice the approval gate understands.

ACP asks for a turn the way the RPC protocol does not: ``session/prompt`` is one request whose
result is the end of the turn, so its handler blocks for the length of the turn while the text
travels ahead of it as notifications. That is why the protocol is spoken on a worker pool (see
``clite.acp.server``): ``session/cancel`` has to be read while the prompt is still running.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from clite.acp.server import REQUEST_FAILED, SESSION_BUSY, AcpError
from clite.agent import AgentCallbacks, TurnResult
from clite.core.config import config_get
from clite.runtime.presentation import result_failed, tool_preview
from clite.runtime.session import ChatSession

if TYPE_CHECKING:
    from clite.acp.server import AcpServer

logger = logging.getLogger("clite.acp.session")

# How much of a tool result is sent back to the editor. The same clip the RPC surface uses: a
# tool that writes a megabyte must not put a megabyte between two protocol messages.
RESULT_PREVIEW_CHARS = 400

# ACP's tool-call kinds, from what the tool does. Anything not named here is "other": the
# vocabulary belongs to the client, and a tool added later still has a place to show up.
TOOL_KINDS = {
    "read_file": "read",
    "vision_analyze": "read",
    "search_files": "search",
    "session_search": "search",
    "skills_list": "search",
    "web_fetch": "fetch",
    "web_search": "fetch",
    "write_file": "edit",
    "patch": "edit",
    "terminal": "execute",
    "execute_code": "execute",
    "process": "execute",
}

# What the editor may answer, and what the agent does with each answer. The option *kind* comes
# from ACP's fixed list, but the id is ours to write: remembering a pattern for this session is
# what c-lite can do, and it is not the same as remembering it forever, so it gets its own
# option — offered with the kind ``allow_once`` and honoured as a session approval.
PERMISSION_OPTIONS = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "allow_session", "name": "Allow for this session", "kind": "allow_once"},
    {"optionId": "allow_always", "name": "Always allow", "kind": "allow_always"},
    {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
]
PERMISSION_CHOICES = {"allow_once": "once", "allow_session": "session", "allow_always": "always"}


def tool_kind(name: str) -> str:
    """The ACP kind of a tool call, for the icon and the verb an editor shows."""
    return TOOL_KINDS.get(name, "other")


def permission_choice(reply: dict[str, Any] | None) -> str:
    """What the agent does with the client's answer to a permission request.

    Silence — no answer, a timeout, a connection that ended — a cancelled prompt, and an option
    we never offered all mean no. Anything else would let a client unlock a command by saying
    nothing at all.
    """
    outcome = reply.get("outcome") if isinstance(reply, dict) else None
    if not isinstance(outcome, dict) or outcome.get("outcome") != "selected":
        return "deny"
    return PERMISSION_CHOICES.get(outcome.get("optionId"), "deny")


def stop_reason(result: TurnResult) -> str:
    """The ACP ``stopReason`` for a finished turn.

    A turn that ended without an answer — the provider failed, the model said nothing — is not
    a stop reason: the client is told the request failed instead of being shown an empty reply.
    """
    if result.interrupted or result.exit_reason == "interrupted":
        return "cancelled"
    if result.completed:
        return "end_turn"
    if result.exit_reason == "refusal":
        return "refusal"
    if result.exit_reason == "budget_exhausted":
        return "max_turn_requests"
    raise AcpError(REQUEST_FAILED, result.error or f"the turn ended without an answer ({result.exit_reason})")


class AcpSession:
    def __init__(
        self,
        server: AcpServer,
        session_id: str,
        *,
        cwd: str | None = None,
        client_factory: Any = None,
        model: str | None = None,
        provider: str | None = None,
        toolsets: list[str] | None = None,
        yolo: bool = False,
    ) -> None:
        self.server = server
        self.id = session_id
        self.cwd = cwd
        # One turn at a time, and the lock is held for as long as the turn runs: a second
        # ``session/prompt`` is refused with ``session busy`` rather than queued, because the
        # protocol has no place to put a turn the client did not ask for yet.
        self._running = threading.Lock()
        # The tool calls this session has announced but not finished, by toolCallId. The entry
        # is kept because a permission request has to name the call it is about.
        self._calls: dict[str, dict[str, Any]] = {}
        self._calls_lock = threading.Lock()
        # Which call the thread asking for approval is running: tools run in parallel, so the
        # question "which tool is asking?" is answered per thread, not per session.
        self._call_on_thread = threading.local()
        self._approvals = 0
        self.chat = ChatSession(
            platform=server.platform,
            callbacks=self._callbacks(),
            model=model,
            provider=provider,
            toolsets=toolsets,
            cwd=cwd,
            yolo=yolo,
            client=client_factory() if client_factory else None,
        )

    # ── callbacks -> session/update ──────────────────────────────────────────────────────

    def _update(self, update: dict[str, Any]) -> None:
        self.server.notify("session/update", {"sessionId": self.id, "update": update})

    def _chunk(self, kind: str, text: str) -> None:
        if text:
            self._update({"sessionUpdate": kind, "content": {"type": "text", "text": text}})

    def _running_call(self) -> dict[str, Any] | None:
        """The tool call the thread asking for approval is running, if any."""
        call_id = getattr(self._call_on_thread, "value", None)
        with self._calls_lock:
            return self._calls.get(call_id) if call_id else None

    def _stand_in_call(self, command: str) -> dict[str, Any]:
        """A tool call to hang a permission request on when no tool call is running.

        Nothing in this agent asks for approval outside a tool today, but the protocol wants
        the request to point at something, and a question with no attachment shows up in an
        editor as a question about nothing.
        """
        with self._calls_lock:
            self._approvals += 1
            number = self._approvals
        return {
            "toolCallId": f"approval-{number}",
            "title": command,
            "kind": "execute",
            "status": "pending",
            "rawInput": {"command": command},
            "content": [],
        }

    def _callbacks(self) -> AgentCallbacks:
        def on_status(kind: str, text: str) -> None:
            # The only status ACP has a place for is the session's title; the rest (compaction,
            # retries, fallbacks) are log lines, not something an editor shows.
            if kind == "title":
                self._update({"sessionUpdate": "session_info_update", "title": str(self.chat.info()["title"])})

        def on_tool_start(call_id: str, name: str, args: dict[str, Any]) -> None:
            self._call_on_thread.value = call_id
            call: dict[str, Any] = {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                # The title is what the editor puts next to the kind's verb: the file, the
                # command, the question — not the tool's name, which the kind already says.
                "title": tool_preview(name, args) or name,
                "kind": tool_kind(name),
                # This fires as the tool starts, with the approval it may still ask for as part
                # of the run, so the call is running, not pending.
                "status": "in_progress",
                "rawInput": args,
                "content": [],
            }
            path = args.get("path")
            if isinstance(path, str) and path:
                call["locations"] = [{"path": path}]  # an editor can open the file being worked on
            with self._calls_lock:
                self._calls[call_id] = call
            self._update(call)

        def on_tool_complete(
            call_id: str, name: str, args: dict[str, Any], result: str, seconds: float
        ) -> None:
            with self._calls_lock:
                self._calls.pop(call_id, None)
            self._call_on_thread.value = None
            self._update(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": call_id,
                    "status": "failed" if result_failed(result) else "completed",
                    # The result travels as text and clipped. ``rawOutput`` is left out on
                    # purpose: it may hold the same payload unclipped, which is how a tool that
                    # read a large file ends up between two protocol messages.
                    "content": [
                        {
                            "type": "content",
                            "content": {"type": "text", "text": result[:RESULT_PREVIEW_CHARS] or "(no output)"},
                        }
                    ],
                }
            )

        def approve(*, command: str, description: str, pattern_keys: list[str]) -> str:
            call = self._running_call() or self._stand_in_call(command)
            tool_call = {key: value for key, value in call.items() if key != "sessionUpdate"}
            reply = self.server.request_client(
                "session/request_permission",
                {"sessionId": self.id, "toolCall": tool_call, "options": PERMISSION_OPTIONS},
                timeout=float(config_get("approvals.timeout", 300) or 300),
            )
            return permission_choice(reply)

        return AgentCallbacks(
            on_delta=lambda text: self._chunk("agent_message_chunk", text),
            on_reasoning=lambda text: self._chunk("agent_thought_chunk", text),
            on_tool_start=on_tool_start,
            on_tool_complete=on_tool_complete,
            on_status=on_status,
            approve=approve,
        )

    # ── turns ────────────────────────────────────────────────────────────────────────────

    def prompt(self, text: str) -> str:
        """Run one turn and return its ``stopReason``. Blocks until the turn is over."""
        if not self._running.acquire(blocking=False):
            raise AcpError(SESSION_BUSY, "a turn is already running in this session")
        try:
            result = self.chat.submit(text)
        finally:
            self._running.release()
        return stop_reason(result)

    def cancel(self) -> None:
        """Ask the running turn to stop; its prompt request answers ``cancelled``."""
        self.chat.interrupt()

    @property
    def busy(self) -> bool:
        return self._running.locked() or self.chat.busy

    def close(self) -> None:
        self.cancel()
        self.chat.close("acp_closed")
