"""Reading a command the way a shell would, for the approval gate's detectors.

A shell ignores much of how a command is spelled: quotes, backslashes, line continuations,
``${NAME}`` for ``$NAME``, ``$IFS`` for a space, repeated slashes. So every detector reads a
command twice, as written and as ``shell_plain`` returns it, once ``normalize_command`` has
undone the cheap obfuscations (ANSI escapes, NUL bytes, full-width look-alikes). The same
reading tells the quoted runs that are only data (``git commit -m "rm -rf /"``) from those that
are code an executor runs (``bash -c "..."``, ``python -c "..."``, ``os.system("...")``); a code
payload is read again as a command of its own. A variable assigned on the same line
(``d=/; rm -rf $d``) is read as the value it holds.

A command too long or too deeply nested to read raises ``CommandTooComplexError``. That is
exactly where a pattern match would go quiet, so the gate refuses it instead of reading less.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def normalize_command(command: str) -> str:
    """Undo the cheap obfuscations: ANSI escapes, NUL bytes, full-width look-alikes."""
    text = _ANSI.sub("", command).replace("\x00", "")
    return unicodedata.normalize("NFKC", text)


_LINE_CONTINUATION = re.compile(r"\\\r?\n")
_IFS = re.compile(r"\$\{IFS\b[^}]*\}|\$IFS\b")
_BRACED_VARIABLE = re.compile(r"\$\{(\w+)\}")
QUOTES = str.maketrans("", "", "\"'")
_COMMAND_BREAK = re.compile(r"&&|\|\||[;&|(){}\n`]|\$\(")
# The same, without the parentheses and backticks: a delete only counts when its ``rm`` is the
# head of a whole command, not a word inside a call such as ``print(rm -rf /)``.
_COMMAND_BREAK_NO_PARENS = re.compile(r"&&|\|\||[;&|\n]")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
_SEPARATOR = frozenset(";&|\n")
# Words that run the command named after them.
_WRAPPERS = frozenset(
    {
        "sudo",
        "doas",
        "env",
        "exec",
        "nohup",
        "setsid",
        "time",
        "command",
        "builtin",
        "nice",
        "timeout",
        "stdbuf",
        "xargs",
        "uv",
        "uvx",
        "pipx",
        "poetry",
    }
)

# Commands whose whole point is to run the text handed to them: their ``-c``/``-e`` argument
# is code, and a shell (or interpreter) inside it runs whatever that text says.
_CODE_COMMANDS = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "ash",
        "eval",
        "source",
        "python",
        "python2",
        "python3",
        "pypy",
        "py",
        "node",
        "nodejs",
        "perl",
        "ruby",
        "php",
        "lua",
        "deno",
        "bun",
        "osascript",
    }
)
# Options that introduce a code payload for any command (``psql -c``, ``redis-cli -e``, ...).
_CODE_OPTIONS = frozenset({"-c", "-e", "--command", "--eval", "--execute"})

# Anything past these is refused rather than parsed: a command too big or too deeply nested to
# read is exactly where a pattern match would go quiet, so it fails closed instead.
MAX_COMMAND_CHARS = 20000
MAX_COMMAND_DEPTH = 12


class CommandTooComplexError(Exception):
    """A command that is too long or too deeply nested to read safely."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _nesting_depth(command: str) -> int:
    """The deepest run of command substitutions and subshells in ``command``."""
    depth = deepest = 0
    index, length = 0, len(command)
    while index < length:
        pair = command[index : index + 2]
        if pair == "$(" or command[index] == "`":
            depth += 1
            deepest = max(deepest, depth)
            index += 2 if pair == "$(" else 1
            continue
        if command[index] == ")":
            depth = max(0, depth - 1)
        index += 1
    return deepest


def guard_parse_limits(command: str, depth: int = 0) -> None:
    """Refuse a command past the size or nesting we are willing to read (fail closed).

    A command too big or too deeply nested to read is exactly where a pattern match would go
    quiet, so it is refused with the reason spelled out rather than waved through."""
    if len(command) > MAX_COMMAND_CHARS:
        raise CommandTooComplexError(f"the command is longer than the {MAX_COMMAND_CHARS}-character limit")
    nesting = _nesting_depth(command)
    if depth + nesting > MAX_COMMAND_DEPTH:
        raise CommandTooComplexError(f"the command nests commands more than {MAX_COMMAND_DEPTH} levels deep")


def _shell_read(command: str) -> tuple[str, list[tuple[int, int, int]]]:
    """``command`` as a shell reads its spelling, plus where each quoted run came from.

    Returns the text without quotes, escapes and other spellings a shell ignores (the same
    string :func:`shell_plain` returns), and for every quoted run the ``(start, end,
    segment_start)`` it occupies in that text. ``start``/``end`` are the bare contents; the
    segment start is where the simple command that owns the run begins, which is what decides
    whether the run is data or code."""
    text = _LINE_CONTINUATION.sub("", normalize_command(command))
    out: list[str] = []
    quoted: list[bool] = []
    segment: list[int] = []
    seg = 0
    index, length = 0, len(text)
    while index < length:
        character = text[index]
        if character == "\\" and index + 1 < length:
            out.append(text[index + 1])
            quoted.append(False)
            segment.append(seg)
            index += 2
            continue
        if character in ("'", '"'):
            quote = character
            index += 1
            while index < length and text[index] != quote:
                if quote == '"' and text[index] == "\\" and index + 1 < length:
                    out.append(text[index + 1])
                    index += 2
                else:
                    out.append(text[index])
                    index += 1
                quoted.append(True)
                segment.append(seg)
            index += 1
            continue
        if character in _SEPARATOR:
            out.append(character)
            quoted.append(False)
            segment.append(seg)
            seg += 1
            index += 1
            continue
        out.append(character)
        quoted.append(False)
        segment.append(seg)
        index += 1
    return _rebase("".join(out), quoted, segment)


def _rebase(plain: str, quoted: list[bool], segment: list[int]) -> tuple[str, list[tuple[int, int, int]]]:
    """``${NAME}`` to ``$NAME``, ``$IFS`` to a space, ``//`` to ``/`` while keeping quote spans."""
    out: list[str] = []
    flags: list[bool] = []
    owners: list[int] = []
    index, length = 0, len(plain)
    while index < length:
        ifs = _IFS.match(plain, index)
        if ifs:
            out.append(" ")
            flags.append(quoted[index])
            owners.append(segment[index])
            index = ifs.end()
            continue
        braced = _BRACED_VARIABLE.match(plain, index)
        if braced:
            for offset, replacement in enumerate("$" + braced.group(1)):
                out.append(replacement)
                flags.append(quoted[index + offset])
                owners.append(segment[index + offset])
            index = braced.end()
            continue
        if plain.startswith("//", index) and (index == 0 or plain[index - 1] not in ":/"):
            out.append("/")
            flags.append(quoted[index])
            owners.append(segment[index])
            index += 2
            continue
        out.append(plain[index])
        flags.append(quoted[index])
        owners.append(segment[index])
        index += 1
    spans: list[tuple[int, int, int]] = []
    start: int | None = None
    for position, is_quoted in enumerate(flags):
        if is_quoted and start is None:
            start = position
        elif not is_quoted and start is not None:
            spans.append((start, position, owners[start]))
            start = None
    if start is not None:
        spans.append((start, len(flags), owners[start]))
    return "".join(out), spans


def _head_of(segment_text: str) -> str | None:
    """The command a segment runs, with its leading ``NAME=value`` words dropped."""
    words = segment_text.split()
    index = 0
    while index < len(words) and _ASSIGNMENT.match(words[index]):
        index += 1
    return posixpath.basename(words[index]).lower() if index < len(words) else None


def _owns_code(plain: str, span: tuple[int, int, int]) -> bool:
    """Whether the quoted run at ``span`` is code an executor will run, not data."""
    start, _end, segment_start = span
    head = _head_of(plain[segment_start:start])
    if head is None:
        return False
    if head in _CODE_COMMANDS:
        return True
    # The word right before the run decides: ``psql -c '...'`` runs its argument as code too.
    preceding = plain[segment_start:start].split()
    return bool(preceding) and preceding[-1] in _CODE_OPTIONS


def _quoted_spans(plain: str, spans: list[tuple[int, int, int]]) -> list[tuple[int, int]]:
    """Every quoted run of ``plain``. Patterns never see inside one: a mention is data, and a
    code payload (``bash -c "..."``) is handed back separately and read as its own command."""
    return [(start, end) for start, end, _segment in spans]


def _written_quoted_spans(text: str) -> list[tuple[int, int]]:
    """The quoted runs of the command as written, with the quotes themselves included."""
    spans: list[tuple[int, int]] = []
    index, length = 0, len(text)
    while index < length:
        character = text[index]
        if character == "\\" and index + 1 < length:
            index += 2
            continue
        if character in ("'", '"'):
            quote, start = character, index
            index += 1
            while index < length and text[index] != quote:
                if quote == '"' and text[index] == "\\" and index + 1 < length:
                    index += 2
                else:
                    index += 1
            index += 1
            spans.append((start, index))
            continue
        index += 1
    return spans


def contained(span: tuple[int, int], text: str, data_spans: list[tuple[int, int]]) -> bool:
    """Whether a match lies wholly inside one quoted data run, and so is only a mention.

    Whitespace at the edges of the match is not part of the mention: ``rm -rf / `` matched
    inside ``echo "rm -rf /"`` reaches one space past the closing quote."""
    body = text[span[0] : span[1]]
    start = span[0] + (len(body) - len(body.lstrip()))
    end = span[1] - (len(body) - len(body.rstrip()))
    return any(start >= low and end <= high for low, high in data_spans)


_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;&|\n]")
_VARIABLE_USE = re.compile(r"\$\{(\w+)\}|\$(\w+)")


def variable_values(plain: str) -> dict[str, str]:
    """``NAME=value`` assignments on the line, in order, so a later mention can be resolved."""
    values: dict[str, str] = {}
    for segment in _SEGMENT_SPLIT.split(plain):
        segment = segment.strip()
        match = re.match(r"^([A-Za-z_]\w*)=(.*)$", segment, re.DOTALL)
        if match and " " not in segment.split("=", 1)[0]:
            values[match.group(1)] = match.group(2)
    return values


def expand_variables(text: str, values: dict[str, str]) -> str:
    """``$NAME`` and ``${NAME}`` replaced by the value assigned to them on the same line."""
    if not values:
        return text
    return _VARIABLE_USE.sub(lambda match: values.get(match.group(1) or match.group(2), match.group(0)), text)


_SHELL_CALL = re.compile(
    r"\b(?:os\.(?:system|popen)|subprocess\.(?:run|call|check_call|check_output|Popen)|commands\.getoutput)\s*\(\s*[\"']([^\"']+)[\"']"
)


def code_payloads(command: str) -> list[str]:
    """The text handed to a code executor: the argument of ``sh -c``, an interpreter, or an
    ``os.system``/``subprocess`` call, all of which run whatever the text says."""
    plain, spans = _shell_read(command)
    payloads = [
        plain[start:end] for span in spans if _owns_code(plain, span) for start, end in [(span[0], span[1])]
    ]
    payloads.extend(match.group(1) for match in _SHELL_CALL.finditer(normalize_command(command)))
    return payloads


def shell_plain(command: str) -> str:
    """``command`` without the spellings a shell ignores: line continuations, backslash
    escapes, quotes, ``${NAME}`` for ``$NAME``, ``$IFS`` for a space, repeated slashes.

    Every detector reads this form as well as the original, so ``rm -rf "$HOME"`` and
    ``r\\\\m -rf ~`` are judged like the plain command they run as.
    """
    return _shell_read(command)[0]


def readings(command: str) -> list[str]:
    """The texts every detector looks at: the command as written, and as a shell reads it."""
    written, plain = normalize_command(command), shell_plain(command)
    return [written] if plain == written else [written, plain]


def position_readings(command: str) -> list[tuple[str, list[tuple[int, int]], dict[str, str]]]:
    """Each reading with the quoted runs that patterns must not see inside, and the line's
    variable assignments.

    A match wholly inside a quoted run is only a mention (``git commit -m "rm -rf /"``). The
    runs that carry code (``bash -c "..."``, ``python -c "..."``) are not matched here either;
    they are handed back separately and read as commands in their own right."""
    written, plain = normalize_command(command), shell_plain(command)
    pairs = [(written, _written_quoted_spans(written))]
    if plain != written:
        pairs.append((plain, _quoted_spans(plain, _shell_read(command)[1])))
    values = variable_values(plain)
    return [(text, spans, values) for text, spans in pairs]


def simple_commands(text: str, *, break_on_parens: bool = True) -> list[list[str]]:
    """The words of each simple command in ``text``, leading ``NAME=value`` words dropped.

    With ``break_on_parens`` false, ``(``/``)``/backticks do not start a new command. The
    delete detector uses that: ``print(rm -rf /)`` is a call whose head is ``print``, not a
    subshell running ``rm``."""
    splitter = _COMMAND_BREAK if break_on_parens else _COMMAND_BREAK_NO_PARENS
    commands = []
    for segment in splitter.split(text):
        words = segment.split()
        while words and _ASSIGNMENT.match(words[0]):
            words.pop(0)
        if words:
            commands.append(words)
    return commands


def arguments_of(words: list[str], names: frozenset[str]) -> list[str] | None:
    """The words after the command when ``words`` runs one of ``names``, directly, by path, or
    through a wrapper such as ``sudo``; ``None`` when it runs something else."""
    first = posixpath.basename(words[0]).lower()
    if first in names:
        return words[1:]
    if first in _WRAPPERS:
        for index, word in enumerate(words[1:], 1):
            if posixpath.basename(word).lower() in names:
                return words[index + 1 :]
    return None
