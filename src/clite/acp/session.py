"""``AcpSession``: a ``ChatSession`` as one ACP session.

This is the translation layer and nothing else — the conversation, the tools and the
approvals all live in ``clite.runtime``. A prompt becomes a turn, the agent's callbacks
become ``session/update`` notifications, and an approval the agent asks for becomes a
``session/request_permission`` to the editor.

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
from clite.runtime.session import ChatSession

if TYPE_CHECKING:
    from clite.acp.server import AcpServer

logger = logging.getLogger("clite.acp.session")


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

    def _callbacks(self) -> AgentCallbacks:
        def on_status(kind: str, text: str) -> None:
            # The only status ACP has a place for is the session's title; the rest (compaction,
            # retries, fallbacks) are log lines, not something an editor shows.
            if kind == "title":
                self._update({"sessionUpdate": "session_info_update", "title": str(self.chat.info()["title"])})

        return AgentCallbacks(
            on_delta=lambda text: self._chunk("agent_message_chunk", text),
            on_reasoning=lambda text: self._chunk("agent_thought_chunk", text),
            on_status=on_status,
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
