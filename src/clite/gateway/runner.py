"""``GatewayRunner``: the policy layer between chat platforms and the agent.

For every inbound message, in this order:

1. plugins may drop or rewrite it (``pre_gateway_dispatch``);
2. authorization: platform allowlist, ``gateway.allow_all_users``, paired users; an unknown
   user in a direct message is offered a pairing code, anywhere else they are ignored;
3. the message is routed to its session (see ``gateway.session``);
4. if that session is waiting for an answer (an approval or a question), the message is the
   answer;
5. a slash command is run; anything else becomes the next turn, subject to the busy policy.

A turn runs on its own thread, so one long task never blocks another chat.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from clite.agent import AgentCallbacks
from clite.core.config import get_path, load_config
from clite.core.errors import CliteError
from clite.core.threads import start_thread
from clite.gateway.event import CHAT_DM, MessageEvent, SessionSource
from clite.gateway.pairing import PairingStore
from clite.gateway.platforms.base import PLATFORMS, BasePlatformAdapter, split_message
from clite.gateway.session import SessionMap, build_session_key
from clite.plugins.hooks import has_hook, invoke_hook
from clite.plugins.manager import ensure_plugins_loaded
from clite.runtime.commands import BUSY_ALLOW, resolve_command, split_command
from clite.runtime.session import ACTION_NEW, ACTION_SUBMIT, ChatSession

logger = logging.getLogger("clite.gateway")

_APPROVAL_WORDS = {
    "approve": "once", "yes": "once", "y": "once", "ok": "once", "once": "once",
    "session": "session", "always": "always", "deny": "deny", "no": "deny", "n": "deny",
}


@dataclass
class _Pending:
    """A question the agent asked that the next message from this chat answers."""

    kind: str  # "approval" | "clarify"
    choices: list[str] = field(default_factory=list)
    answered: threading.Event = field(default_factory=threading.Event)
    answer: str = ""


@dataclass
class GatewaySession:
    key: str
    source: SessionSource
    chat: ChatSession
    last_used: float = field(default_factory=time.monotonic)
    queue: list[str] = field(default_factory=list)
    worker: threading.Thread | None = None
    pending: _Pending | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def busy(self) -> bool:
        return self.chat.busy or (self.worker is not None and self.worker.is_alive())


class GatewayRunner:
    def __init__(self, config: dict[str, Any] | None = None, *, client_factory: Any = None) -> None:
        self.config = config if config is not None else load_config()
        self.client_factory = client_factory  # tests inject a scripted model client
        self.adapters: dict[str, BasePlatformAdapter] = {}
        self.sessions: dict[str, GatewaySession] = {}
        self.session_map = SessionMap()
        self.pairing = PairingStore()
        self._lock = threading.RLock()
        self._scheduler: Any = None
        self.running = False

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def start(self, *, with_cron: bool = True) -> list[str]:
        """Connect every enabled platform. Returns the names that started."""
        import clite.gateway.platforms.local  # noqa: F401 - registers the built-in adapters
        import clite.gateway.platforms.telegram  # noqa: F401

        ensure_plugins_loaded()  # plugins may register more platforms
        started = []
        for name, settings in (get_path(self.config, "gateway.platforms", {}) or {}).items():
            if not isinstance(settings, dict) or not settings.get("enabled", True):
                continue
            factory = PLATFORMS.get(name)
            if factory is None:
                logger.warning("gateway platform %r is configured but no adapter is installed", name)
                continue
            try:
                adapter = factory(settings, self)
                adapter.connect()
            except Exception as exc:  # noqa: BLE001 - one platform failing must not stop the others
                logger.warning("gateway platform %s failed to start: %s", name, exc)
                continue
            self.adapters[name] = adapter
            started.append(name)
        self.running = True
        if with_cron and get_path(self.config, "cron.enabled", True):
            from clite.cron.scheduler import Scheduler

            self._scheduler = Scheduler(deliver=self.deliver, client=self.client_factory() if self.client_factory else None)
            self._scheduler.start()
        return started

    def stop(self) -> None:
        self.running = False
        if self._scheduler is not None:
            self._scheduler.stop()
        with self._lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            self._close_session(session, "gateway_stop")
        for adapter in self.adapters.values():
            try:
                adapter.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("disconnect failed for %s", adapter.name, exc_info=True)
        self.adapters.clear()

    def _close_session(self, session: GatewaySession, reason: str) -> None:
        if session.pending is not None:
            session.pending.answered.set()
        session.chat.interrupt()
        if session.worker is not None and session.worker is not threading.current_thread():
            session.worker.join(timeout=5)
        session.chat.close(reason)

    # ── sending ──────────────────────────────────────────────────────────────────────────

    def reply(self, source: SessionSource, text: str) -> None:
        adapter = self.adapters.get(source.platform)
        if adapter is None or not text.strip():
            return
        for chunk in split_message(text, adapter.max_message_length):
            result = adapter.send(source.chat_id, chunk, thread_id=source.thread_id)
            if not result.success:
                logger.warning("send to %s:%s failed: %s", source.platform, source.chat_id, result.error)
                return

    def deliver(self, job: dict[str, Any], text: str) -> None:
        """Deliver a cron job's output: to where the job was created, or to ``platform:chat``."""
        target = str(job.get("deliver") or "local")
        origin = job.get("origin") or {}
        if target == "origin":
            platform, chat_id, thread_id = origin.get("platform"), origin.get("chat_id"), origin.get("thread_id")
        else:
            platform, _, chat_id = target.partition(":")
            thread_id = None
        if not platform or not chat_id or platform not in self.adapters:
            raise RuntimeError(f"cannot deliver to {target!r}: the platform is not connected or the chat is unknown")
        label = job.get("name") or f"job {job['id']}"
        self.reply(SessionSource(platform=platform, chat_id=str(chat_id), thread_id=thread_id), f"[{label}]\n{text}")

    # ── authorization ────────────────────────────────────────────────────────────────────

    def is_authorized(self, source: SessionSource) -> bool:
        adapter = self.adapters.get(source.platform)
        if adapter is not None and source.user_id in adapter.allowed_users():
            return True
        if get_path(self.config, "gateway.allow_all_users", False):
            return True
        return self.pairing.is_approved(source.platform, source.user_id)

    def _handle_unauthorized(self, source: SessionSource) -> None:
        if source.chat_type != CHAT_DM:
            return  # never answer strangers in a group
        code = self.pairing.request_code(source.platform, source.user_id, source.user_name)
        if code is None:
            return  # rate-limited: stay silent rather than become a spam relay
        self.reply(source, (
            "I do not know you yet. Ask the owner of this agent to approve you with:\n\n"
            f"clite gateway pair approve {source.platform} {code}\n\nThe code is valid for one hour."
        ))

    # ── sessions ─────────────────────────────────────────────────────────────────────────

    def _callbacks(self, key: str, source: SessionSource) -> AgentCallbacks:
        timeout = float(get_path(self.config, "approvals.timeout", 300) or 300)

        def ask(pending: _Pending, message: str) -> str:
            session = self.sessions.get(key)
            if session is None:
                return ""
            session.pending = pending
            self.reply(source, message)
            pending.answered.wait(timeout)
            session.pending = None
            return pending.answer

        def approve(*, command: str, description: str, pattern_keys: list[str]) -> str:
            answer = ask(_Pending("approval"), (
                f"This command needs your approval ({description}):\n\n{command}\n\n"
                "Reply /approve (once), /approve session, /approve always, or /deny."
            ))
            return answer or "deny"  # silence is a no

        def clarify(question: str, choices: list[str]) -> str:
            options = "".join(f"\n{number}. {choice}" for number, choice in enumerate(choices, start=1))
            return ask(_Pending("clarify", choices), f"{question}{options}")

        def on_status(kind: str, text: str) -> None:
            if kind in ("fallback", "compressed"):
                self.reply(source, f"[{text}]")

        return AgentCallbacks(approve=approve, clarify=clarify, on_status=on_status)

    def _get_session(self, source: SessionSource) -> GatewaySession:
        key = build_session_key(source, group_sessions_per_user=bool(get_path(self.config, "gateway.group_sessions_per_user", True)))
        with self._lock:
            self._evict_idle()
            session = self.sessions.get(key)
            if session is None:
                chat = ChatSession(
                    platform=source.platform, callbacks=self._callbacks(key, source), session_id=self.session_map.get(key),
                    client=self.client_factory() if self.client_factory else None,
                    session_meta={"session_key": key, "user_id": source.user_id, "chat_id": source.chat_id,
                                  "chat_type": source.chat_type, "thread_id": source.thread_id,
                                  "display_name": source.user_name, "origin": source.to_dict()},
                )
                session = self.sessions[key] = GatewaySession(key, source, chat)
                self.session_map.set(key, chat.session_id, source)
            session.last_used = time.monotonic()
            return session

    def _evict_idle(self) -> None:
        ttl = float(get_path(self.config, "gateway.agent_cache_ttl_seconds", 3600) or 0)
        if not ttl:
            return
        now = time.monotonic()
        for key in [key for key, session in self.sessions.items() if now - session.last_used > ttl and not session.busy]:
            # The conversation is not lost: the next message resumes it from the database.
            self._close_session(self.sessions.pop(key), "idle")

    # ── dispatch ─────────────────────────────────────────────────────────────────────────

    def dispatch(self, event: MessageEvent) -> None:
        """Handle one inbound message. Called from adapter threads; returns quickly."""
        try:
            self._dispatch(event)
        except CliteError as exc:
            self.reply(event.source, f"Error: {exc}")
        except Exception:  # noqa: BLE001 - a bad message must not kill the adapter's receive loop
            logger.exception("gateway dispatch failed")
            self.reply(event.source, "Something went wrong handling that message. The error was logged.")

    def _dispatch(self, event: MessageEvent) -> None:
        text = event.text.strip()
        if has_hook("pre_gateway_dispatch"):
            for directive in invoke_hook("pre_gateway_dispatch", event=event, gateway=self):
                if isinstance(directive, dict) and directive.get("action") == "skip":
                    return
                if isinstance(directive, dict) and directive.get("action") == "rewrite":
                    text = str(directive.get("text") or "").strip()
        if not text:
            return
        if not self.is_authorized(event.source):
            self._handle_unauthorized(event.source)
            return

        session = self._get_session(event.source)
        if session.pending is not None and self._answer_pending(session, text):
            return

        name, _args = split_command(text)
        if name in ("approve", "deny"):
            self.reply(event.source, "Nothing is waiting for approval.")
            return
        if name:
            definition = resolve_command(name)
            if session.busy and (definition is None or definition.busy_policy != BUSY_ALLOW):
                self.reply(event.source, f"/{name} has to wait: I am still working. Send /stop to interrupt.")
                return
            result = session.chat.run_slash(text)
            if result.action == ACTION_NEW:
                self.session_map.set(session.key, session.chat.session_id, event.source)
            if result.action != ACTION_SUBMIT:
                self.reply(event.source, result.text)
                return
            text = result.text  # a skill command: run it as a turn
        self._submit(session, text)

    def _answer_pending(self, session: GatewaySession, text: str) -> bool:
        pending = session.pending
        assert pending is not None
        if pending.kind == "approval":
            words = text.lower().lstrip("/").split()
            word = words[1] if len(words) > 1 and words[0] == "approve" else (words[0] if words else "")
            choice = _APPROVAL_WORDS.get(word)
            if choice is None:
                self.reply(session.source, "Please answer /approve, /approve session, /approve always, or /deny.")
                return True
            pending.answer = choice
        else:
            pending.answer = pending.choices[int(text) - 1] if text.isdigit() and 1 <= int(text) <= len(pending.choices) else text
        pending.answered.set()
        return True

    def _submit(self, session: GatewaySession, text: str) -> None:
        mode = str(get_path(self.config, "display.busy_input_mode", "interrupt"))
        with session.lock:
            if session.busy:
                if mode == "steer":
                    session.chat.steer(text)
                    return
                session.queue.append(text)
                if mode == "interrupt":
                    session.chat.interrupt()
                return
            session.queue.append(text)
            session.worker = start_thread(self._drain, session, name=f"clite-gw-{session.key}")

    def _drain(self, session: GatewaySession) -> None:
        merge_bursts = str(get_path(self.config, "display.busy_input_mode", "interrupt")) == "interrupt"
        while True:
            with session.lock:
                if not session.queue:
                    session.worker = None
                    return
                if merge_bursts:
                    # Several messages sent in quick succession are one thought: answer them together.
                    text = "\n\n".join(session.queue)
                    session.queue.clear()
                else:
                    text = session.queue.pop(0)
            adapter = self.adapters.get(session.source.platform)
            if adapter is not None:
                adapter.send_typing(session.source.chat_id, thread_id=session.source.thread_id)
            try:
                result = session.chat.submit(text)
            except Exception as exc:  # noqa: BLE001
                logger.exception("gateway turn failed for %s", session.key)
                self.reply(session.source, f"Something went wrong: {type(exc).__name__}: {exc}")
                continue
            session.last_used = time.monotonic()
            if result.interrupted:
                continue  # the user moved on; whatever interrupted this turn runs next
            self.reply(session.source, result.final_response or "(no response)")
