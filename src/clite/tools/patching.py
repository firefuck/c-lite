"""Tolerant patch matching and V4A multi-file patch application.

Two capabilities that make the ``patch`` tool less brittle and able to edit several
files in one call:

* **Tolerance chain** — when ``old_string`` is not found verbatim, a ladder of
  progressively looser normalisations is tried. Each rung only accepts the match
  when it is unique in the file, so a fuzzy match is never ambiguous. The rung that
  succeeded is reported back to the model.

* **V4A multi-file patches** — a single text block in the V4A format
  (``*** Update File``, ``*** Add File``, ``*** Delete File``) that touches several
  files. It is parsed, every path is checked against ``write_denied_reason`` first,
  and the whole batch is applied — or, on any failure after writes begin, rolled back
  to the snapshot taken before the first write.

Paths still go through ``write_denied_reason`` and diffs are still redacted; the
multi-file mode adds atomicity, not a new route past the guards.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from clite.core.io import atomic_write_text
from clite.tools.file_safety import write_denied_reason

# Smart quotes and look-alikes that models copy from rendered prose. Normalising to
# their ASCII equivalents lets a match succeed when the file is clean but the model
# handed in typographic punctuation (or vice versa). Keys are ordinals so the dict works
# both as a ``str.translate`` table and as a per-character lookup.
_SMART_QUOTES = {
    ord("\u2018"): "'",
    ord("\u2019"): "'",  # left/right single quotes
    ord("\u201c"): '"',
    ord("\u201d"): '"',  # left/right double quotes
    ord("\u201a"): "'",
    ord("\u201e"): '"',  # low single/double quotes
    ord("\u2032"): "'",
    ord("\u2033"): '"',  # prime / double prime
    ord("\u00ab"): '"',
    ord("\u00bb"): '"',  # guillemets
    ord("\u2013"): "-",
    ord("\u2014"): "-",  # en/em dash
    ord("\u00a0"): " ",  # non-breaking space
}


@dataclass
class MatchResult:
    """Outcome of a tolerant search for ``old`` inside ``content``."""

    found: bool
    span: tuple[int, int] | None = None
    level: str = ""  # which rung matched: "exact" / "trailing_ws" / "indent" / "smart_quotes" / "blank_lines"
    matches: int = 0  # how many candidates the matched rung saw (0 when nothing matched at all)


# ── normalisation rungs ─────────────────────────────────────────────────────────────────
# Each rung is (level, normalise). The normalise function is applied to *both* the needle
# and the haystack; an exact substring match on the two normalised forms is then a
# candidate. To recover the span in the *original* content, we record, for each character
# of the normalised haystack, the offset it came from. Rungs are ordered least-relaxing
# first; the first rung that yields exactly one candidate wins, and a rung that yields two
# or more stops the chain (ambiguous → reject).


def _smart_quote_normalize(text: str) -> str:
    return text.translate(_SMART_QUOTES)


def _blank_line_normalize(text: str) -> str:
    """Collapse runs of blank lines to a single blank line, so a missing or extra empty
    line between two blocks no longer defeats the match."""
    import re

    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)


def _rstrip_lines(text: str) -> str:
    """Strip trailing whitespace from each line; leading indentation is preserved."""
    return "\n".join(line.rstrip() for line in text.splitlines())


def _strip_lines(text: str) -> str:
    """Strip leading and trailing whitespace from each line."""
    return "\n".join(line.strip() for line in text.splitlines())


_RUNGS: list[tuple[str, Callable[[str], str]]] = [
    ("trailing_ws", _rstrip_lines),
    ("indent", _strip_lines),
    ("smart_quotes", _smart_quote_normalize),
    ("blank_lines", _blank_line_normalize),
]


def _normalise_with_origin(text: str, fn: Callable[[str], str]) -> tuple[str, list[int]]:
    """Apply ``fn`` to ``text`` and return the result plus the origin map: for each
    character position in the result, the index in ``text`` it came from.

    The normalisations either *drop* characters (stripping, blank-line collapse) or
    *replace* one character with another (smart quotes). We align the result to the
    input by walking both in lock-step: for each character the function *keeps*, we
    record where it came from; for each character it *drops*, we skip it; for a
    *replacement* (smart quote → ASCII), the replacement carries the original's origin.

    Alignment is done per surviving character by scanning ``text`` forward from the
    last consumed position until we find the character the normalisation kept. This is
    O(n) because every character of ``text`` is visited at most once.
    """
    normalised = fn(text)
    if not normalised:
        return "", []
    result_chars: list[str] = []
    origin: list[int] = []
    ti = 0  # next unread index into text
    n = len(text)
    for ch in normalised:
        # Advance ti past any characters that fn dropped (they don't appear in the
        # normalised output at this position). For a replacement (smart quote), the
        # original character is different from ``ch`` but still maps here.
        while ti < n:
            original = text[ti]
            if original == ch:
                # kept verbatim
                result_chars.append(ch)
                origin.append(ti)
                ti += 1
                break
            if (
                fn is _smart_quote_normalize
                and ord(original) in _SMART_QUOTES
                and _SMART_QUOTES[ord(original)] == ch
            ):
                # replaced: the replacement char ``ch`` matches what the table says
                result_chars.append(ch)
                origin.append(ti)
                ti += 1
                break
            # otherwise this original char was dropped by fn; skip it
            ti += 1
        else:
            # ran out of text without aligning — should not happen for our rungs
            break
    return "".join(result_chars), origin


# ── tolerant search ─────────────────────────────────────────────────────────────────────


def find_tolerant_match(content: str, old: str) -> MatchResult:
    """Find a unique place in ``content`` that matches ``old``.

    The exact match is checked first. When it is absent, each normalisation rung is
    applied *to both the needle and the haystack* and an exact substring match is retried
    on the normalised forms. A rung is accepted only when it produces exactly one
    candidate; two or more means the match is ambiguous and the chain stops there.

    The returned ``span`` is always in the *original* ``content`` coordinates, so the
    caller can apply the replacement without re-running the normalisation.
    """
    count = content.count(old)
    if count == 1:
        start = content.index(old)
        return MatchResult(found=True, span=(start, start + len(old)), level="exact", matches=1)
    if count > 1:
        return MatchResult(found=False, level="exact", matches=count)

    needle_base = old.strip("\n")
    for level, fn in _RUNGS:
        norm_needle = fn(needle_base)
        if not norm_needle or not norm_needle.strip():
            continue
        norm_content, origin = _normalise_with_origin(content, fn)
        candidates: list[tuple[int, int]] = []
        search_from = 0
        while True:
            pos = norm_content.find(norm_needle, search_from)
            if pos < 0:
                break
            candidates.append((pos, pos + len(norm_needle)))
            search_from = pos + 1
        if len(candidates) == 1:
            start, end = candidates[0]
            orig_start = origin[start]
            orig_end = origin[end - 1] + 1 if end > 0 and end - 1 < len(origin) else orig_start
            # Expand to full lines: the replacement should cover whole original lines, so a
            # match that differs only in indentation replaces the block including its leading
            # whitespace, not just the non-blank characters.
            orig_start, orig_end = _expand_to_line_span(content, orig_start, orig_end)
            return MatchResult(found=True, span=(orig_start, orig_end), level=level, matches=1)
        if candidates:
            return MatchResult(found=False, level=level, matches=len(candidates))
    return MatchResult(found=False, matches=0)


def _expand_to_line_span(content: str, start: int, end: int) -> tuple[int, int]:
    """Grow ``[start, end)`` to the nearest enclosing line boundaries."""
    line_start = content.rfind("\n", 0, start)
    new_start = line_start + 1 if line_start >= 0 else 0
    line_end = content.find("\n", end)
    new_end = line_end + 1 if line_end >= 0 else len(content)
    return new_start, new_end


def apply_replacement(content: str, span: tuple[int, int], new: str) -> str:
    """Drop in ``new`` at ``span`` and keep the trailing-newline behaviour of the original."""
    matched = content[span[0] : span[1]]
    replacement = new if (new.endswith("\n") or not matched.endswith("\n")) else new + "\n"
    return content[: span[0]] + replacement + content[span[1] :]


# ── V4A multi-file patch ───────────────────────────────────────────────────────────────


@dataclass
class PatchHunk:
    """One file operation parsed from a V4A patch."""

    op: str  # "update" | "add" | "delete"
    path: str
    context: str  # the `@@ ... @@` context hint line, or ""
    removed: list[str]
    added: list[str]


@dataclass
class ParsedPatch:
    """A parsed V4A patch: a list of hunks and a parse error, if any."""

    hunks: list[PatchHunk]
    error: str | None = None


_V4A_HEADERS = {"update file", "add file", "delete file"}


def parse_v4a_patch(patch_text: str) -> ParsedPatch:
    """Parse V4A-format multi-file patch text into hunks.

    The format is line-oriented::

        *** Update File: path/to/file
        @@ context hint @@
         context line
        -removed line
        +added line
        *** Add File: path/to/new
        +content line
        *** Delete File: path/to/gone

    Blank lines between a header and the first hunk line are ignored. An ``Update`` hunk
    without added lines is a deletion; an ``Add`` hunk without removed lines is a creation.
    """
    lines = patch_text.splitlines()
    hunks: list[PatchHunk] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if not stripped.startswith("*** "):
            i += 1
            continue
        header_body = stripped[4:]
        if ":" in header_body:
            op_label, path = header_body.split(":", 1)
        else:
            parts = header_body.split(None, 1)
            if len(parts) != 2:
                return ParsedPatch(hunks, f"malformed file header: {line!r}")
            op_label, path = parts
        op = op_label.strip().lower()
        path = path.strip()
        if op not in _V4A_HEADERS:
            return ParsedPatch(hunks, f"unknown patch op {op_label!r}; expected Update/Add/Delete File")
        if not path:
            return ParsedPatch(hunks, f"file header missing a path: {line!r}")
        op_verb = op.split()[0]
        i += 1
        context = ""
        removed: list[str] = []
        added: list[str] = []
        # Optional @@ context hint @@
        if i < n and lines[i].lstrip().startswith("@@") and lines[i].rstrip().endswith("@@"):
            context = lines[i].strip()
            i += 1
        while i < n:
            body = lines[i]
            if body.startswith("*** "):
                break
            if body.startswith("-"):
                removed.append(body[1:])
            elif body.startswith("+"):
                added.append(body[1:])
            elif body.startswith(" "):
                # context line — belongs to neither side but anchors the hunk
                pass
            elif body.strip() == "":
                # blank line inside a hunk is treated as a context blank
                pass
            else:
                return ParsedPatch(hunks, f"unexpected line in hunk for {path}: {body!r}")
            i += 1
        hunks.append(PatchHunk(op=op_verb, path=path, context=context, removed=removed, added=added))
    if not hunks:
        return ParsedPatch([], "patch contains no file headers")
    return ParsedPatch(hunks)


# ── atomic application ─────────────────────────────────────────────────────────────────


@dataclass
class _AppliedFile:
    path: Path
    created: bool
    before: str | None  # None when the file did not exist
    diff: str


@dataclass
class MultiFileResult:
    applied: list[_AppliedFile]
    rolled_back: bool
    error: str | None = None
    denied_path: str | None = None


def _hunk_to_replacement(hunk: PatchHunk) -> tuple[str, str, bool]:
    """Return ``(old_string, new_string, replace_all)`` for a parsed hunk.

    ``Update`` hunks keep their removed/added lines as an old→new pair. ``Add`` hunks
    have no old side (the whole content is added). ``Delete`` hunks have no new side.
    """
    if hunk.op == "add":
        return ("", "\n".join(hunk.added) + "\n", False)
    if hunk.op == "delete":
        return ("\n".join(hunk.removed) + "\n", "", False)
    old = "\n".join(hunk.removed) + ("\n" if hunk.removed else "")
    new = "\n".join(hunk.added) + ("\n" if hunk.added else "")
    return (old, new, False)


def apply_v4a_patch(patch_text: str, resolve) -> MultiFileResult:
    """Apply a V4A multi-file patch atomically.

    ``resolve`` maps a path string (as written in the patch) to a ``Path``; the caller
    passes in the tool's environment-aware resolver so the same cwd rules apply.

    Every path is checked against ``write_denied_reason`` *before* any write happens, so
    a denied path aborts the whole batch cleanly. Once writes begin, a failure triggers a
    rollback: each touched file is restored to the snapshot taken just before its write
    (or removed, if it was created by this patch).
    """
    parsed = parse_v4a_patch(patch_text)
    if parsed.error:
        return MultiFileResult(applied=[], rolled_back=False, error=parsed.error)

    # 1. resolve + guard every path up front
    planned: list[tuple[PatchHunk, Path]] = []
    for hunk in parsed.hunks:
        path = resolve(hunk.path)
        denied = write_denied_reason(path)
        if denied:
            return MultiFileResult(applied=[], rolled_back=False, error=denied, denied_path=str(path))
        planned.append((hunk, path))

    applied: list[_AppliedFile] = []
    import difflib

    for hunk, path in planned:
        existed = path.is_file()
        before = path.read_text(encoding="utf-8") if existed else None

        if hunk.op == "add":
            new_content = "\n".join(hunk.added)
            if not new_content.endswith("\n") and new_content:
                new_content += "\n"
            try:
                atomic_write_text(path, new_content)
            except OSError as exc:
                _rollback(applied)
                return MultiFileResult(applied=[], rolled_back=True, error=f"could not write {path}: {exc}")
            diff = "".join(
                difflib.unified_diff(
                    [],
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{path.name}",
                    tofile=f"b/{path.name}",
                    n=2,
                )
            )
            applied.append(_AppliedFile(path=path, created=not existed, before=before, diff=diff))
            continue

        if hunk.op == "delete":
            if not existed:
                continue  # nothing to delete; treat as applied-no-op
            try:
                path.unlink()
            except OSError as exc:
                _rollback(applied)
                return MultiFileResult(applied=[], rolled_back=True, error=f"could not delete {path}: {exc}")
            diff = "".join(
                difflib.unified_diff(
                    (before or "").splitlines(keepends=True),
                    [],
                    fromfile=f"a/{path.name}",
                    tofile=f"b/{path.name}",
                    n=2,
                )
            )
            applied.append(_AppliedFile(path=path, created=False, before=before, diff=diff))
            continue

        # op == "update"
        if not existed:
            _rollback(applied)
            return MultiFileResult(applied=[], rolled_back=True, error=f"file not found: {path}")
        content = before or ""
        old, new, _ = _hunk_to_replacement(hunk)
        if not old:
            _rollback(applied)
            return MultiFileResult(
                applied=[],
                rolled_back=True,
                error=f"update hunk for {path} has no removed lines; use *** Add File to create content",
            )
        match = find_tolerant_match(content, old)
        if not match.found or match.span is None:
            reason = "not found" if match.matches == 0 else f"{match.matches} matches"
            _rollback(applied)
            return MultiFileResult(applied=[], rolled_back=True, error=f"old_string {reason} in {path}")
        updated = apply_replacement(content, match.span, new)
        try:
            atomic_write_text(path, updated)
        except OSError as exc:
            _rollback(applied)
            return MultiFileResult(applied=[], rolled_back=True, error=f"could not write {path}: {exc}")
        diff = "".join(
            difflib.unified_diff(
                content.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
                n=2,
            )
        )
        applied.append(_AppliedFile(path=path, created=False, before=before, diff=diff))

    return MultiFileResult(applied=applied, rolled_back=False)


def _rollback(applied: list[_AppliedFile]) -> None:
    """Undo every write in ``applied``, in reverse order."""
    for entry in reversed(applied):
        try:
            if entry.before is None:
                # the file was created by this patch: remove it
                if entry.path.exists():
                    entry.path.unlink()
            else:
                atomic_write_text(entry.path, entry.before)
        except OSError:
            # best-effort: we cannot do better than restore what we can
            pass
