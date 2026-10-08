"""``ChatSession``: one conversation as a surface sees it.

It owns an ``AIAgent`` and everything a surface does around it: starting, resuming and
resetting sessions, slash commands, model switches, retry and undo. The CLI, the RPC server
and the gateway each hold a ``ChatSession`` and only translate between it and their own input
and output.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from clite.agent import AgentCallbacks, AIAgent, TurnResult
from clite.agent.attachments import AttachmentError, build_content, load_images
from clite.agent.messages import content_text, is_internal
from clite.core.config import load_config
from clite.core.threads import start_thread
from clite.plugins.hooks import invoke_hook
from clite.plugins.manager import get_plugin_manager
from clite.providers.client import ModelClient
from clite.providers.model_switch import ModelSwitchResult, switch_model
from clite.runtime.commands import resolve_command, split_command
from clite.runtime.factory import build_agent
from clite.skills.commands import build_skill_message, skill_commands
from clite.state.db import get_session_db
from clite.tools.checkpoints import RollbackResult, TurnGroup, list_checkpoints, rollback

logger = logging.getLogger("clite.runtime.session")

ACTION_QUIT = "quit"
ACTION_SUBMIT = "submit"  # ``text`` is a prompt to run as the next turn
ACTION_NEW = "new"  # the session was replaced; the surface should refresh its view
QUICK_COMMAND_TIMEOUT = 30

# What a line that arrives while a turn already runs should do (``display.busy_input_mode``).
BUSY_QUEUE = "queue"  # run it after the current turn finishes
BUSY_INTERRUPT = "interrupt"  # stop the current turn, run this one next
BUSY_STEER = "steer"  # hand it to the running turn as guidance, do not interrupt
BUSY_REJECT = "reject"  # refuse it; the surface decides what to say

BUSY_MODES = (BUSY_QUEUE, BUSY_INTERRUPT, BUSY_STEER, BUSY_REJECT)

# Outcome of ``TurnQueue.submit``:
SUBMIT_STARTED = "started"  # the session was idle; this turn started a worker
SUBMIT_QUEUED = "queued"  # accepted, waiting behind the running turn
SUBMIT_STEERED = "steered"  # handed to the running turn as guidance
SUBMIT_REJECTED = "rejected"  # refused because a turn is running


@dataclass
class Turn:
    """One queued turn. ``id`` is the surface's name for it (a turn id, a chat key);
    ``payload`` carries whatever that surface needs to run it (loaded image parts, the
    source a reply goes to)."""

    text: str
    id: str = ""
    payload: Any = None


class TurnQueue:
    """Serializes turns for one :class:`ChatSession` and applies the busy policy.

    Every surface that lets the user keep typing while the agent works (the REPL, the RPC
    server, the gateway) shares this: a line that arrives during a turn follows
    ``display.busy_input_mode`` (steer, interrupt, reject or queue), and the first line while
    idle starts a worker thread that drains the queue. The caller's thread keeps reading.

    ``run`` does the actual work for one turn (submit it, emit events, reply). Everything
    surface-specific lives there and in ``on_queued``; this class owns only the queue, the
    worker and the policy.
    """

    def __init__(self, session: ChatSession, run: Callable[[Turn], None], *,
                 merge_bursts: bool = False, thread_name: str = "clite-turn",
                 lock: threading.Lock | None = None) -> None:
        self.session = session
        self._run = run
        # When several lines pile up in ``interrupt`` mode they are one thought: run them as
        # a single message, joined by a blank line. ``queue`` mode keeps them apart and in order.
        self.merge_bursts = merge_bursts
        self.thread_name = thread_name
        self._lock = lock or threading.Lock()
        self._queue: list[Turn] = []
        self._worker: threading.Thread | None = None

    # ── state ────────────────────────────────────────────────────────────────────────────

    @property
    def busy(self) -> bool:
        worker = self._worker
        return self.session.busy or (worker is not None and worker.is_alive())

    @property
    def pending(self) -> int:
        return len(self._queue)

    # ── submitting ───────────────────────────────────────────────────────────────────────

    def submit(self, turn: Turn, mode: str | None = None) -> str:
        """Enqueue ``turn`` (or steer/reject it) and return one of the ``SUBMIT_*`` outcomes.

        ``mode`` is a ``display.busy_input_mode`` value; the caller passes its own override
        when it has one (the RPC ``busy_mode`` field). A rejected line raises nothing here:
        the surface turns ``SUBMIT_REJECTED`` into whatever it says to the user.
        """
        mode = mode or busy_input_mode()
        with self._lock:
            if self.busy:
                if mode == BUSY_STEER:
                    self.session.steer(turn.text)
                    return SUBMIT_STEERED
                if mode == BUSY_REJECT:
                    return SUBMIT_REJECTED
                self._queue.append(turn)
                if mode == BUSY_INTERRUPT:
                    self.session.interrupt()
                return SUBMIT_QUEUED
            self._queue.append(turn)
            self._worker = start_thread(self._drain, name=self.thread_name)
        return SUBMIT_STARTED

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    return
                if self.merge_bursts:
                    text = "\n\n".join(turn.text for turn in self._queue)
                    payload = self._queue[-1].payload
                    turn_id = self._queue[-1].id
                    self._queue.clear()
                    turn = Turn(text=text, id=turn_id, payload=payload)
                else:
                    turn = self._queue.pop(0)
            self._run(turn)

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()

    def join(self, timeout: float | None = None) -> None:
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=timeout)


def busy_input_mode(config: dict[str, Any] | None = None) -> str:
    """``display.busy_input_mode``, defaulting to ``interrupt`` and clamped to a known value."""
    from clite.core.config import get_path

    conf = config if config is not None else load_config()
    mode = str(get_path(conf, "display.busy_input_mode", BUSY_INTERRUPT) or BUSY_INTERRUPT)
    return mode if mode in BUSY_MODES else BUSY_INTERRUPT


@dataclass
class SlashResult:
    text: str = ""
    action: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class ChatSession:
    def __init__(
        self,
        *,
        platform: str = "cli",
        callbacks: AgentCallbacks | None = None,
        session_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        toolsets: list[str] | None = None,
        cwd: str | None = None,
        yolo: bool = False,
        client: ModelClient | None = None,
        system_message: str | None = None,
        session_meta: dict[str, Any] | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.platform = platform
        self.callbacks = callbacks or AgentCallbacks()
        self.yolo = yolo
        self._options: dict[str, Any] = {
            "model": model, "provider": provider, "toolsets": toolsets, "cwd": cwd, "client": client,
            "system_message": system_message, "session_meta": session_meta, "max_turns": max_turns,
        }
        self.agent: AIAgent = self._build(session_id)
        # Image paths the user queued with /image, waiting for the next submitted message.
        self._pending_images: list[str] = []

    # ── construction ─────────────────────────────────────────────────────────────────────

    def _build(self, session_id: str | None, *, route: Any = None) -> AIAgent:
        options = dict(self._options)
        if route is not None:
            options.update(route=route, model=None, provider=None)
        return build_agent(platform=self.platform, session_id=session_id, callbacks=self.callbacks, yolo=self.yolo,
                           config=load_config(), **options)

    def _replace_agent(self, session_id: str | None, *, close_reason: str, keep_route: bool = True) -> None:
        route = self.agent.route if keep_route else None
        self.agent.close(close_reason)
        self.agent = self._build(session_id, route=route)

    @property
    def session_id(self) -> str:
        return self.agent.session_id

    @property
    def busy(self) -> bool:
        return self.agent.busy

    # ── turns ────────────────────────────────────────────────────────────────────────────

    def submit(self, text: Any, *, images: list[str] | None = None,
               image_parts: list[dict[str, Any]] | None = None) -> TurnResult:
        """Run one turn with ``text`` as the user's message.

        ``images`` are local paths attached to this message; ``image_parts`` are already
        loaded content parts (surfaces that validate on their own thread, like RPC, use this
        so a bad path is an error there rather than mid-turn). Paths queued earlier with
        ``/image`` are prepended and cleared: the pictures join the message sent next.
        """
        queued = self._take_pending_images()
        paths = [*queued, *(images or [])]
        parts = [*self.load_attachments(paths), *(image_parts or [])]
        content = text
        if parts:
            text_value = text if isinstance(text, str) else content_text(text)
            content = build_content(text_value, parts)
        return self.agent.run_conversation(content)

    def queue_image(self, path: str) -> str:
        """Remember an image for the next message. Returns a line to show the user.

        The path is checked here so `/image typo.png` fails at once, while the (expensive)
        decode and downscaling still happen when the message is actually sent.
        """
        from pathlib import Path

        target = Path(path).expanduser()
        if not target.exists():
            raise AttachmentError(f"no file at {target}")
        if not target.is_file():
            raise AttachmentError(f"{target} is not a file")
        self._pending_images.append(str(path))
        return f"Image queued: {target} ({len(self._pending_images)} waiting)"

    @property
    def pending_image_count(self) -> int:
        return len(self._pending_images)

    def _take_pending_images(self) -> list[str]:
        queued, self._pending_images = self._pending_images, []
        return queued

    def load_attachments(self, paths: list[str]) -> list[dict[str, Any]]:
        """Load, bound and shrink images. Raises ``AttachmentError`` on a bad or oversized one."""
        if not paths:
            return []
        from clite.core.config import get_path

        config = self.agent.config
        return load_images(
            paths,
            max_count=int(get_path(config, "attachments.max_images", 8) or 8),
            max_bytes=int(get_path(config, "attachments.max_bytes", 5_000_000) or 5_000_000),
            max_edge=int(get_path(config, "attachments.max_edge", 1568) or 1568),
        )

    def handle_input(self, text: str, *, images: list[str] | None = None) -> SlashResult | TurnResult:
        """Dispatch a line of input: a slash command, or a prompt for the model."""
        name, _ = split_command(text)
        if not name:
            return self.submit(text, images=images)
        result = self.run_slash(text)
        if result.action == ACTION_SUBMIT:
            return self.submit(result.text, images=images)
        return result

    def interrupt(self) -> None:
        self.agent.interrupt()

    def steer(self, text: str) -> None:
        self.agent.steer(text)

    # ── slash commands ───────────────────────────────────────────────────────────────────

    def run_slash(self, text: str) -> SlashResult:
        """Resolve and run a slash command: built-in, then plugin, quick command, skill."""
        from clite.runtime.slash import SLASH_HANDLERS

        name, args = split_command(text)
        if not name:
            return SlashResult("Not a command.")
        command = resolve_command(name)
        if command is not None:
            if command.cli_only and self.platform not in ("cli", "tui", "desktop"):
                return SlashResult(f"/{command.name} is only available in the terminal.")
            return SLASH_HANDLERS[command.name](self, args)

        plugin_command = get_plugin_manager().commands.get(name)
        if plugin_command is not None:
            try:
                output = plugin_command.handler(args, self)
            except Exception as exc:  # noqa: BLE001 - a plugin bug is reported, not raised
                logger.warning("plugin command /%s failed", name, exc_info=True)
                return SlashResult(f"/{name} failed: {type(exc).__name__}: {exc}")
            return SlashResult(str(output) if output is not None else "")

        quick = (self.agent.config.get("quick_commands") or {}).get(name)
        if isinstance(quick, dict):
            return self._run_quick_command(name, quick, args)

        skill = skill_commands(cwd=self.agent.cwd, config=self.agent.config).get(name)
        if skill is not None:
            return SlashResult(build_skill_message(skill, args), ACTION_SUBMIT, {"skill": skill.name})

        from clite.runtime.slash import run_mcp_prompt
        from clite.tools.mcp import mcp_prompt_commands

        if name in mcp_prompt_commands():
            return run_mcp_prompt(self, name, args)
        return SlashResult(f"Unknown command: /{name}. Type /help to list commands.")

    def _run_quick_command(self, name: str, spec: dict[str, Any], args: str) -> SlashResult:
        kind = spec.get("type", "exec")
        if kind == "alias":
            target = str(spec.get("target") or "").strip()
            if not target.startswith("/") or split_command(target)[0] == name:
                return SlashResult(f"quick command /{name} has an invalid alias target")
            return self.run_slash(f"{target} {args}".strip())
        if kind == "exec":
            # The user wrote this command into their own config: it runs as given, without
            # the model and without the approval gate.
            try:
                completed = subprocess.run(  # noqa: S602
                    str(spec.get("command") or ""), shell=True, capture_output=True, text=True,
                    timeout=QUICK_COMMAND_TIMEOUT, cwd=self.agent.cwd, check=False)
            except subprocess.TimeoutExpired:
                return SlashResult(f"/{name} timed out after {QUICK_COMMAND_TIMEOUT}s")
            output = (completed.stdout + completed.stderr).strip()
            return SlashResult(output or f"(/{name} produced no output, exit code {completed.returncode})")
        return SlashResult(f"quick command /{name} has unknown type {kind!r} (use exec or alias)")

    # ── session management ───────────────────────────────────────────────────────────────

    def new_session(self) -> str:
        invoke_hook("on_session_reset", session_id=self.agent.session_id, platform=self.platform)
        self._replace_agent(None, close_reason="new_session")
        return self.agent.session_id

    def resume(self, reference: str) -> bool:
        row = get_session_db().find_session(reference)
        if row is None:
            return False
        self._replace_agent(row["id"], close_reason="resumed_other")
        return True

    def reload(self) -> None:
        """Pick up config and plugin changes. The conversation continues, but the tool list
        and system prompt may change, which costs one prompt-cache miss."""
        from clite.core.config import reset_config_cache
        from clite.providers.registry import reset_user_layers

        reset_config_cache()
        reset_user_layers()
        get_plugin_manager().load_all()
        session_id = self.agent.session_id
        had_session = bool(self.agent.messages)
        self.agent.close("reload")
        self.agent = self._build(session_id if had_session else None)
        if had_session:
            self.agent.rebuild_system_prompt()

    def switch_model(self, text: str, *, persist: bool = False) -> ModelSwitchResult:
        result = switch_model(text, current=self.agent.route, persist=persist, config=self.agent.config)
        if result.success and result.route is not None:
            self.agent.switch_model(result.route)
            self._options.update(model=None, provider=None)
        return result

    def set_yolo(self, enabled: bool) -> None:
        self.yolo = enabled
        self.agent.approval_mode = "off" if enabled else None

    def undo(self) -> str | None:
        """Remove the last user turn and everything after it. Returns the removed user text."""
        messages = self.agent.messages
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.get("role") == "user" and not message.get("is_summary") and not is_internal(message):
                text = content_text(message.get("content"))
                row_id = message.get("_row_id")
                if self.agent.db is not None and row_id:
                    self.agent.db.deactivate_from(self.agent.session_id, row_id)
                del messages[index:]
                return text
        return None

    def set_title(self, title: str) -> str:
        self.agent.ensure_session()
        return get_session_db().set_title(self.agent.session_id, title, source="user")

    # ── file checkpoints ─────────────────────────────────────────────────────────────────

    def rollback_files(self, turns: int = 1) -> RollbackResult:
        """Restore the files the agent changed in the last ``turns`` turns."""
        return rollback(self.agent.session_id, turns=turns)

    def list_file_checkpoints(self) -> list[TurnGroup]:
        """The stored file-change groups for this session, oldest first."""
        return list_checkpoints(self.agent.session_id)

    def info(self) -> dict[str, Any]:
        row = get_session_db().get_session(self.agent.session_id) or {}
        return {
            "session_id": self.agent.session_id, "title": row.get("title") or "", "platform": self.platform,
            "model": self.agent.route.model, "provider": self.agent.route.provider, "cwd": self.agent.cwd,
            "busy": self.busy, "yolo": self.yolo, "message_count": len(self.agent.messages),
            "tools": sorted(self.agent.tool_names), "toolsets": list(self.agent.enabled_toolsets),
            "context": self.agent.context_status(), "reasoning_effort": self.agent.reasoning_effort,
        }

    def close(self, reason: str = "closed") -> None:
        self.agent.close(reason)
