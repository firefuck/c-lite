"""The classic interactive CLI: a read-eval-print loop over a ``ChatSession``.

Standard library only (``input`` plus ``readline`` when the platform has it). It is the
fallback that always works: over SSH, in a container, with no Node installed. The richer
interface is the TUI (``clite tui``), which talks to the same session logic over JSON-RPC.

Ctrl+C while the agent works interrupts the turn; a second Ctrl+C within two seconds exits.
"""

from __future__ import annotations

import signal
import sys
import time
from typing import Any

from clite.agent import AgentCallbacks, TurnResult
from clite.cli.display import Display
from clite.core.config import get_path, load_config
from clite.core.constants import get_home
from clite.core.errors import CliteError
from clite.runtime.commands import command_catalog
from clite.runtime.session import ACTION_NEW, ACTION_QUIT, ChatSession, SlashResult

try:
    import readline
except ImportError:  # Windows without pyreadline
    readline = None  # type: ignore[assignment]

_APPROVAL_KEYS = {"o": "once", "once": "once", "s": "session", "session": "session", "a": "always",
                  "always": "always", "d": "deny", "deny": "deny", "n": "deny", "": "deny"}
FORCE_EXIT_WINDOW_SECONDS = 2.0


class Repl:
    def __init__(self, *, display: Display | None = None, input_fn=input, **session_options: Any) -> None:
        config = load_config()
        self.display = display or Display(
            skin=str(get_path(config, "display.skin", "default")),
            tool_progress=str(get_path(config, "display.tool_progress", "all")),
        )
        self.input_fn = input_fn
        self.show_reasoning = bool(get_path(config, "display.show_reasoning", False))
        self._prompting = False
        self._last_interrupt = 0.0
        self._streamed = False
        self.session = ChatSession(platform="cli", callbacks=self._callbacks(), **session_options)

    # ── callbacks ────────────────────────────────────────────────────────────────────────

    def _callbacks(self) -> AgentCallbacks:
        def on_delta(text: str) -> None:
            self._streamed = True
            self.display.delta(text)

        def on_message(message: dict[str, Any]) -> None:
            # Text that arrived without streaming (or before a tool call) still has to be shown.
            if not self._streamed and message.get("content"):
                self.display.line(str(message["content"]))
            self.display.end_stream()
            self._streamed = False

        return AgentCallbacks(
            on_delta=on_delta,
            on_reasoning=(lambda text: self.display.delta(self.display.style(text, "info"))) if self.show_reasoning else None,
            on_message=on_message,
            on_tool_start=lambda call_id, name, args: self.display.tool_start(name, args),
            on_tool_complete=lambda call_id, name, args, result, seconds: self.display.tool_done(name, args, result, seconds),
            on_status=self.display.status,
            on_subagent=lambda event, payload: self.display.info(f"  subagent {payload.get('index', 0) + 1}: {event} "
                                                                 f"{payload.get('tool') or payload.get('status') or ''}"),
            approve=self._approve,
            clarify=self._clarify,
        )

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
        if self._prompting or not self.session.busy or now - self._last_interrupt < FORCE_EXIT_WINDOW_SECONDS:
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
            names = sorted("/" + entry["name"] for entry in command_catalog("cli", cwd=self.session.agent.cwd))
            matches = [name for name in names if name.startswith(text)]
            return matches[state] if state < len(matches) else None

        readline.set_completer_delims(" \t\n")
        readline.set_completer(complete)
        readline.parse_and_bind("tab: complete")
        import atexit

        atexit.register(lambda: _save_history(history))

    # ── the loop ─────────────────────────────────────────────────────────────────────────

    def show_result(self, result: SlashResult | TurnResult) -> bool:
        """Print a command's or a turn's outcome. Returns False when the loop should end."""
        if isinstance(result, SlashResult):
            if result.text:
                self.display.line(result.text)
            if result.action == ACTION_NEW:
                self.display.info(f"session {self.session.session_id}")
            return result.action != ACTION_QUIT
        self.display.end_stream()
        if result.interrupted:
            self.display.line("(interrupted)", "status")
        elif result.error:
            self.display.error(result.final_response or result.error)
        return True

    def run_once(self, line: str) -> bool:
        """Handle one line of input. Returns False to exit."""
        text = line.strip()
        if not text:
            return True
        self._streamed = False
        try:
            return self.show_result(self.session.handle_input(text))
        except KeyboardInterrupt:
            self.display.line("(interrupted)", "status")
            return True
        except CliteError as exc:
            self.display.error(f"error: {exc}")
            return True

    def run(self) -> int:
        self._setup_readline()
        previous = None
        try:
            previous = signal.signal(signal.SIGINT, self._on_sigint)
        except ValueError:
            pass  # not on the main thread (embedded use): Ctrl+C handling is the host's job
        self.display.banner(self.session.info())
        try:
            while True:
                try:
                    line = self.input_fn(self.display.style(self.display.skin["prompt"], "user_prompt"))
                except KeyboardInterrupt:
                    self.display.line()
                    continue
                except EOFError:
                    self.display.line()
                    break
                if not self.run_once(line):
                    break
        finally:
            if previous is not None:
                signal.signal(signal.SIGINT, previous)
            self.session.close("cli_exit")
            self.display.info(f"Resume this session with: clite chat --resume {self.session.session_id}")
        return 0


def _save_history(path) -> None:
    try:
        readline.write_history_file(path)
    except OSError:
        pass


def run_single_query(query: str, *, as_json: bool = False, quiet: bool = False, **session_options: Any) -> int:
    """``clite chat -q``: one turn, the answer on stdout, everything else on stderr."""
    import json

    progress = Display(stream=sys.stderr, tool_progress="off" if quiet or as_json else "all")
    callbacks = AgentCallbacks(
        on_tool_complete=lambda call_id, name, args, result, seconds: progress.tool_done(name, args, result, seconds),
        on_status=lambda kind, text: None if quiet else progress.status(kind, text),
    )
    session = ChatSession(platform="cli", callbacks=callbacks, **session_options)
    try:
        outcome = session.handle_input(query)
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
