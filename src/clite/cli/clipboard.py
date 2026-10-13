"""Copy text to the local clipboard, best effort and standard library only.

The classic REPL must run anywhere Python runs, so there is no clipboard dependency. We try
the platform's own tool (``pbcopy``, ``wl-copy``, ``xclip``, ``clip.exe``) and, when none is
present, fall back to the OSC 52 escape sequence, which a terminal over SSH understands. A
copy that cannot happen is reported as text; it never raises.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from typing import TextIO

# (command, args to read stdin) per platform, most specific first.
_TOOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pbcopy", ()),
    ("wl-copy", ()),
    ("xclip", ("-selection", "clipboard")),
    ("xsel", ("--clipboard", "--input")),
    ("clip.exe", ()),
)
OSC52_LIMIT = 100_000  # a terminal will not accept an unbounded OSC 52 payload


def _tool() -> tuple[str, tuple[str, ...]] | None:
    for name, args in _TOOLS:
        if shutil.which(name):
            return name, args
    return None


def write_clipboard_text(text: str, *, stream: TextIO | None = None) -> bool:
    """Put ``text`` on the clipboard. Returns True when a native tool did it."""
    tool = _tool()
    if tool is None:
        return False
    name, args = tool
    try:
        completed = subprocess.run(  # noqa: S603 - a known clipboard tool, no shell
            [name, *args],
            input=text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def write_osc52(text: str, *, stream: TextIO | None = None) -> bool:
    """Copy via the terminal's OSC 52 sequence. Works over SSH, needs terminal support."""
    payload = text[:OSC52_LIMIT]
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    out = stream if stream is not None else sys.stdout
    # tmux and screen wrap OSC 52 differently; wrapping is safe for a plain terminal too.
    if os.environ.get("TMUX"):
        sequence = f"\x1bPtmux;\x1b\x1b]52;c;{encoded}\x07\x1b\\"
    else:
        sequence = f"\x1b]52;c;{encoded}\x07"
    try:
        out.write(sequence)
        out.flush()
    except OSError:
        return False
    return True


def copy_to_clipboard(text: str, *, stream: TextIO | None = None) -> bool:
    """Try a native tool, then OSC 52. True when anything copied the text."""
    if write_clipboard_text(text):
        return True
    return write_osc52(text, stream=stream)
