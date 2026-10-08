"""``BasePlatformAdapter``: the three things a chat platform must do.

Connect and start receiving, send a message, disconnect. Everything else has a default. An
adapter runs its own receive loop (a thread or a webhook) and calls ``self.handle_message``
for each inbound message; it never decides who is allowed or what a command means.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from clite.gateway.event import MessageEvent, SendResult

if TYPE_CHECKING:
    from clite.gateway.runner import GatewayRunner


class BasePlatformAdapter(ABC):
    name = ""
    max_message_length = 4000

    def __init__(self, config: dict[str, Any], runner: GatewayRunner) -> None:
        self.config = config
        self.runner = runner

    @abstractmethod
    def connect(self) -> None:
        """Start receiving. Must return promptly: run the receive loop on its own thread.
        Raise when the platform cannot be reached or the credentials are wrong."""

    @abstractmethod
    def disconnect(self) -> None:
        """Stop receiving and release connections."""

    @abstractmethod
    def send(
        self, chat_id: str, text: str, *, reply_to: str | None = None, thread_id: str | None = None
    ) -> SendResult:
        """Send one message of at most ``max_message_length`` characters."""

    def send_typing(self, chat_id: str, *, thread_id: str | None = None) -> None:
        """Show a "typing" indicator, where the platform has one."""

    def can_edit(self) -> bool:
        """Whether this adapter implements :meth:`edit`. The runner streams only when it does."""
        return False

    def edit(self, chat_id: str, message_id: str, text: str) -> bool:
        """Replace the text of a message this adapter sent. ``False`` when it cannot be done.

        Never raises: a failed edit (rate limit, message too old) leaves the answer to be sent
        whole at the end of the turn.
        """
        return False

    def send_file(
        self, chat_id: str, path: str, *, caption: str = "", thread_id: str | None = None
    ) -> SendResult:
        """Send a local file to a chat. ``False`` when the platform has no upload path.

        Never raises: the tool that calls this reports an unsupported platform to the model.
        """
        return SendResult(False, error=f"{self.name} cannot send files")

    def handle_message(self, event: MessageEvent) -> None:
        """Hand an inbound message to the gateway. Never blocks on the agent's turn."""
        self.runner.dispatch(event)

    def allowed_users(self) -> set[str]:
        return {str(user) for user in self.config.get("allowed_users") or []}


PlatformFactory = Callable[[dict[str, Any], "GatewayRunner"], BasePlatformAdapter]
PLATFORMS: dict[str, PlatformFactory] = {}


def register_platform(name: str, factory: PlatformFactory) -> None:
    PLATFORMS[name] = factory


def split_message(text: str, limit: int) -> list[str]:
    """Split a long reply at paragraph, then line, then word boundaries."""
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = max(window.rfind("\n\n"), 0) or max(window.rfind("\n"), 0) or max(window.rfind(" "), 0) or limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
