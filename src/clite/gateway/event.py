"""What a platform adapter hands to the gateway, and what it gets back.

Adapters translate their platform's messages into ``MessageEvent`` and nothing else. All
policy (who may talk to the agent, which session a message belongs to, what a slash command
does) lives in the runner, so every platform behaves the same.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

CHAT_DM, CHAT_GROUP, CHAT_CHANNEL = "dm", "group", "channel"


@dataclass(frozen=True)
class SessionSource:
    """Where a message came from. Enough to route a reply and to key a session."""

    platform: str
    chat_id: str
    user_id: str = ""
    user_name: str = ""
    chat_type: str = CHAT_DM
    thread_id: str | None = None
    chat_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"platform": self.platform, "chat_id": self.chat_id, "user_id": self.user_id, "user_name": self.user_name,
                "chat_type": self.chat_type, "thread_id": self.thread_id, "chat_name": self.chat_name}


@dataclass
class MessageEvent:
    text: str
    source: SessionSource
    message_id: str = ""
    reply_to: str | None = None
    attachments: list[str] = field(default_factory=list)  # local paths the adapter downloaded
    timestamp: float = field(default_factory=time.time)
    raw: Any = None


@dataclass
class SendResult:
    success: bool
    message_id: str = ""
    error: str = ""
