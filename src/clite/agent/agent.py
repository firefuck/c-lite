"""``AIAgent``: one conversation, usable from any surface.

This class holds the session's state and the few operations a surface needs (run a turn,
interrupt, steer, switch model, compress, close). The turn itself lives in ``agent/loop.py``
and ``agent/turn/``. Keep this file a facade: a new behaviour belongs in a phase, a tool or a
plugin, not in a new method here.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import Any

from clite.agent.budget import IterationBudget
from clite.agent.callbacks import AgentCallbacks
from clite.agent.context.engine import create_context_engine
from clite.agent.loop import run_turn
from clite.agent.memory.manager import MemoryManager
from clite.agent.prompt.builder import PromptInputs, build_system_prompt
from clite.agent.state import TurnResult, TurnState
from clite.agent.todo import TodoStore
from clite.core.config import get_path, load_config
from clite.core.constants import get_home
from clite.core.profiles import get_active_profile_name
from clite.plugins.hooks import invoke_hook
from clite.providers.auxiliary import call_auxiliary
from clite.providers.client import LLMClient, ModelClient
from clite.providers.models import get_context_length
from clite.providers.runtime import RuntimeRoute, resolve_fallback_routes, resolve_runtime_provider
from clite.providers.transports.types import Usage
from clite.state.db import SessionDB, get_session_db, new_session_id
from clite.tools.dispatch import get_tool_definitions

logger = logging.getLogger("clite.agent")

_SESSION_META_KEYS = ("session_key", "user_id", "chat_id", "chat_type", "thread_id", "display_name", "origin")


class AIAgent:
    def __init__(
        self,
        route: RuntimeRoute | None = None,
        *,
        model: str | None = None,
        provider: str | None = None,
        session_id: str | None = None,
        platform: str = "cli",
        cwd: str | None = None,
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
        max_turns: int | None = None,
        callbacks: AgentCallbacks | None = None,
        config: dict[str, Any] | None = None,
        session_db: SessionDB | None = None,
        client: ModelClient | None = None,
        system_message: str | None = None,
        parent: AIAgent | None = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
        approval_mode: str | None = None,
        persist: bool = True,
        session_meta: dict[str, Any] | None = None,
        stream: bool | None = None,
        auto_title: bool = False,
    ) -> None:
        # The config is read once. A session keeps the settings it started with, which keeps
        # its prompt and tool list stable; `/reload` builds a new agent.
        self.config = config if config is not None else load_config()
        self.route = route or resolve_runtime_provider(provider, model, config=self.config)
        self.client: ModelClient = client or LLMClient()
        self.platform = platform
        self.cwd = cwd or str(get_path(self.config, "terminal.cwd", "") or "") or os.getcwd()
        self.parent = parent
        self.depth = parent.depth + 1 if parent is not None else 0
        self.callbacks = callbacks or AgentCallbacks()
        self.approval_mode = approval_mode
        self.system_message = system_message
        self.skip_context_files = skip_context_files
        self.auto_title = auto_title
        self.session_meta = {key: value for key, value in (session_meta or {}).items() if key in _SESSION_META_KEYS}

        self.db: SessionDB | None = (session_db or get_session_db()) if persist else None
        self.session_id = session_id or new_session_id()

        self.enabled_toolsets = list(enabled_toolsets if enabled_toolsets is not None else self.config.get("toolsets") or [])
        self.disabled_toolsets = list(
            disabled_toolsets if disabled_toolsets is not None else self.config.get("disabled_toolsets") or []
        )
        # The tool list is fixed for the session: it is part of the cached request prefix.
        self.tools: list[dict[str, Any]] = get_tool_definitions(self.enabled_toolsets, self.disabled_toolsets, config=self.config)

        self.memory: MemoryManager | None = None if skip_memory else MemoryManager(self.config)
        if self.memory is not None:
            self.tools.extend({"type": "function", "function": schema} for schema in self.memory.provider_tool_schemas())
        self.tool_names: frozenset[str] = frozenset(tool["function"]["name"] for tool in self.tools)

        limit = max_turns if max_turns is not None else get_path(self.config, "agent.max_turns")
        self.budget = IterationBudget(limit)
        self.run_budget_seconds = get_path(self.config, "agent.run_budget_seconds")
        self.reasoning_effort = str(get_path(self.config, "agent.reasoning_effort", "") or "")
        self.stream = bool(get_path(self.config, "display.streaming", True)) if stream is None else stream

        self.context_engine = create_context_engine(str(get_path(self.config, "context.engine", "compressor") or "compressor"))
        self.context_engine.configure(context_length=get_context_length(self.route, self.config), config=self.config)

        self.todos = TodoStore()
        self.messages: list[dict[str, Any]] = []
        self.system_prompt: str | None = None
        self.total_usage = Usage()
        self.interrupt_event = threading.Event()
        self._steer: list[str] = []
        self._lock = threading.RLock()
        self._turn_lock = threading.Lock()
        self._children: list[AIAgent] = []
        self._fallback_routes: list[RuntimeRoute] | None = None
        self._session_ready = False
        self._closed = False
        self._title_requested = False
        self._load_existing_session()

    # ── session lifecycle ────────────────────────────────────────────────────────────────

    def _load_existing_session(self) -> None:
        if self.db is None:
            return
        row = self.db.get_session(self.session_id)
        if row is None:
            return
        self.messages = self.db.get_messages(self.session_id)
        # Reuse the stored prompt byte-for-byte: a resumed session must look exactly like the
        # original to the provider's prompt cache.
        self.system_prompt = row.get("system_prompt") or None
        self._session_ready = True
        self._title_requested = bool(row.get("title"))
        if row.get("ended_at") is not None:
            self.db.update_session(self.session_id, ended_at=None, end_reason=None)  # it is live again
        self.context_engine.on_session_start(self.session_id)

    def _prompt_inputs(self) -> PromptInputs:
        return PromptInputs(
            platform=self.platform, tool_names=self.tool_names, toolsets=tuple(self.enabled_toolsets), cwd=self.cwd,
            config=self.config, model=self.route.model, provider=self.route.provider,
            context_length=self.context_engine.context_length,
            memory_blocks=self.memory.system_prompt_blocks() if self.memory is not None else [],
            system_message=self.system_message, skip_context_files=self.skip_context_files, depth=self.depth,
            profile_name=get_active_profile_name(),
        )

    def rebuild_system_prompt(self) -> str:
        self.system_prompt = build_system_prompt(self._prompt_inputs())
        if self.db is not None and self._session_ready:
            self.db.update_session(self.session_id, system_prompt=self.system_prompt)
        return self.system_prompt

    def ensure_session(self) -> None:
        """Create the session row and build the system prompt, once."""
        with self._lock:
            if self.system_prompt is None:
                self.system_prompt = build_system_prompt(self._prompt_inputs())
                if self.db is not None and self._session_ready:
                    self.db.update_session(self.session_id, system_prompt=self.system_prompt)
            if self._session_ready:
                return
            self._session_ready = True
            if self.db is not None:
                self.db.create_session(
                    self.session_id, self.platform, model=self.route.model, provider=self.route.provider,
                    system_prompt=self.system_prompt, cwd=self.cwd,
                    parent_session_id=self.parent.session_id if self.parent is not None else None,
                    profile_name=get_active_profile_name(), **self.session_meta,
                )
        if self.memory is not None:
            self.memory.initialize(self.session_id, platform=self.platform, home=str(get_home()))
        self.context_engine.on_session_start(self.session_id)
        invoke_hook("on_session_start", session_id=self.session_id, platform=self.platform, model=self.route.model)

    def close(self, reason: str = "closed") -> None:
        """End the session: stop children, flush memory, release the execution environment."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            children = list(self._children)
        for child in children:
            child.interrupt()
        if self._session_ready:
            if self.memory is not None:
                self.memory.on_session_end(self.messages)
            self.context_engine.on_session_end(self.session_id, self.messages)
            invoke_hook("on_session_end", session_id=self.session_id, platform=self.platform, reason=reason,
                        message_count=len(self.messages))
            if self.db is not None and not self.db.closed:
                self.db.end_session(self.session_id, reason)
        if self.memory is not None:
            self.memory.shutdown()
        from clite.tools.builtin.process import process_registry
        from clite.tools.environments import cleanup_environment

        process_registry.kill_all(self.session_id)
        cleanup_environment(self.session_id)

    # ── transcript ───────────────────────────────────────────────────────────────────────

    def append_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Add a message to the transcript. It is durable when this returns."""
        with self._lock:
            self.messages.append(message)
            if self.db is not None:
                message["_row_id"] = self.db.append_message(self.session_id, message)
        return message

    def replace_last_content(self, content: Any) -> None:
        """Rewrite the newest message's content (used to attach steering text)."""
        with self._lock:
            if not self.messages:
                return
            previous = self.messages.pop()
            if self.db is not None and previous.get("_row_id"):
                self.db.deactivate_from(self.session_id, previous["_row_id"])
            updated = {key: value for key, value in previous.items() if key != "_row_id"}
            updated["content"] = content
        self.append_message(updated)

    def get_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(message) for message in self.messages]

    # ── running a turn ───────────────────────────────────────────────────────────────────

    def run_conversation(self, user_message: Any, *, task_id: str | None = None) -> TurnResult:
        """Run one full turn: from the user's message to the assistant's final answer."""
        if self._closed:
            raise RuntimeError("this agent is closed")
        if not self._turn_lock.acquire(blocking=False):
            raise RuntimeError("a turn is already running for this session; interrupt it or wait")
        try:
            state = TurnState(user_message=user_message, route=self.route, task_id=task_id or self.session_id)
            return run_turn(self, state)
        finally:
            self._turn_lock.release()

    def chat(self, message: str) -> str:
        return self.run_conversation(message).final_response

    @property
    def busy(self) -> bool:
        return self._turn_lock.locked()

    def interrupt(self) -> None:
        """Stop the running turn as soon as possible: the model call is aborted, a running
        command is killed, tools that have not started are skipped."""
        self.interrupt_event.set()
        with self._lock:
            children = list(self._children)
        for child in children:
            child.interrupt()

    def steer(self, text: str) -> None:
        """Queue guidance for the running turn without interrupting it."""
        if text.strip():
            with self._lock:
                self._steer.append(text.strip())

    def take_steer(self) -> list[str]:
        with self._lock:
            taken, self._steer = self._steer, []
            return taken

    def record_usage(self, state: TurnState, usage: Usage | None) -> None:
        self.context_engine.update_from_response(usage)
        if usage is None:
            return
        for target in (state.usage, self.total_usage):
            target.input_tokens += usage.input_tokens
            target.output_tokens += usage.output_tokens
            target.cache_read_tokens += usage.cache_read_tokens
            target.cache_write_tokens += usage.cache_write_tokens
            target.reasoning_tokens += usage.reasoning_tokens
        if self.db is not None:
            self.db.add_usage(
                self.session_id, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens, cache_write_tokens=usage.cache_write_tokens,
                reasoning_tokens=usage.reasoning_tokens, api_calls=1,
            )

    # ── model and context ────────────────────────────────────────────────────────────────

    def get_fallback_routes(self) -> list[RuntimeRoute]:
        if self._fallback_routes is None:
            self._fallback_routes = resolve_fallback_routes(self.config)
        return self._fallback_routes

    def switch_model(self, route: RuntimeRoute) -> None:
        """Use another model from the next turn on. The prompt cache is lost either way, so
        the system prompt is rebuilt to name the new model."""
        self.route = route
        self.context_engine.configure(context_length=get_context_length(route, self.config), config=self.config)
        if self._session_ready:
            self.rebuild_system_prompt()
            if self.db is not None:
                self.db.update_session(self.session_id, model=route.model, provider=route.provider)

    def compress_context(self, state: TurnState | None = None, *, focus: str | None = None, reason: str = "manual") -> bool:
        """Shrink the transcript. True when it changed.

        This is the one operation allowed to rewrite history and rebuild the system prompt.
        Old rows are archived under the same session id, so they stay searchable.
        """
        with self._lock:
            before = list(self.messages)
        if state is not None:
            state.compression_attempts += 1
        self.callbacks.emit("on_status", "compressing", f"compressing context ({reason})")
        if self.memory is not None:
            self.memory.before_compress(before)

        def summarize(prompt: str) -> str:
            return call_auxiliary("compression", [{"role": "user", "content": prompt}], main_route=self.route,
                                  client=self.client, max_tokens=4000, config=self.config)

        after = self.context_engine.compress(before, summarize=summarize, focus=focus)
        if after is before or after == before:
            self.callbacks.emit("on_status", "compressed", "nothing to compress yet")
            return False
        todo_note = self.todos.format_active()
        cleaned = [{key: value for key, value in message.items() if key != "_row_id"} for message in after]
        if todo_note:
            for message in cleaned:
                if message.get("is_summary") and isinstance(message.get("content"), str):
                    message["content"] += f"\n\n{todo_note}"
                    break
        with self._lock:
            if self.db is not None:
                row_ids = self.db.replace_active_messages(self.session_id, cleaned)
                for message, row_id in zip(cleaned, row_ids, strict=True):
                    message["_row_id"] = row_id
            self.messages = cleaned
        # Memory written during the session becomes visible now; the prefix is new anyway.
        if self.memory is not None:
            self.memory.reload()
        self.rebuild_system_prompt()
        self.callbacks.emit("on_status", "compressed", f"context compressed: {len(before)} messages -> {len(cleaned)}")
        return True

    def context_status(self) -> dict[str, Any]:
        return {**self.context_engine.status(), "messages": len(self.messages), "model": self.route.model,
                "provider": self.route.provider}

    # ── helpers used by tools and phases ─────────────────────────────────────────────────

    def register_child(self, child: AIAgent) -> None:
        with self._lock:
            self._children.append(child)

    def unregister_child(self, child: AIAgent) -> None:
        with self._lock:
            if child in self._children:
                self._children.remove(child)

    def maybe_generate_title(self, user_text: str) -> None:
        if not self.auto_title or self._title_requested or self.db is None or self.depth > 0:
            return
        self._title_requested = True
        from clite.agent.title import generate_title_async

        generate_title_async(self, user_text)

    @staticmethod
    def new_task_id() -> str:
        return uuid.uuid4().hex[:12]
