"""``ChatSession``: one conversation as a surface sees it.

It owns an ``AIAgent`` and everything a surface does around it: starting, resuming and
resetting sessions, slash commands, model switches, retry and undo. The CLI, the RPC server
and the gateway each hold a ``ChatSession`` and only translate between it and their own input
and output.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any

from clite.agent import AgentCallbacks, AIAgent, TurnResult
from clite.agent.messages import content_text
from clite.core.config import load_config
from clite.plugins.hooks import invoke_hook
from clite.plugins.manager import get_plugin_manager
from clite.providers.client import ModelClient
from clite.providers.model_switch import ModelSwitchResult, switch_model
from clite.runtime.commands import resolve_command, split_command
from clite.runtime.factory import build_agent
from clite.skills.commands import build_skill_message, skill_commands
from clite.state.db import get_session_db

logger = logging.getLogger("clite.runtime.session")

ACTION_QUIT = "quit"
ACTION_SUBMIT = "submit"  # ``text`` is a prompt to run as the next turn
ACTION_NEW = "new"  # the session was replaced; the surface should refresh its view
QUICK_COMMAND_TIMEOUT = 30


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

    def submit(self, text: Any) -> TurnResult:
        """Run one turn with ``text`` as the user's message."""
        return self.agent.run_conversation(text)

    def handle_input(self, text: str) -> SlashResult | TurnResult:
        """Dispatch a line of input: a slash command, or a prompt for the model."""
        name, _ = split_command(text)
        if not name:
            return self.submit(text)
        result = self.run_slash(text)
        if result.action == ACTION_SUBMIT:
            return self.submit(result.text)
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
            if message.get("role") == "user" and not message.get("is_summary"):
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
