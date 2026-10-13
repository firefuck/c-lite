"""Render an assistant answer written in Markdown, and a unified diff, to terminal text.

The renderer works **in stages**, because answers arrive streamed: a line that is complete is
rendered at once, while a line that is still being typed is held back, so nothing is painted
half a sentence and then repainted. :class:`MarkdownStream` is that hold-and-flush machine;
:func:`render_markdown` is the whole-document path (a stored answer, an export, a test).
Feeding one text through a stream in any fragmentation must give exactly the same string as
rendering it whole — that invariant is what the tests pin down.

Everything here is a pure function of its arguments: no stream is read or written, and the
renderer never decides for itself whether colour is wanted. Colour is **data**: a
:class:`MarkdownStyle` maps a semantic role (``heading``, ``code``, ``diff_add`` …) to an ANSI
escape that the caller built from the active skin. When the style is empty the same functions
return plain text — the ``NO_COLOR`` / ``dumb`` terminal / redirected output path — and the
structure still stands out through indentation and symbols.

Two things are deliberately *not* run through the Markdown grammar: a fenced code block is kept
verbatim (its ``#`` and ``**`` are code, not markup), and a table wider than the terminal is
cut to fit instead of soft-wrapping mid-cell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["MarkdownStream", "MarkdownStyle", "render_diff", "render_markdown"]

_RULE = "─"
_DEFAULT_WIDTH = 80
_RULE_WIDTH = 40  # a horizontal rule is a visual break, not a full-width bar


@dataclass(frozen=True)
class MarkdownStyle:
    """A role-to-ANSI-escape mapping. Empty means plain text.

    The renderer names *roles*, never codes: ``style.paint("heading", "Title")`` is the one
    place an escape is emitted, and the escape came in from the caller.
    """

    codes: dict[str, str]

    @classmethod
    def none(cls) -> MarkdownStyle:
        return cls({})

    @classmethod
    def from_codes(cls, codes: dict[str, str]) -> MarkdownStyle:
        return cls({role: code for role, code in codes.items() if code})

    def is_plain(self) -> bool:
        """True when no role has a colour: the output is plain, readable text."""
        return not self.codes

    def paint(self, role: str, text: str) -> str:
        code = self.codes.get(role)
        return f"\x1b[{code}m{text}\x1b[0m" if code else text


# ── inline markup ─────────────────────────────────────────────────────────────────────────

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")


def _inline(text: str, style: MarkdownStyle) -> str:
    """Unwrap inline markup, painting each fragment with its role."""
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _INLINE_CODE.sub(lambda m: style.paint("code", m.group(1)), text)
    text = _BOLD.sub(lambda m: style.paint("heading", (m.group(1) or m.group(2) or "")), text)
    return _ITALIC.sub(lambda m: style.paint("quote", (m.group(1) or m.group(2) or "")), text)


# ── tables ───────────────────────────────────────────────────────────────────────────────

_TABLE_DIVIDER_CELL = re.compile(r"^\s*:?-{3,}:?\s*$")


def _split_row(row: str) -> list[str]:
    s = row.strip()
    s = s.removeprefix("|")
    s = s.removesuffix("|")
    return [cell.strip() for cell in s.split("|")]


def _is_divider(row: str) -> bool:
    cells = _split_row(row)
    return len(cells) > 1 and all(_TABLE_DIVIDER_CELL.match(cell) for cell in cells)


def _could_open_table(line: str) -> bool:
    """True when a line might be the header of a table whose divider has not arrived yet.

    Anything with more than one cell is ambiguous until the next line is known, so a stream
    keeps it back rather than rendering it as an ordinary paragraph.
    """
    stripped = line.strip()
    return "|" in stripped and len(_split_row(stripped)) > 1


def _unsettled_tail(lines: list[str]) -> int:
    """Count the trailing lines a stream must hold back because they may still change meaning.

    A table grows by rows, so the whole trailing table waits for a line that ends it. A single
    trailing row-looking line waits too, in case the next line is a divider that makes it a
    table header.
    """
    if not lines:
        return 0
    if not _could_open_table(lines[-1]):
        return 0
    # Walk back over the trailing run of table-shaped lines to find the whole table.
    start = len(lines)
    while start > 0 and _could_open_table(lines[start - 1]):
        start -= 1
    # A table needs a header *and* a divider above its rows, so hold the whole run: the stream
    # cannot tell yet whether the next line closes it.
    return len(lines) - start


def _plain_head(line: str) -> str:
    """The prefix of an unfinished line that renders exactly as it is typed.

    Markdown gives meaning to ``* _ ` [ ] ( ) # > ~ | < & \\`` and to list markers, so an
    unfinished line is only shown up to the first of those. Past it the raw text may differ
    from what the finished line renders to, and a stream that cannot rewrite a line would
    print it twice.
    """
    stop = len(line)
    for index, char in enumerate(line):
        if char in _MEANINGFUL:
            stop = index
            break
    return line[:stop]


def _visible_len(text: str) -> int:
    return len(re.sub(r"\x1b\[[0-9;]*m", "", text))


def _cut(text: str, limit: int) -> str:
    """Truncate to ``limit`` visible columns, marking the cut with an ellipsis."""
    if _visible_len(text) <= limit:
        return text
    if limit <= 1:
        return "…"[:limit]
    return text[: limit - 1] + "…"


def _render_table(rows: list[list[str]], style: MarkdownStyle, width: int) -> list[str]:
    """Rebuild a table with uniform column widths, truncated to the terminal."""
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    widths = [max(1, *(len(row[c]) for row in rows)) for c in range(columns)]
    gap = "  "
    # Trim the widest columns right-to-left until the table fits ``width``.
    available = width - len(gap) * (columns - 1)
    for column in sorted(range(columns), key=lambda c: widths[c], reverse=True):
        if sum(widths) <= available:
            break
        overflow = sum(widths) - available
        widths[column] = max(1, widths[column] - overflow)
    lines = []
    for row in rows:
        cells = [_cut(row[c], widths[c]).ljust(widths[c]) for c in range(columns)]
        lines.append(style.paint("table", gap.join(cells).rstrip()))
    return lines


# ── block rendering ──────────────────────────────────────────────────────────────────────

_FENCE = re.compile(r"^\s*(```+|~~~+)")

# Characters Markdown may give meaning to: an unfinished line is only shown up to the first.
_MEANINGFUL = frozenset("*_`[]()#>~|<&\\")


def _render_line(line: str, style: MarkdownStyle, width: int) -> str:
    if not line:
        return ""
    if _heading := _HEADING.match(line):
        return style.paint("heading", _inline(_heading.group(2), style))
    if _quote := _QUOTE.match(line):
        return style.paint("quote", "│ " + _inline(_quote.group(1), style))
    if line.strip() in ("---", "***", "___"):
        return style.paint("rule", _RULE * min(width, _RULE_WIDTH))
    if _ordered := _ORDERED.match(line):
        indent, number, body = _ordered.groups()
        return f"{indent}  {style.paint('marker', number + '.')} {_inline(body, style)}"
    if _bullet := _BULLET.match(line):
        indent, body = _bullet.groups()
        return f"{indent}  {style.paint('marker', '•')} {_inline(body, style)}"
    return _inline(line, style)


def _render_blocks(lines: list[str], style: MarkdownStyle, width: int) -> list[str]:
    """Render complete lines, buffering a table so its columns can be measured."""
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "|" in line and index + 1 < len(lines) and _is_divider(lines[index + 1]):
            rows = [_split_row(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                if not _is_divider(lines[index]):
                    rows.append(_split_row(lines[index]))
                index += 1
            out.extend(_render_table(rows, style, width))
            continue
        out.append(_render_line(line, style, width))
        index += 1
    return out


def _render_fence_line(line: str, style: MarkdownStyle) -> str:
    return style.paint("code", line)


# ── the public interface ─────────────────────────────────────────────────────────────────


def render_markdown(text: str, *, style: MarkdownStyle | None = None, width: int = _DEFAULT_WIDTH) -> str:
    """Render a whole Markdown document. Equivalent to one stream fed ``text`` then closed."""
    stream = MarkdownStream(style=style, width=width)
    return stream.feed(text) + stream.close()


class MarkdownStream:
    """Stage a Markdown answer as it streams: hold the unfinished line, render the rest.

    The object is pure: it holds state but touches no I/O, and calling :meth:`feed` and
    :meth:`close` in the same order always yields the same string.
    """

    def __init__(self, *, style: MarkdownStyle | None = None, width: int = _DEFAULT_WIDTH) -> None:
        self.style = style or MarkdownStyle.none()
        self.width = width
        self._held = ""  # the line being typed, without its newline yet
        self._decided: list[str] = []  # complete lines whose meaning is known
        self._in_fence = False
        self._fence_buffer: list[str] = []  # a fenced block, kept until it closes
        self._emitted = ""  # everything feed/close has returned so far

    def view(self) -> str:
        """The whole answer as it should look right now, unfinished line included.

        :meth:`feed` returns only what is *settled*; a live surface can instead track this
        string and print each new suffix as it grows, so an unfinished line shows while it
        is being typed. Pure, like everything else: same state, same string.
        """
        pending = self._pending_raw()
        return self._emitted + pending

    def _pending_raw(self) -> str:
        """The decided-but-unrendered tail: held-back table lines and the unfinished line.

        Only the plainly-typeable head of the unfinished line is offered, up to the first
        character that Markdown gives meaning to. Past that the raw text may not be what the
        finished line renders to (``**bo`` becomes bold ``bo``), and a stream that cannot
        rewrite a line would print it twice, so that part waits for the line to settle.
        """
        lines = list(self._decided)
        if not self._in_fence:
            lines = lines[: len(lines) - _unsettled_tail(lines)]
        if self._held:
            lines.append(_plain_head(self._held))
        return "\n".join(part for part in lines)

    def feed(self, chunk: str) -> str:
        """Take a piece of the answer and return the text that is now safe to show.

        A complete line is not always safe: a lone ``| a | b |`` may be the first row of a
        table whose divider has not arrived, so it is held until the next line settles it.
        """
        self._held += chunk
        if "\n" not in self._held:
            return ""
        *complete, self._held = self._held.split("\n")
        self._decided.extend(complete)
        # More may always arrive, so nothing is settled yet: an unsettled tail waits.
        out = self._render(settle=False)
        self._emitted += out
        return out

    def close(self) -> str:
        """Flush whatever is still held: the answer has ended.

        A fenced block that never closed is flushed as code, newlines and all. A half-typed
        ordinary line is emitted without a trailing newline, so the surface showing the
        answer stays in charge of the line break at the very end.
        """
        held, self._held = self._held, ""
        if held:
            self._decided.append(held)
        out = self._render(settle=True, closed=True)
        if held and not self._in_fence and out.endswith("\n"):
            out = out[:-1]
        self._emitted += out
        return out

    # ── internals ────────────────────────────────────────────────────────────────────────

    def _flush_fence(self) -> str:
        rendered = "".join(_render_fence_line(line, self.style) + "\n" for line in self._fence_buffer)
        self._fence_buffer.clear()
        return rendered

    def _render(self, *, settle: bool, closed: bool = False) -> str:
        """Render the decided lines, holding back whatever is still unsettled.

        While more text may arrive, a trailing table is not finished: it could grow another
        row, and a lone ``| a | b |`` could still turn out to be a table header. Those lines
        are left for the next round so a stray line is never rendered the wrong way.
        """
        lines = self._decided
        if not settle and not self._in_fence:
            lines = lines[: len(lines) - _unsettled_tail(lines)]
        out: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if self._in_fence:
                if _FENCE.match(line):
                    self._in_fence = False
                    out.append(self._flush_fence())
                else:
                    self._fence_buffer.append(line)
                index += 1
                continue
            if _FENCE.match(line):
                # A fenced block is buffered whole: nothing inside it is Markdown.
                self._in_fence = True
                index += 1
                continue
            # Collect the run of non-fenced lines so a table can be measured in one go.
            run: list[str] = []
            while index < len(lines) and not _FENCE.match(lines[index]):
                run.append(lines[index])
                index += 1
            out.extend(line + "\n" for line in _render_blocks(run, self.style, self.width))
        if closed and self._in_fence and self._fence_buffer:
            # The fence never closed: show what it held rather than swallowing it.
            self._in_fence = False
            out.append(self._flush_fence())
        self._decided = self._decided[len(lines) :]
        return "".join(out)


# ── diffs ────────────────────────────────────────────────────────────────────────────────

_DIFF_ROLES = {
    "-": "diff_del",
    "+": "diff_add",
    "@": "diff_hunk",
    " ": "diff_context",
}


def render_diff(diff: str, *, style: MarkdownStyle | None = None, max_lines: int | None = None) -> str:
    """Render a unified diff with one colour per line kind, capped at ``max_lines``.

    ``patch`` and ``write_file`` return a diff; showing it in the tool's own colour makes a
    change readable at a glance. When the diff is longer than ``max_lines`` the tail is dropped
    and a line says how much was left out, so a huge write never floods the transcript.
    """
    style = style or MarkdownStyle.none()
    if not diff.strip():
        return ""
    lines = diff.rstrip("\n").split("\n")
    body: list[str] = []
    from_file = ""
    for raw in lines:
        if raw.startswith("--- "):
            from_file = raw[4:].strip()
            continue
        if raw.startswith("+++ "):
            to_file = raw[4:].strip()
            header = f"{from_file or 'a/?'} → {to_file or 'b/?'}"
            body.append(style.paint("diff_file", header))
            continue
        role = _DIFF_ROLES.get(raw[:1])
        body.append(style.paint(role, raw) if role else raw)

    omitted = 0
    if max_lines is not None and len(body) > max_lines:
        omitted = len(body) - max_lines
        body = body[:max_lines]
    if omitted:
        body.append(style.paint("diff_hunk", f"… omitted {omitted} diff line(s)"))
    return "\n".join(body) + "\n"
