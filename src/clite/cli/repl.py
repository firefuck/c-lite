"""The classic interactive CLI: a read-eval-print loop over a ``ChatSession``.

The loop reads on the main thread and runs the agent on a worker thread, so a line typed
while the agent works is not lost: it follows ``display.busy_input_mode`` (steer, interrupt,
queue or reject), exactly like the RPC server and the gateway. The queue, the worker and the
policy are the runtime's :class:`~clite.runtime.session.TurnQueue` — one implementation for all
three surfaces.

Input has two paths. ``prompt_toolkit`` (``pip install "clite[cli]"``) gives multi-line editing
(Alt+Enter or a trailing backslash), bracketed paste, history and a Tab completion menu, and
keeps streaming output from overwriting the line being typed. The standard library reader is
the fallback that always works — over SSH, in a container, with no extra installed — and it is
the path the tests exercise. See :mod:`clite.cli.input`.

Ctrl+C while the agent works interrupts the turn; a second Ctrl+C within two seconds exits.
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from typing import Any

from clite.agent import AgentCallbacks, TurnResult
from clite.cli.display import Display, load_skin
from clite.cli.input import Completer, build_completer, make_reader
from clite.core.config import get_path, load_config
from clite.core.constants import get_home
from clite.core.errors import CliteError
from clite.runtime.commands import BUSY_ALLOW, command_catalog, resolve_command, split_command
from clite.runtime.session import (
    ACTION_CLIPBOARD,
    ACTION_NEW,
    ACTION_QUIT,
    ACTION_SUBMIT,
    SUBMIT_QUEUED,
    SUBMIT_REJECTED,
    SUBMIT_STEERED,
    ChatSession,
    SlashResult,
    Turn,
    TurnQueue,
    busy_input_mode,
)

try:
    import readline
except ImportError:  # Windows without pyreadline
    readline = None  # type: ignore[assignment]

_APPROVAL_KEYS = {
    "o": "once",
    "once": "once",
    "s": "session",
    "session": "session",
    "a": "always",
    "always": "always",
    "d": "deny",
    "deny": "deny",
    "n": "deny",
    "": "deny",
}
FORCE_EXIT_WINDOW_SECONDS = 2.0


class Repl:
    def __init__(
        self,
        *,
        display: Display | None = None,
        input_fn=input,
        images: list[str] | None = None,
        **session_options: Any,
    ) -> None:
        config = load_config()
        self.display = display or Display(
            skin=str(get_path(config, "display.skin", "default")),
            tool_progress=str(get_path(config, "display.tool_progress", "all")),
        )
        self.input_fn = input_fn
        self.config = config
        self.show_reasoning = bool(get_path(config, "display.show_reasoning", False))
        self._prompting = False
        self._last_interrupt = 0.0
        self._streamed = False
        self._print_lock = threading.Lock()
        # Images attached with --image; they join the first message of the session.
        self._start_images = list(images or [])
        self.session = ChatSession(platform="cli", callbacks=self._callbacks(), **session_options)
        # The queue, the worker and the busy policy are shared with RPC and the gateway.
        self.turns = TurnQueue(
            self.session, self._run_turn, merge_bursts=False, thread_name="clite-repl-turn"
        )

    # ── callbacks ────────────────────────────────────────────────────────────────────────

    def _callbacks(self) -> AgentCallbacks:
        def on_delta(text: str) -> None:
            self._streamed = True
            with self._print_lock:
                self.display.delta(text)

        def on_message(message: dict[str, Any]) -> None:
            with self._print_lock:
                # Text that arrived without streaming (or before a tool call) still has to be shown.
                if not self._streamed and message.get("content"):
                    self.display.line(str(message["content"]))
                self.display.end_stream()
            self._streamed = False

        return AgentCallbacks(
            on_delta=on_delta,
            on_reasoning=(self.display.reasoning) if self.show_reasoning else None,
            on_message=on_message,
            on_tool_start=lambda call_id, name, args: self.display.tool_start(name, args),
            on_tool_complete=lambda call_id, name, args, result, seconds: self.display.tool_done(
                name, args, result, seconds
            ),
            on_status=self.display.status,
            on_subagent=self._show_subagent,
            approve=self._approve,
            clarify=self._clarify,
        )

    def _show_subagent(self, event: str, payload: dict[str, Any]) -> None:
        """One line of subagent progress: the tool, a preview of its arguments, the iteration."""
        detail = payload.get("tool") or payload.get("status") or ""
        if event == "tool":
            preview = payload.get("args") or ""
            detail = f"{detail}({preview})" if preview else detail
        iteration = payload.get("iteration") or 0
        where = f" [iter {iteration}]" if iteration else ""
        model = payload.get("model") or ""
        on = f" on {model}" if model else ""
        self.display.info(f"  subagent {payload.get('index', 0) + 1}{on}: {event} {detail}{where}".rstrip())

    def _ask(self, prompt: str) -> str:
        self._prompting = True
        try:
            return self.input_fn(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""
        finally:
            self._prompting = False

    def _approve(self, *, command: str, description: str, pattern_keys: list[str]) -> str:
        self.display.line(f"This command needs your approval ({description}):", "status")
        self.display.line(f"    {command}")
        answer = self._ask("  [o]nce  [s]ession  [a]lways  [d]eny > ").strip().lower()
        return _APPROVAL_KEYS.get(answer, "deny")

    def _clarify(self, question: str, choices: list[str]) -> str:
        self.display.line(question, "status")
        for number, choice in enumerate(choices, start=1):
            self.display.line(f"  {number}. {choice}")
        answer = self._ask("  answer > ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        return answer

    # ── signals and line editing ─────────────────────────────────────────────────────────

    def _on_sigint(self, signum: int, frame: Any) -> None:
        now = time.monotonic()
        if self._prompting or not self.busy or now - self._last_interrupt < FORCE_EXIT_WINDOW_SECONDS:
            raise KeyboardInterrupt
        self._last_interrupt = now
        self.session.interrupt()
        self.display.line("Interrupting… (Ctrl+C again to exit)", "status")

    def _setup_readline(self) -> None:
        if readline is None:
            return
        history = get_home() / ".cli_history"
        try:
            readline.read_history_file(history)
        except OSError:
            pass
        readline.set_history_length(1000)

        def complete(text: str, state: int) -> str | None:
            if not readline.get_line_buffer().startswith("/"):
                return None
            names = sorted(
                "/" + entry["name"] for entry in command_catalog("cli", cwd=self.session.agent.cwd)
            )
            matches = [name for name in names if name.startswith(text)]
            return matches[state] if state < len(matches) else None

        readline.set_completer_delims(" \t\n")
        readline.set_completer(complete)
        readline.parse_and_bind("tab: complete")
        import atexit

        atexit.register(lambda: _save_history(history))

    # ── state ────────────────────────────────────────────────────────────────────────────

    @property
    def busy(self) -> bool:
        return self.turns.busy

    @property
    def _policy(self) -> str:
        return busy_input_mode(self.config)

    # ── the loop ─────────────────────────────────────────────────────────────────────────

    def show_result(self, result: SlashResult | TurnResult) -> bool:
        """Print a command's or a turn's outcome. Returns False when the loop should end."""
        if isinstance(result, SlashResult):
            if result.action == ACTION_CLIPBOARD:
                self._copy(result)
                return True
            if result.text:
                self.display.line(result.text)
            if "skin" in result.data:
                self.display.skin = load_skin(result.data["skin"])
            if "tool_progress" in result.data:
                self.display.tool_progress = result.data["tool_progress"]
            if result.action == ACTION_NEW:
                self.display.info(f"session {self.session.session_id}")
            return result.action != ACTION_QUIT
        self.display.end_stream()
        if result.interrupted:
            self.display.line("(interrupted)", "status")
        elif result.error:
            self.display.error(result.final_response or result.error)
        return True

    def _copy(self, result: SlashResult) -> None:
        """Put the last answer on the clipboard. The one place clipboard I/O happens."""
        from clite.cli.clipboard import copy_to_clipboard

        if copy_to_clipboard(result.text, stream=self.display.out):
            self.display.line(
                f"Copied {result.data.get('chars', len(result.text))} characters to the clipboard.", "status"
            )
        else:
            self.display.error(
                "Could not reach the clipboard. Install one of pbcopy, wl-copy, xclip "
                "or xsel, or use a terminal that supports OSC 52."
            )

    def _run_turn(self, turn: Turn) -> None:
        """Run one queued turn on the worker thread. The caller's thread keeps reading."""
        self._streamed = False
        try:
            outcome = self.session.handle_input(turn.text, images=turn.payload)
        except KeyboardInterrupt:
            self.display.line("(interrupted)", "status")
        except CliteError as exc:
            self.display.error(f"error: {exc}")
        else:
            self.show_result(outcome)

    def _submit(self, text: str, images: list[str] | None = None) -> str:
        """Hand a prompt to the shared queue and report what the busy policy did with it."""
        turn = Turn(text=text, payload=list(images or []))
        outcome = self.turns.submit(turn, self._policy)
        if outcome == SUBMIT_QUEUED:
            self.display.info(f"(queued: {self.turns.pending} waiting behind the running turn)")
        elif outcome == SUBMIT_STEERED:
            self.display.info("(steering the running turn)")
        elif outcome == SUBMIT_REJECTED:
            self.display.line("A turn is running; wait for it or interrupt with Ctrl+C.", "status")
        return outcome

    def _handle_slash(self, text: str) -> bool:
        """Run a slash command on the main thread. Returns False to exit the loop.

        Only reached for commands that may run while a worker is busy (``BUSY_ALLOW``) or when
        nothing is running; a command that has to wait is stopped by :meth:`_dispatch`.
        """
        result = self.session.run_slash(text)
        if result.action == ACTION_SUBMIT:
            self._start_images = []
            self._submit(result.text)
            return True
        return self.show_result(result)

    def run_once(self, line: str) -> bool:
        """Handle one line of input. Returns False to exit.

        Kept synchronous for embedding and tests: it runs the turn here rather than on a
        worker. :meth:`run` uses the queue for the real, concurrent loop.
        """
        text = line.strip()
        if not text:
            return True
        self._streamed = False
        try:
            outcome = self.session.handle_input(text, images=self._start_images)
        except KeyboardInterrupt:
            self.display.line("(interrupted)", "status")
            return True
        except CliteError as exc:
            self.display.error(f"error: {exc}")
            return True
        else:
            # --image applies to the first real turn; a slash command that runs nothing keeps
            # the images for the message that actually goes to the model.
            if isinstance(outcome, TurnResult):
                self._start_images = []
            return self.show_result(outcome)

    def _dispatch(self, line: str) -> bool:
        """Route one line while a worker may be running. Returns False to exit.

        A plain line follows the busy policy through the shared queue. A slash command that is
        safe mid-turn (``BUSY_ALLOW``: ``/stop``, ``/status``, ``/help``, ``/quit``) runs at
        once; any other command has to wait for the running turn, so it is refused with a hint
        rather than racing the worker.
        """
        text = line.strip()
        if not text:
            return True
        name, _ = split_command(text)
        if not name:
            self._start_images = []
            self._submit(text)
            return True
        definition = resolve_command(name)
        waits = definition is None or definition.busy_policy != BUSY_ALLOW
        if self.busy and waits:
            self.display.line(f"/{name} waits for the running turn; use /stop first.", "status")
            return True
        return self._handle_slash(text)

    def run(self) -> int:
        self._setup_readline()
        completer: Completer | None = None
        try:
            completer = build_completer(surface="cli", cwd=self.session.agent.cwd)
        except Exception:  # noqa: BLE001 - completion is optional; the REPL is not
            completer = None
        reader = make_reader(
            input_fn=self.input_fn if self.input_fn is not input else None,
            completer=completer,
            history_path=get_home() / ".cli_history",
        )
        # The concurrent loop needs a reader that owns the prompt line (prompt_toolkit, which
        # also keeps streaming output off it). Without it we keep the classic loop: read a line,
        # run the turn, read the next — the behaviour that always works.
        streaming = getattr(reader, "streaming", None)
        concurrent = streaming is not None
        previous = None
        try:
            previous = signal.signal(signal.SIGINT, self._on_sigint)
        except ValueError:
            pass  # not on the main thread (embedded use): Ctrl+C handling is the host's job
        stream = streaming() if streaming is not None else None
        if stream is not None:
            stream.__enter__()
        self.display.banner(self.session.info())
        prompt = self.display.style(self.display.skin["prompt"], "user_prompt")
        try:
            while True:
                try:
                    line = reader.read_message(prompt)
                except KeyboardInterrupt:
                    self.display.line()
                    continue
                if line is None:
                    self.display.line()
                    break
                if concurrent:
                    keep_going = self._dispatch(line)
                else:
                    keep_going = self.run_once(line)
                if not keep_going:
                    break
        finally:
            if stream is not None:
                stream.__exit__(None, None, None)
            if previous is not None:
                signal.signal(signal.SIGINT, previous)
            self.turns.clear()
            self.session.interrupt()
            self.turns.join(timeout=5)
            self.session.close("cli_exit")
            self.display.info(f"Resume this session with: clite chat --resume {self.session.session_id}")
        return 0


def _save_history(path) -> None:
    try:
        readline.write_history_file(path)
    except OSError:
        pass


def run_single_query(
    query: str,
    *,
    as_json: bool = False,
    quiet: bool = False,
    images: list[str] | None = None,
    **session_options: Any,
) -> int:
    """``clite chat -q``: one turn, the answer on stdout, everything else on stderr."""
    import json

    progress = Display(stream=sys.stderr, tool_progress="off" if quiet or as_json else "all")
    callbacks = AgentCallbacks(
        on_tool_complete=lambda call_id, name, args, result, seconds: progress.tool_done(
            name, args, result, seconds
        ),
        on_status=lambda kind, text: None if quiet else progress.status(kind, text),
    )
    session = ChatSession(platform="cli", callbacks=callbacks, **session_options)
    try:
        outcome = session.handle_input(query, images=list(images or []))
    finally:
        session.close("single_query")
    if isinstance(outcome, SlashResult):
        print(outcome.text)
        return 0
    if as_json:
        print(json.dumps(outcome.to_dict(), ensure_ascii=False))
    else:
        print(outcome.final_response)
    return 0 if outcome.completed else 1
