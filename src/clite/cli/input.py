"""Line input for the classic REPL: multi-line, bracketed paste, completion.

The REPL must run wherever Python runs, so the standard library reader (``input`` plus
``readline``) is the fallback that is always present and always tested. When
``prompt_toolkit`` is installed (``pip install "clite[cli]"``) :func:`make_reader` returns a
richer reader instead: the same multi-line and paste behaviour, plus a live completion menu
and a status bar that is redrawn while a turn streams, so streaming output never garbles the
line the user is typing.

The pure helpers here (:func:`continuation_text`, :func:`split_paste`) are unit tested
without a terminal; the readers are thin wrappers around them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Bracketed paste: the terminal wraps pasted text in these markers when it is asked to
# (``\x1b[?2004h``). With them, a paste is one input, not a run of Enter presses.
PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"
CONTINUATION = "\\"  # a line ending in a backslash continues on the next line


def split_paste(text: str) -> tuple[str, str | None]:
    """Split a bracketed paste. Returns ``(before, pasted)``.

    ``pasted`` is ``None`` when ``text`` carries no paste markers (there is nothing to
    continue reading); otherwise it is the pasted body, with the opening marker removed. The
    closing marker may not have arrived yet, so the body can still need more lines; the reader
    keeps reading until it sees the marker or the stream ends.
    """
    if PASTE_START not in text:
        return text, None
    before, _, rest = text.partition(PASTE_START)
    return before, rest


def continuation_text(text: str) -> str:
    """The text without its continuation marker, or the same text when it does not continue.

    A line ending in an odd number of backslashes continues (``foo\\\\`` does not: the second
    backslash escapes the first). The whitespace before the marker goes too, so a wrapped
    message does not carry a dangling space into the next line.
    """
    stripped = text.rstrip()
    trailing = len(stripped) - len(stripped.rstrip(CONTINUATION))
    if trailing % 2 == 1:
        return stripped[:-1].rstrip() + text[len(stripped) :]
    return text


def needs_continuation(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and (len(stripped) - len(stripped.rstrip(CONTINUATION))) % 2 == 1


def join_lines(lines: list[str]) -> str:
    """A multi-line message: the continuation markers are gone, the newlines stay."""
    return "\n".join(lines)


def read_message(
    read_line: Callable[[str], str | None], prompt: str, *, continuation_prompt: str = "… "
) -> str | None:
    """Read one message, following ``\\`` continuations and bracket pastes.

    ``read_line`` returns one line or ``None`` at end of input. This is the shared loop the
    standard-library reader and (for continuations) the prompt_toolkit paths both use, so
    their behaviour matches: the returned text is the whole message with real newlines.
    """
    first = read_line(prompt)
    if first is None:
        return None
    before, pasted = split_paste(first)
    if pasted is not None:
        # A paste can span several lines; keep reading until the closing marker arrives.
        while not pasted.endswith(PASTE_END):
            more = read_line("")
            if more is None:
                break
            pasted += "\n" + more
        pasted = pasted.removesuffix(PASTE_END)
        lines = ([*before.split("\n")] if before else []) + pasted.split("\n")
    else:
        lines = [before]
    while needs_continuation(lines[-1]):
        more = read_line(continuation_prompt)
        if more is None:
            break
        lines[-1] = continuation_text(lines[-1])
        lines.extend(more.split("\n"))
    return join_lines(lines)


class StdlibReader:
    """The fallback reader: ``input`` (with ``readline`` when the platform has it).

    It reaches the user through ``input_fn`` so tests can script input, and it is what runs
    when ``prompt_toolkit`` is not installed.
    """

    def __init__(self, input_fn: Callable[[str], str]) -> None:
        self.input_fn = input_fn

    def read_message(self, prompt: str) -> str | None:
        return read_message(self._one_line, prompt)

    def _one_line(self, prompt: str) -> str | None:
        try:
            return self.input_fn(prompt)
        except EOFError:
            return None


class PromptToolkitReader:
    """The rich reader: ``prompt_toolkit`` in multiline mode.

    Alt+Enter (or ``Esc`` then ``Enter``) starts a new line; Enter sends. Bracketed paste
    arrives as one message. The reader owns the prompt line, and the REPL wraps streaming
    output in :meth:`streaming` (``patch_stdout``) so a running turn prints above the line
    instead of over it.
    """

    def __init__(
        self, *, completer: Completer | None = None, history_path: Any = None, style: Any = None
    ) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings

        keys = KeyBindings()

        @keys.add("escape", "enter")  # Alt+Enter: newline, keep editing
        def _newline(event: Any) -> None:
            event.current_buffer.insert_text("\n")

        history = FileHistory(str(history_path)) if history_path else None
        self.session: Any = PromptSession(
            multiline=True,
            key_bindings=keys,
            history=history,
            auto_suggest=AutoSuggestFromHistory(),
            completer=_pt_completer(completer) if completer else None,
            complete_while_typing=False,
            style=style,
        )

    def read_message(self, prompt: str) -> str | None:
        try:
            text = self.session.prompt(prompt)
        except EOFError:
            return None
        # prompt_toolkit gives the whole buffer; only a trailing backslash still continues.
        lines = text.split("\n")
        while len(lines) and needs_continuation(lines[-1]):
            lines[-1] = continuation_text(lines[-1])
            try:
                more = self.session.prompt("… ")
            except EOFError:
                break
            lines.extend(more.split("\n"))
        return "\n".join(lines)

    def streaming(self) -> Any:
        """A context manager: writes inside it go above the prompt, not through it."""
        from prompt_toolkit.patch_stdout import patch_stdout

        return patch_stdout()


def _pt_completer(source: Completer) -> Any:
    from prompt_toolkit.completion import Completer as PtCompleter
    from prompt_toolkit.completion import Completion
    from prompt_toolkit.document import Document

    class _Completer(PtCompleter):
        def get_completions(self, document: Document, complete_event: Any) -> Any:
            text = document.text_before_cursor
            word = document.get_word_before_cursor(WORD=False)
            for suggestion in source.suggest(text):
                yield Completion(suggestion.text, start_position=-len(word), display=suggestion.display())

    return _Completer()


def prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


def make_reader(
    *,
    input_fn: Callable[[str], str] | None = None,
    completer: Completer | None = None,
    history_path: Any = None,
    style: Any = None,
) -> StdlibReader | PromptToolkitReader:
    """The reader for this run: the injected ``input_fn``, prompt_toolkit, or the fallback.

    Tests and embedded callers pass ``input_fn``; it always wins so behaviour is scriptable.
    A real terminal gets prompt_toolkit when it is installed and the standard library reader
    otherwise.
    """
    if input_fn is not None:
        return StdlibReader(input_fn)
    if prompt_toolkit_available():
        try:
            return PromptToolkitReader(completer=completer, history_path=history_path, style=style)
        except Exception:  # noqa: BLE001 - a broken terminal must still leave a usable REPL
            import logging

            logging.getLogger("clite.cli.input").warning(
                "prompt_toolkit unavailable; using the classic reader", exc_info=True
            )
    return StdlibReader(input)


# ── completion ───────────────────────────────────────────────────────────────────────────


@dataclass
class Suggestion:
    text: str
    kind: str  # "command" | "model" | "skill" | "session" | "subcommand"

    def display(self) -> str:
        return f"{self.text}  ({self.kind})"


@dataclass
class Completer:
    """Values a tab press can offer, gathered offline from the sources already on disk.

    Slash commands and their argument values (models, skills, session ids) come from the
    same catalogs the rest of the CLI reads; nothing here fetches from the network.
    """

    commands: list[Suggestion] = field(default_factory=list)
    models: list[Suggestion] = field(default_factory=list)
    skills: list[Suggestion] = field(default_factory=list)
    sessions: list[Suggestion] = field(default_factory=list)

    def suggest(self, buffer: str) -> list[Suggestion]:
        """Suggestions for what the user has typed so far.

        ``/mod`` completes commands; ``/model mock`` completes model names;
        ``/resume <prefix>`` completes sessions; ``/skills <prefix>`` completes skills.
        """
        stripped = buffer.lstrip()
        if not stripped.startswith("/"):
            return []
        if " " not in stripped:
            prefix = stripped.lower()
            return [s for s in self.commands if s.text.lower().startswith(prefix)]
        name, _, args = stripped[1:].partition(" ")
        pool = self._pool_for(name.lower())
        return [s for s in pool if s.text.lower().startswith(args.strip().lower())]

    def _pool_for(self, command: str) -> list[Suggestion]:
        if command in ("model", "models"):
            return self.models
        if command in ("skills", "skill"):
            return self.skills
        if command in ("resume", "sessions"):
            return self.sessions
        return []


def build_completer(*, surface: str = "cli", cwd: str | None = None) -> Completer:
    """The completer for a surface, filled from the catalogs already on disk.

    Slash commands (and one entry per skill) come from :func:`clite.runtime.commands.command_catalog`;
    model names come from the providers' own lists and the configured default; session ids come
    from the session database. Nothing here touches the network, so a Tab press stays instant.
    """
    from clite.core.config import get_path, load_config
    from clite.runtime.commands import command_catalog

    config = load_config()
    commands = [
        Suggestion("/" + entry["name"], "skill" if entry.get("kind") == "skill" else "command")
        for entry in command_catalog(surface, cwd=cwd)
    ]
    skills = [
        Suggestion(entry["name"], "skill")
        for entry in command_catalog(surface, cwd=cwd)
        if entry.get("kind") == "skill"
    ]

    models: dict[str, Suggestion] = {}
    default_model = str(get_path(config, "model.default", "") or "")
    if default_model:
        models[default_model] = Suggestion(default_model, "model")
    try:
        from clite.providers.registry import list_providers

        for profile in list_providers(config):
            for name in (*profile.fallback_models, profile.default_model):
                if name:
                    models.setdefault(name, Suggestion(name, "model"))
    except Exception:  # noqa: BLE001 - completion is a convenience; never fail the REPL for it
        pass

    sessions: list[Suggestion] = []
    try:
        from clite.state.db import get_session_db

        for row in get_session_db().list_sessions(limit=50):
            sessions.append(Suggestion(str(row["id"]), "session"))
    except Exception:  # noqa: BLE001
        pass

    return Completer(
        commands=commands,
        models=sorted(models.values(), key=lambda s: s.text),
        skills=skills,
        sessions=sessions,
    )
