"""``AcpSession``: a ``ChatSession`` as one ACP session.

This is the translation layer and nothing else — the conversation, the tools and the
approvals all live in ``clite.runtime``. A prompt becomes a turn, the agent's callbacks
become ``session/update`` notifications, and an approval the agent asks for becomes a
``session/request_permission`` to the editor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from clite.agent import AgentCallbacks
from clite.runtime.session import ChatSession

if TYPE_CHECKING:
    from clite.acp.server import AcpServer

logger = logging.getLogger("clite.acp.session")


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

    def _callbacks(self) -> AgentCallbacks:
        return AgentCallbacks()

    @property
    def busy(self) -> bool:
        return self.chat.busy

    def close(self) -> None:
        self.chat.close("acp_closed")
