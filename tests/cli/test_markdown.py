"""Markdown and diff rendering, as pure functions.

The renderer is a function from text to text: it never reads a stream, never writes one, and
never decides for itself whether a terminal wants colour. That is what makes the streaming
behaviour testable — feed the same answer in one piece or in random fragments and the result
must be the same string.
"""

from __future__ import annotations

import json
import os
import random

from clite.cli.markdown import MarkdownStream, MarkdownStyle, render_diff, render_markdown

# A style that spells actual ANSI codes, so a test can tell coloured output from plain and can
# assert which role painted which part. The renderer itself never names a code.
COLOR = MarkdownStyle.from_codes(
    {
        "heading": "1",
        "code": "36",
        "fence": "2",
        "marker": "33",
        "quote": "36",
        "rule": "2",
        "link": "34",
        "diff_file": "1",
        "diff_hunk": "36",
        "diff_add": "32",
        "diff_del": "31",
        "diff_context": "2",
    }
)
PLAIN = MarkdownStyle.none()

WIDTH = 80


def render(text: str, style: MarkdownStyle = PLAIN, width: int = WIDTH) -> str:
    return render_markdown(text, style=style, width=width)


def stream(text: str, chunks: list[int], style: MarkdownStyle = PLAIN, width: int = WIDTH) -> str:
    """Feed ``text`` through a fresh stream in pieces of the given sizes."""
    out = MarkdownStream(style=style, width=width)
    parts: list[str] = []
    index = 0
    for size in chunks:
        parts.append(out.feed(text[index : index + size]))
        index += size
    if index < len(text):
        parts.append(out.feed(text[index:]))
    parts.append(out.close())
    return "".join(parts)


# ── staging: fragments are the same as the whole ─────────────────────────────────────────


def test_a_stream_in_random_fragments_matches_the_whole_text():
    text = (
        "# Title\n\n"
        "Some **bold** prose and a `snippet`.\n\n"
        "- one\n- two\n\n"
        "```python\nprint('hello')\n```\n\n"
        "A closing paragraph.\n"
    )
    rng = random.Random(20261006)
    for _ in range(50):
        chunks = [rng.randint(1, 7) for _ in range(len(text))]
        assert stream(text, chunks) == render(text)


def test_an_unfinished_line_is_held_until_the_newline_arrives():
    out = MarkdownStream(style=PLAIN, width=WIDTH)
    assert out.feed("one sho") == ""  # no newline yet: nothing to render
    assert out.feed("rt line\n") == "one short line\n"  # the line is complete now
    assert out.close() == ""


def test_the_held_line_is_flushed_by_close():
    out = MarkdownStream(style=PLAIN, width=WIDTH)
    assert out.feed("no newline here") == ""
    assert out.close() == "no newline here"


def test_a_line_split_mid_word_renders_identically():
    whole = render("# Heading\nplain line\n")
    assert stream("# Heading\nplain line\n", [9, 4, 1, 3, 50]) == whole


def test_an_empty_style_is_plain():
    assert MarkdownStyle.none().is_plain() is True
    assert MarkdownStyle.from_codes({}).is_plain() is True
    assert MarkdownStyle.from_codes({"heading": "1"}).is_plain() is False
    # Codes that are empty strings are dropped, so the style stays plain.
    assert MarkdownStyle.from_codes({"heading": ""}).is_plain() is True


def test_the_live_view_shows_an_unfinished_line_while_it_is_typed():
    out = MarkdownStream(style=PLAIN, width=WIDTH)
    seen = ""
    for fragment in ["slee", "ping ", "z z", "z\n"]:
        out.feed(fragment)
        view = out.view()
        assert view.startswith(seen)  # nothing already shown is taken back
        seen = view
    assert out.view() == "sleeping z zz\n"  # and nothing is shown twice


def test_the_live_view_waits_at_the_first_markdown_character():
    out = MarkdownStream(style=PLAIN, width=WIDTH)
    out.feed("a plain word, then **bold half")
    # Up to the first ``*`` is what the finished line will render to; past it may change.
    assert out.view() == "a plain word, then "
    out.feed(" done**\n")
    assert out.view() == "a plain word, then bold half done\n"


# ── code blocks are never rendered as Markdown ───────────────────────────────────────────


def test_a_code_block_is_kept_verbatim_and_not_rendered_as_markdown():
    text = "```\n# not a heading\n**not bold**\n- not a list\n```\n"
    assert render(text) == "# not a heading\n**not bold**\n- not a list\n"


def test_markup_inside_a_fence_keeps_its_marks_with_colour():
    text = "```\n# not a heading\n```\n"
    out = render(text, COLOR)
    assert "\x1b[36m" in out and "# not a heading" in out
    assert "# " not in out.replace("# not a heading", "")  # the heading marker is untouched
    assert "\x1b[1m" not in out  # the heading colour never leaked into the block


def test_an_unterminated_fence_is_held_until_it_closes_during_streaming():
    out = MarkdownStream(style=PLAIN, width=WIDTH)
    assert out.feed("antes\n```\n# inside\n") == "antes\n"  # the open fence is buffered
    assert out.feed("```\n") == "# inside\n"


def test_a_fence_that_never_closes_is_flushed_by_close():
    out = MarkdownStream(style=PLAIN, width=WIDTH)
    assert out.feed("```\ncode\n") == ""
    assert out.close() == "code\n"


# ── headings, lists, quotes, rules ───────────────────────────────────────────────────────


def test_headings_lists_and_quotes_lose_their_markers():
    assert render("# Title\n") == "Title\n"
    assert render("## Sub\n") == "Sub\n"
    assert render("- one\n- two\n") == "  • one\n  • two\n"
    assert render("1. first\n2. second\n") == "  1. first\n  2. second\n"
    assert render("> quoted\n") == "│ quoted\n"


def test_a_rule_becomes_a_line_of_dashes():
    assert render("---\n").strip() == "─" * 40


def test_inline_markup_is_unwrapped_and_coloured_by_role():
    plain = render("**bold** and `code` and [text](http://x)\n")
    assert plain == "bold and code and text\n"
    coloured = render("**bold** and `code`\n", COLOR)
    assert "\x1b[1mbold\x1b[0m" in coloured and "\x1b[36mcode\x1b[0m" in coloured


# ── tables ───────────────────────────────────────────────────────────────────────────────


def test_a_table_keeps_its_columns_and_drops_the_divider():
    table = "| Name | Age |\n| --- | --- |\n| Ada | 36 |\n| Bob | 7 |\n"
    assert render(table) == "Name  Age\nAda   36\nBob   7\n"


def test_a_table_wider_than_the_terminal_is_truncated_to_the_width():
    table = "| left column | right column |\n| --- | --- |\n| a long value here | another long value here |\n"
    lines = render(table, width=30).splitlines()
    assert lines and all(len(line) <= 30 for line in lines)
    assert any("…" in line for line in lines)  # a cut column shows it was cut
    assert lines[0].startswith("left column")  # the leftmost column survives the cut


def test_a_narrow_table_is_not_truncated():
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    assert render(table, width=30) == "a  b\n1  2\n"


# ── plain output without colour ──────────────────────────────────────────────────────────


def test_without_colour_the_output_is_plain_and_readable():
    text = "# Title\n\nSome **bold** text.\n\n```\ncode\n```\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    out = render(text)
    assert "\x1b" not in out
    assert out == ("Title\n\nSome bold text.\n\ncode\n\nA  B\n1  2\n")


def test_plain_and_coloured_output_carry_the_same_visible_text():
    text = "## Title\n- item with `code`\n"
    assert _strip(render(text, COLOR)) == render(text)


def _strip(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ── diff rendering ───────────────────────────────────────────────────────────────────────


DIFF = "--- a/file.txt\n+++ b/file.txt\n@@ -1,3 +1,3 @@\n context line\n-removed line\n+added line\n"


def test_a_unified_diff_is_coloured_by_line_role():
    out = render_diff(DIFF, style=COLOR)
    assert "\x1b[32m+added line\x1b[0m" in out
    assert "\x1b[31m-removed line\x1b[0m" in out
    assert "\x1b[36m@@ -1,3 +1,3 @@\x1b[0m" in out
    assert "a/file.txt → b/file.txt" in out


def test_a_diff_without_colour_is_plain_readable_text():
    out = render_diff(DIFF)
    assert "\x1b" not in out
    assert "-removed line" in out and "+added line" in out and " context line" in out


def test_a_long_diff_is_capped_and_says_how_much_was_left_out():
    body = "".join(f"+line {i}\n" for i in range(200))
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n" + body
    out = render_diff(diff, max_lines=20)
    assert out.count("\n") <= 22
    assert "omitted" in out and "line(s)" in out


def test_a_diff_of_nothing_is_empty():
    assert render_diff("") == ""
    assert render_diff("   \n") == ""


# ── the skin decides the colours ─────────────────────────────────────────────────────────


def _display(
    *,
    skin: str = "default",
    color: bool,
    no_color: bool = False,
    term: str = "xterm",
    diff: str = "",
    chunks: list[str] | None = None,
    reasoning: list[str] | None = None,
):
    import io

    from clite.cli.display import Display

    if no_color:
        os.environ["NO_COLOR"] = "1"
    else:
        os.environ.pop("NO_COLOR", None)
    os.environ["TERM"] = term
    stream = io.StringIO()
    # ``color`` is forced so the test never depends on whether pytest's stdout is a tty.
    shown = Display(skin=skin, stream=stream, color=color, tool_progress="all", width=WIDTH)
    for text in reasoning or []:
        shown.reasoning(text)
    for text in chunks if chunks is not None else ["## Heading\n"]:
        shown.delta(text)
    shown.end_stream()
    if diff:
        payload = json.dumps({"files": [{"path": "a.txt", "diff": diff}]})
        shown.tool_done("patch", {"path": "a.txt"}, payload, 0.1)
    return stream.getvalue()


def test_the_skin_supplies_the_markdown_colours():
    out = _display(skin="default", color=True)
    assert "\x1b[1m" in out  # heading role, from the skin's "bold"
    assert _strip(out).strip() == "Heading"


def test_a_monochrome_skin_renders_plain_text():
    out = _display(skin="mono", color=True)
    assert "\x1b" not in out
    assert out.strip() == "Heading"


def test_no_color_gives_plain_text_that_still_reads():
    out = _display(skin="default", color=False, no_color=True)
    assert "\x1b" not in out
    assert out.strip() == "Heading"


def test_a_dumb_terminal_gives_plain_text():
    out = _display(skin="default", color=False, term="dumb")
    assert "\x1b" not in out
    assert "Heading" in out


def test_redirected_output_has_no_escapes():
    # Writing to a non-tty stream makes Display choose plain text on its own.
    import io

    from clite.cli.display import Display

    os.environ.pop("NO_COLOR", None)
    os.environ["TERM"] = "xterm"
    stream = io.StringIO()
    shown = Display(skin="default", stream=stream, width=WIDTH)  # color=None -> auto
    assert shown.color is False
    shown.delta("# Title\n")
    shown.end_stream()
    assert "\x1b" not in stream.getvalue()


def test_a_streamed_answer_is_rendered_as_markdown_in_the_skin_colours():
    out = _display(skin="default", color=True, chunks=["# Title\n", "plain `code`\n"])
    assert "<h1>" not in out  # not HTML: we render to plain text
    assert _strip(out).strip() == "Title\nplain code"
    assert "\x1b[1m" in out  # the heading role, from the skin


def test_reasoning_is_shown_as_typed_and_never_read_as_markdown():
    out = _display(skin="default", color=False, reasoning=["**think", "ing** here"])
    assert "**thinking** here" in out  # marks kept, not unwrapped


def test_a_tool_diff_is_shown_in_the_skin_colours():
    out = _display(skin="default", color=True, diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
    assert "\x1b[32m+new\x1b[0m" in out
    assert "\x1b[31m-old\x1b[0m" in out


def test_a_tool_diff_without_colour_is_plain():
    out = _display(skin="mono", color=True, diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
    assert "\x1b" not in out
    assert "-old" in out and "+new" in out
