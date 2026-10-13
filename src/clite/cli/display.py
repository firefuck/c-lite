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
from clite.cli.markdown import MarkdownStream, MarkdownStyle, render_diff
from clite.core.brand import DISPLAY_NAME
from clite.core.constants import get_home
from clite.runtime.presentation import markdown_role_codes, result_failed, tool_diffs, tool_preview

_COLORS = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "gray": "90",
    "bright_red": "91",
    "bright_green": "92",
    "bright_yellow": "93",
    "bright_blue": "94",
    "bright_magenta": "95",
    "bright_cyan": "96",
    "bold": "1",
    "dim": "2",
}

BUILTIN_SKINS: dict[str, dict[str, str]] = {
    "default": {
        "prompt": "❯ ",
        "tool_prefix": "┊",
        "banner": "bright_cyan",
        "assistant": "",
        "tool": "gray",
        "status": "yellow",
        "error": "bright_red",
        "info": "gray",
        "user_prompt": "bright_green",
        # Markdown and diff colouring: the renderer names a role, the skin picks its colour.
        "md_heading": "bold",
        "md_code": "cyan",
        "md_fence": "dim",
        "md_table": "white",
        "md_marker": "bright_yellow",
        "md_quote": "cyan",
        "md_rule": "dim",
        "md_link": "bright_blue",
        "diff_add": "green",
        "diff_del": "red",
        "diff_hunk": "bright_cyan",
        "diff_file": "bold",
        "diff_context": "dim",
    },
    "mono": {
        "prompt": "> ",
        "tool_prefix": "|",
        "banner": "",
        "assistant": "",
        "tool": "",
        "status": "",
        "error": "",
        "info": "",
        "user_prompt": "",
        # A monochrome skin leaves every colour blank: the renderer then emits plain text.
        "md_heading": "",
        "md_code": "",
        "md_fence": "",
        "md_table": "",
        "md_marker": "",
        "md_quote": "",
        "md_rule": "",
        "md_link": "",
        "diff_add": "",
        "diff_del": "",
        "diff_hunk": "",
        "diff_file": "",
        "diff_context": "",
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
    def __init__(
        self,
        *,
        skin: str = "default",
        stream: TextIO | None = None,
        color: bool | None = None,
        tool_progress: str = "all",
        width: int | None = None,
        diff_lines: int = 200,
    ) -> None:
        self.out = stream or sys.stdout
        self.skin = load_skin(skin)
        self.tool_progress = tool_progress
        if color is None:
            color = (
                self.out.isatty()
                and "NO_COLOR" not in os.environ
                and os.environ.get("TERM") not in (None, "", "dumb")
            )
        self.color = color
        self.width = width or min(shutil.get_terminal_size((80, 24)).columns, 120)
        self.diff_lines = diff_lines
        self._mid_line = False
        self._md: MarkdownStream | None = None
        self._md_printed = ""

    def style(self, text: str, role: str) -> str:
        code = _COLORS.get(self.skin.get(role, ""), "")
        return f"\x1b[{code}m{text}\x1b[0m" if self.color and code else text

    def markdown_style(self) -> MarkdownStyle:
        """The Markdown/diff role map for this skin, empty when colour is off.

        The renderer never chooses a colour: this is the only place the skin is turned into
        escapes, and ``NO_COLOR`` / a dumb terminal / redirected output simply yields none.
        """
        if not self.color:
            return MarkdownStyle.none()
        return MarkdownStyle.from_codes(markdown_role_codes(self.skin))

    def markdown_stream(self, width: int | None = None) -> MarkdownStream:
        """A staged renderer for a streamed answer, coloured as the skin asks."""
        return MarkdownStream(style=self.markdown_style(), width=width or self.width)

    def render_markdown(self, text: str, width: int | None = None) -> str:
        """Render a whole Markdown answer to the text this display would show."""
        from clite.cli.markdown import render_markdown

        return render_markdown(text, style=self.markdown_style(), width=width or self.width)

    def diff(self, diff: str) -> None:
        """Show a unified diff (from ``patch`` or ``write_file``) in the skin's colours."""
        text = render_diff(diff, style=self.markdown_style(), max_lines=self.diff_lines)
        if text:
            self.line(text.rstrip("\n"))

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def line(self, text: str = "", role: str = "") -> None:
        self.end_stream()
        self._write((self.style(text, role) if role else text) + "\n")

    # ── the turn ─────────────────────────────────────────────────────────────────────────

    def delta(self, text: str) -> None:
        if self._md is None:
            self._md = self.markdown_stream()
            self._md_printed = ""
            self._mid_line = False
        self._md.feed(text)
        self._flush_markdown()

    def reasoning(self, text: str) -> None:
        """A streamed reasoning delta: shown as typed, never read as Markdown."""
        self._write(self.style(text, "info"))
        self._mid_line = not text.endswith("\n")

    def _flush_markdown(self) -> None:
        """Write whatever of the answer's current appearance is not on screen yet.

        :meth:`MarkdownStream.view` includes the unfinished line, so an answer shows while it
        is being typed, not only when it is complete. A finished line replaces its own raw
        text; a terminal can be asked to rewrite the line, other streams cannot — so there,
        only the settled part is shown to avoid printing the line twice.
        """
        view = self._md.view() if self._md is not None else ""
        printed = self._md_printed
        if view == printed:
            return
        common = 0
        limit = min(len(view), len(printed))
        while common < limit and view[common] == printed[common]:
            common += 1
        if common < len(printed):
            # The line changed shape (e.g. ``**bold**`` became bold): redraw where we can.
            if self.color:
                self._write("\r\x1b[K" + view[common:])
            else:
                self._write(view[common:])
        else:
            self._write(view[common:])
        self._md_printed = view
        self._mid_line = bool(view) and not view.endswith("\n")

    def end_stream(self) -> None:
        if self._md is not None:
            self._md.close()
            self._flush_markdown()
            self._md = None
            self._md_printed = ""
        if self._mid_line:
            self._write("\n")
            self._mid_line = False

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        if self.tool_progress == "verbose":
            self.line(
                f"{self.skin['tool_prefix']} {name} {json.dumps(args, ensure_ascii=False)[:300]}", "tool"
            )

    def tool_done(self, name: str, args: dict[str, Any], result: str, seconds: float) -> None:
        if self.tool_progress == "off":
            return
        mark = "✗" if result_failed(result) else "✓"
        self.line(
            f"{self.skin['tool_prefix']} {mark} {name} {tool_preview(name, args)}  ({seconds:.1f}s)", "tool"
        )
        # A file-changing tool ships a diff; show it so the change is readable at a glance.
        for _path, diff in tool_diffs(result):
            self.diff(diff)

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
        self.line(
            f"{info['model']} via {info['provider']} · {len(info['tools'])} tools · session {info['session_id']}",
            "info",
        )
        self.line(f"{info['cwd']}", "info")
        self.line("Type a message, /help for commands, Ctrl+C to interrupt, Ctrl+D to exit.", "info")
        self.line("─" * width, "info")
