"""Keeping a chat live while a turn runs: the typing indicator and the answer as it is written.

Every turn starts a typing indicator, renewed by :class:`TypingKeeper` until the first message
is sent or the turn ends. On an adapter that can edit a sent message, :class:`LiveReply` then
streams the answer through ``stream.py`` and reports tool activity; on one that cannot, the
runner sends the whole answer when the turn is done.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator
from typing import Any

from clite.agent import AgentCallbacks
from clite.core.threads import start_thread
from clite.gateway.event import SessionSource
from clite.gateway.platforms.base import BasePlatformAdapter
from clite.gateway.stream import ProgressReporter, StreamSender, tool_line, tool_message

logger = logging.getLogger("clite.gateway")

DEFAULT_TYPING_INTERVAL = 3.5


class TypingKeeper:
    """Keep a chat typing indicator active until stopped.

    Platforms like Telegram drop the typing action after 4-5 seconds. This helper fires
    an initial typing indicator and repeats it periodically until closed. Thread-safe:
    calling :meth:`stop` or exiting the context immediately stops the heartbeat loop.
    """

    def __init__(
        self,
        adapter: BasePlatformAdapter,
        chat_id: str,
        *,
        thread_id: str | None = None,
        interval: float = DEFAULT_TYPING_INTERVAL,
    ) -> None:
        self.adapter = adapter
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> TypingKeeper:
        self.adapter.send_typing(self.chat_id, thread_id=self.thread_id)
        self._thread = start_thread(self._run, name=f"clite-typing-{self.chat_id}")
        return self

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self.adapter.send_typing(self.chat_id, thread_id=self.thread_id)
            except Exception:  # cosmetic heartbeat failure
                logger.debug("typing heartbeat failed for %s", self.chat_id, exc_info=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

    def __enter__(self) -> TypingKeeper:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()


def start_typing(
    adapter: BasePlatformAdapter | None,
    chat_id: str,
    *,
    thread_id: str | None = None,
    interval: float | None = None,
) -> TypingKeeper | None:
    """A started :class:`TypingKeeper` for ``chat_id``, or ``None`` without an adapter.

    ``interval`` defaults to :data:`DEFAULT_TYPING_INTERVAL` as it is at the time of the call.
    """
    if adapter is None:
        return None
    keeper = TypingKeeper(
        adapter,
        chat_id,
        thread_id=thread_id,
        interval=DEFAULT_TYPING_INTERVAL if interval is None else interval,
    )
    keeper.start()
    return keeper


class LiveReply:
    """How one turn's answer reaches a chat while it is being written.

    A chat that can edit a sent message gets the answer as it is written and one status
    message for tool activity. A chat that cannot keeps the old behaviour: typing indicator,
    then the whole answer. ``message`` mode instead gets one separate chat message per tool
    call, sent as the call starts.
    """

    def __init__(
        self,
        adapter: BasePlatformAdapter,
        source: SessionSource,
        *,
        reply_to: str | None,
        typing_keeper: TypingKeeper | None,
        tool_progress: str,
    ) -> None:
        self.adapter = adapter
        self.chat_id, self.thread_id = source.chat_id, source.thread_id
        self.reply_to = reply_to
        self.typing_keeper = typing_keeper
        self._first_send = True
        self.stream: StreamSender | None = None
        self.progress: ProgressReporter | None = None
        self.per_tool_message = False
        if adapter.can_edit():
            self.stream = StreamSender(self.send, self.edit, max_length=adapter.max_message_length)
            if tool_progress not in ("off", "message"):
                self.progress = ProgressReporter(self.send, self.edit)
            self.per_tool_message = tool_progress == "message"

    def send(self, text: str) -> str | None:
        if self.typing_keeper is not None:
            self.typing_keeper.stop()
        result = self.adapter.send(
            self.chat_id,
            text,
            reply_to=self.reply_to if self._first_send else None,
            thread_id=self.thread_id,
        )
        if result.success:
            self._first_send = False
        return result.message_id if result.success else None

    def edit(self, message_id: str, text: str) -> bool:
        return self.adapter.edit(self.chat_id, message_id, text)

    @contextlib.contextmanager
    def wired(self, callbacks: AgentCallbacks) -> Iterator[None]:
        """Point the session's streaming callbacks at this chat for the turn, then restore them."""
        saved = (callbacks.on_delta, callbacks.on_tool_complete, callbacks.on_tool_start)
        stream, progress = self.stream, self.progress
        if stream is not None:
            callbacks.on_delta = stream.push
        if progress is not None:
            callbacks.on_tool_complete = lambda _call_id, name, args, result, seconds: progress.note(
                tool_line(name, args, result, seconds)
            )
        if self.per_tool_message:

            def on_tool_start(_call_id: str, name: str, args: dict[str, Any]) -> None:
                self.send(tool_message(name, args))

            callbacks.on_tool_start = on_tool_start
        try:
            yield
        finally:
            callbacks.on_delta, callbacks.on_tool_complete, callbacks.on_tool_start = saved
