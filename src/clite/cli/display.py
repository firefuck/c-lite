"""Terminal output for the classic CLI: colours, tool progress lines, the banner.

Standard library only. The look is data (a *skin*), so changing colours or the prompt symbol
never means editing this file: drop ``<home>/skins/<name>.yaml`` and set ``display.skin``.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Any, TextIO

import yaml

from clite import __version__
from clite.core.brand import DISPLAY_NAME
from clite.core.constants import get_home
from clite.runtime.presentation import result_failed, tool_preview

_COLORS = {
    "black": "30", "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36",
    "white": "37", "gray": "90", "bright_red": "91", "bright_green": "92", "bright_yellow": "93",
    "bright_blue": "94", "bright_magenta": "95", "bright_cyan": "96", "bold": "1", "dim": "2",
}

BUILTIN_SKINS: dict[str, dict[str, str]] = {
    "default": {
        "prompt": "❯ ", "tool_prefix": "┊", "banner": "bright_cyan", "assistant": "", "tool": "gray",
        "status": "yellow", "error": "bright_red", "info": "gray", "user_prompt": "bright_green",
    },
    "mono": {
        "prompt": "> ", "tool_prefix": "|", "banner": "", "assistant": "", "tool": "", "status": "",
        "error": "", "info": "", "user_prompt": "",
    },
}

def load_skin(name: str) -> dict[str, str]:
    skin = dict(BUILTIN_SKINS["default"])
    if name in BUILTIN_SKINS:
        skin.update(BUILTIN_SKINS[name])
        return skin
    path = get_home() / "skins" / f"{name}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return skin
    if isinstance(data, dict):
        skin.update({key: str(value) for key, value in data.items() if key in skin})
    return skin


class Display:
    def __init__(self, *, skin: str = "default", stream: TextIO | None = None, color: bool | None = None,
                 tool_progress: str = "all") -> None:
        self.out = stream or sys.stdout
        self.skin = load_skin(skin)
        self.tool_progress = tool_progress
        if color is None:
            color = self.out.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
        self.color = color
        self._mid_line = False

    def style(self, text: str, role: str) -> str:
        code = _COLORS.get(self.skin.get(role, ""), "")
        return f"\x1b[{code}m{text}\x1b[0m" if self.color and code else text

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def line(self, text: str = "", role: str = "") -> None:
        self.end_stream()
        self._write((self.style(text, role) if role else text) + "\n")

    # ── the turn ─────────────────────────────────────────────────────────────────────────

    def delta(self, text: str) -> None:
        self._write(self.style(text, "assistant"))
        self._mid_line = not text.endswith("\n")

    def end_stream(self) -> None:
        if self._mid_line:
            self._write("\n")
            self._mid_line = False

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        if self.tool_progress == "verbose":
            self.line(f"{self.skin['tool_prefix']} {name} {json.dumps(args, ensure_ascii=False)[:300]}", "tool")

    def tool_done(self, name: str, args: dict[str, Any], result: str, seconds: float) -> None:
        if self.tool_progress == "off":
            return
        mark = "✗" if result_failed(result) else "✓"
        self.line(f"{self.skin['tool_prefix']} {mark} {name} {tool_preview(name, args)}  ({seconds:.1f}s)", "tool")

    def status(self, kind: str, text: str) -> None:
        if kind != "title":
            self.line(f"[{kind}] {text}", "status")

    def info(self, text: str) -> None:
        self.line(text, "info")

    def error(self, text: str) -> None:
        self.line(text, "error")

    def banner(self, info: dict[str, Any]) -> None:
        width = min(shutil.get_terminal_size((80, 24)).columns, 80)
        self.line(f"{DISPLAY_NAME} {__version__}", "banner")
        self.line(f"{info['model']} via {info['provider']} · {len(info['tools'])} tools · session {info['session_id']}", "info")
        self.line(f"{info['cwd']}", "info")
        self.line("Type a message, /help for commands, Ctrl+C to interrupt, Ctrl+D to exit.", "info")
        self.line("─" * width, "info")
