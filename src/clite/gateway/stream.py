"""Streaming answers into a chat: one message that grows, instead of a long silence.

An adapter that can edit a sent message (``edit(chat_id, message_id, text)``) lets the runner
show the answer as it is written. This module holds the rate limiting and the splitting, so the
runner stays policy-only and the adapter stays a thin transport.

The sender is a plain object with no I/O of its own: it is handed a ``send`` and an ``edit``
function and a clock, which is what makes it testable without a platform.
"""

from __future__ import annotations

import time
from collections.abc import Callable

# A chat platform's edit endpoint is rate limited (Telegram allows about one edit per message
# per second; Discord and Slack are looser but not free). One and a half seconds keeps a fast
# model from being throttled while still looking live.
DEFAULT_MIN_EDIT_INTERVAL = 1.5


class StreamSender:
    """Grow one chat message as the answer streams, then settle it.

    ``send(text) -> message id or None`` and ``edit(message_id, text) -> bool`` come from the
    adapter. The runner builds one of these only when the adapter can edit; when an edit fails
    mid-stream the sender stops editing and the remainder is sent as its own message at
    :meth:`finish`, so a platform rate limit never loses the answer.
    """

    def __init__(
        self,
        send: Callable[[str], str | None],
        edit: Callable[[str, str], bool],
        *,
        max_length: int,
        min_interval: float = DEFAULT_MIN_EDIT_INTERVAL,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._send = send
        self._edit = edit
        self._max_length = max(1, int(max_length))
        self._min_interval = max(0.0, float(min_interval))
        self._now = now
        self._full = ""
        self._settled_len = 0  # text on screen in messages that are never edited again
        self._live_id: str | None = None
        self._live_shown_len = 0  # how much of the live message is actually on screen
        self._last_update: float | None = None
        self._edit_broken = False
        self.sends = 0
        self.edits = 0

    @property
    def text(self) -> str:
        return self._full

    def push(self, delta: str) -> None:
        """Append streamed text and, when the rate limit allows, show it."""
        if not delta:
            return
        self._full += delta
        self._update(force=False)

    def finish(self, final_text: str | None = None) -> str:
        """Flush everything and return the text that was shown.

        ``final_text`` is the authoritative answer. When it differs from what was streamed (a
        surface may strip reasoning or normalise whitespace) it wins: what is already on screen
        is kept and only the difference is sent.
        """
        if final_text is not None and final_text != self._full:
            if final_text.startswith(self._full):
                self._full = final_text  # only a tail was missing; keep what is on screen
            else:
                self._settle_live()
                self._settled_len = 0
                self._live_id = None
                self._full = final_text
        self._update(force=True)
        return self._full

    # ── internals ────────────────────────────────────────────────────────────────────────

    def _settle_live(self) -> None:
        """Leave the live message on screen as it is and stop editing it."""
        if self._live_id is not None:
            self._settled_len += self._live_shown_len
            self._live_id = None
            self._live_shown_len = 0

    def _update(self, *, force: bool) -> None:
        if not self._full:
            return
        if not force and self._edit_broken:
            return  # keep accumulating; finish() sends the remainder
        if (
            not force
            and self._last_update is not None
            and (self._now() - self._last_update) < self._min_interval
        ):
            return
        if self._edit_broken:
            self._settle_live()

        live_target = self._full[self._settled_len :]
        # Anything past the platform limit becomes its own finalized message; the live message
        # keeps only the tail, so an edit never has to shrink the text.
        while len(live_target) > self._max_length:
            head, live_target = live_target[: self._max_length], live_target[self._max_length :]
            if self._live_id is not None:
                if self._edit(self._live_id, head):
                    self.edits += 1
                else:
                    self._edit_broken = True
            if self._live_id is None or self._edit_broken:
                self._send(head)
                self.sends += 1
            self._settled_len += len(head)
            self._live_id = None
            self._live_shown_len = 0

        if not live_target:
            self._last_update = self._now()
            return

        if self._live_id is None:
            self._live_id = self._send(live_target)
            self.sends += 1
            if self._live_id is None:
                # Nothing to edit later: the text is already on screen, so the tail waits.
                self._edit_broken = True
                self._settled_len = len(self._full)
            else:
                self._live_shown_len = len(live_target)
            self._last_update = self._now()
            return

        if self._edit(self._live_id, live_target):
            self.edits += 1
            self._live_shown_len = len(live_target)
            self._last_update = self._now()
        else:
            # A rejected edit (rate limit, message too old) must not lose the answer.
            self._edit_broken = True


# How many tool lines the progress message keeps. A long turn should read as "what is happening
# now", not as an unbounded log the user has to scroll.
PROGRESS_MAX_LINES = 8


class ProgressReporter:
    """One chat message that lists tool activity and is updated in place.

    The alternative -- a message per tool -- buries the answer under notifications. The reporter
    keeps the last :data:`PROGRESS_MAX_LINES` lines so the message stays readable, and it stops
    updating (without failing the turn) when the platform refuses an edit.
    """

    def __init__(
        self,
        send: Callable[[str], str | None],
        edit: Callable[[str, str], bool],
        *,
        max_lines: int = PROGRESS_MAX_LINES,
    ) -> None:
        self._send = send
        self._edit = edit
        self._max_lines = max(1, int(max_lines))
        self._lines: list[str] = []
        self._message_id: str | None = None
        self._broken = False

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    def note(self, line: str) -> None:
        """Record one tool line and show the updated message."""
        line = line.strip()
        if not line or self._broken:
            return
        self._lines.append(line)
        self._show()

    def _show(self) -> None:
        body = "\n".join(self._lines[-self._max_lines :])
        if self._message_id is None:
            self._message_id = self._send(body)
            self._broken = self._message_id is None
            return
        if not self._edit(self._message_id, body):
            self._broken = True


def tool_line(name: str, result: str, seconds: float) -> str:
    """A one-line summary of a finished tool call, the same shape the CLI prints."""
    from clite.runtime.presentation import result_failed

    mark = "✗" if result_failed(result) else "✓"
    return f"{mark} {name} ({seconds:.1f}s)"
