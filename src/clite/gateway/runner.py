"""``GatewayRunner``: the policy layer between chat platforms and the agent.

For every inbound message, in this order:

1. plugins may drop or rewrite it (``pre_gateway_dispatch``);
2. authorization: platform allowlist, ``gateway.allow_all_users``, paired users; an unknown
   user in a direct message is offered a pairing code, anywhere else they are ignored;
3. the message is routed to its session (see ``gateway.session``);
4. if that session is waiting for an answer (an approval or a question), the message is the
   answer;
5. a slash command is run; anything else becomes the next turn, subject to the busy policy.

A voice message is transcribed on the way in, so the turn sees words; where a platform asked
for it, the answer to a voice message is spoken on the way out.

A turn runs on its own thread, so one long task never blocks another chat.

This module keeps that order, the sessions and the turns. The steps that have rules of their own
sit beside it and are called from here: ``questions.py`` (approvals and clarifying questions),
``model_picker.py`` (the ``/model`` buttons), ``attachments.py`` and ``voice.py`` (files and
speech), and ``live_reply.py`` (the typing indicator and the answer as it is written).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from clite.agent import AgentCallbacks
from clite.core.config import get_path, load_config
from clite.core.errors import CliteError
from clite.core.threads import start_thread
from clite.gateway import media
from clite.gateway.attachments import collect_attachments
from clite.gateway.event import CHAT_DM, MessageEvent, SessionSource
from clite.gateway.live_reply import LiveReply, start_typing
from clite.gateway.model_picker import ModelPickerFlow
from clite.gateway.pairing import PairingStore
from clite.gateway.platforms.base import PLATFORMS, BasePlatformAdapter, split_message
from clite.gateway.questions import Pending, PendingQuestions
from clite.gateway.session import HomeChannels, SessionMap, build_session_key
from clite.gateway.voice import speak_reply
from clite.plugins.hooks import has_hook, invoke_hook
from clite.plugins.manager import ensure_plugins_loaded
from clite.runtime.commands import BUSY_ALLOW, resolve_command, split_command
from clite.runtime.session import (
    ACTION_NEW,
    ACTION_RESTART,
    ACTION_SUBMIT,
    BUSY_INTERRUPT,
    ChatSession,
    Turn,
    TurnQueue,
)

logger = logging.getLogger("clite.gateway")

# Runners started in this process. The `send_message` tool reaches the live gateway through
# this, so it can reach only platforms that are actually connected. Guarded by a lock and
# cleared on stop, so a stopped runner is never handed to the model.
_ACTIVE_RUNNERS: list[GatewayRunner] = []
_ACTIVE_LOCK = threading.Lock()


def active_runner() -> GatewayRunner | None:
    """The first running gateway in this process, or ``None`` when there is none."""
    with _ACTIVE_LOCK:
        for runner in _ACTIVE_RUNNERS:
            if runner.running:
                return runner
    return None


def reset_active_runners() -> None:
    """Forget every runner in this process. Called between tests so one cannot leak."""
    with _ACTIVE_LOCK:
        _ACTIVE_RUNNERS.clear()


@dataclass
class GatewaySession:
    key: str
    source: SessionSource
    chat: ChatSession
    last_used: float = field(default_factory=time.monotonic)
    turns: TurnQueue | None = None  # set by the runner; owns the queue, the worker and the policy
    pending: Pending | None = None

    @property
    def busy(self) -> bool:
        return self.chat.busy if self.turns is None else self.turns.busy


class GatewayRunner:
    def __init__(self, config: dict[str, Any] | None = None, *, client_factory: Any = None) -> None:
        self.config = config if config is not None else load_config()
        self.client_factory = client_factory  # tests inject a scripted model client
        self.adapters: dict[str, BasePlatformAdapter] = {}
        self.sessions: dict[str, GatewaySession] = {}
        self.session_map = SessionMap()
        self.home_channels = HomeChannels(self.config)
        self.now_fn = time.time
        self.pairing = PairingStore()
        self.on_restart: Any = None
        self._lock = threading.RLock()
        self._model_picker = ModelPickerFlow(self)
        self._questions = PendingQuestions(self, lock=self._lock)
        self._scheduler: Any = None
        self.running = False
        self.accepting = True

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def start(self, *, with_cron: bool = True) -> list[str]:
        """Connect every enabled platform. Returns the names that started."""
        import clite.gateway.platforms.discord
        import clite.gateway.platforms.local  # registers the built-in adapters
        import clite.gateway.platforms.slack
        import clite.gateway.platforms.telegram  # noqa: F401 - importing registers the adapter

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
        self.accepting = True
        with _ACTIVE_LOCK:
            if self not in _ACTIVE_RUNNERS:
                _ACTIVE_RUNNERS.append(self)
        if with_cron and get_path(self.config, "cron.enabled", True):
            from clite.cron.scheduler import Scheduler

            self._scheduler = Scheduler(
                deliver=self.deliver, client=self.client_factory() if self.client_factory else None
            )
            self._scheduler.start()
        return started

    def begin_drain(self) -> None:
        """Stop accepting inbound work while existing turns finish."""
        self.accepting = False

    def has_active_turns(self) -> bool:
        """Whether a turn is running or queued in any gateway session."""
        with self._lock:
            return any(session.busy for session in self.sessions.values())

    def notify_interrupted_turns(self) -> None:
        """Tell chats whose turns exceeded the service drain deadline."""
        with self._lock:
            sessions = [session for session in self.sessions.values() if session.busy]
        for session in sessions:
            self.reply(session.source, "The gateway is stopping; this turn was interrupted.")

    def stop(self) -> None:
        self.accepting = False
        self.running = False
        with _ACTIVE_LOCK:
            if self in _ACTIVE_RUNNERS:
                _ACTIVE_RUNNERS.remove(self)
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
            except Exception:
                logger.debug("disconnect failed for %s", adapter.name, exc_info=True)
        self.adapters.clear()

    def request_restart(self) -> None:
        """Trigger a restart of the gateway process or service."""
        if callable(self.on_restart):
            self.on_restart()
        else:
            # Fallback when running standalone without supervisor callback
            def _exit() -> None:
                time.sleep(0.5)
                import os
                import signal

                try:
                    os.kill(os.getpid(), signal.SIGTERM)
                except Exception:  # noqa: BLE001 - if signalling fails, exit hard so the supervisor restarts us
                    os._exit(75)

            start_thread(_exit, name="clite-gw-restart")

    def _close_session(self, session: GatewaySession, reason: str) -> None:
        if session.pending is not None:
            session.pending.answered.set()
        session.chat.interrupt()
        if session.turns is not None:
            session.turns.join(timeout=5)
        session.chat.close(reason)
        media.cleanup_media(session.key)  # the files belong to this conversation only

    # ── sending ──────────────────────────────────────────────────────────────────────────

    def reply(self, source: SessionSource, text: str, *, reply_to: str | None = None) -> None:
        adapter = self.adapters.get(source.platform)
        if adapter is None or not text.strip():
            return
        for index, chunk in enumerate(split_message(text, adapter.max_message_length)):
            result = adapter.send(
                source.chat_id,
                chunk,
                reply_to=reply_to if index == 0 else None,
                thread_id=source.thread_id,
            )
            if not result.success:
                logger.warning("send to %s:%s failed: %s", source.platform, source.chat_id, result.error)
                return

    def deliver(self, job: dict[str, Any], text: str) -> None:
        """Deliver a cron job's output: to where the job was created, or to ``platform:chat``."""
        target = str(job.get("deliver") or "local")
        origin = job.get("origin") or {}
        if target == "origin":
            platform, chat_id, thread_id = (
                origin.get("platform"),
                origin.get("chat_id"),
                origin.get("thread_id"),
            )
        elif ":" in target:
            platform, _, chat_id = target.partition(":")
            thread_id = None
        else:
            # Home channel for platform: "deliver: telegram"
            platform = target.strip()
            thread_id = None
            chat_id = self.home_channels.get(platform)
            if not chat_id:
                raise RuntimeError(
                    f"no home channel configured for {platform!r}; run /sethome in the chat first"
                )
        if not platform or not chat_id or platform not in self.adapters:
            raise RuntimeError(
                f"cannot deliver to {target!r}: the platform is not connected or the chat is unknown"
            )
        label = job.get("name") or f"job {job['id']}"
        self.reply(
            SessionSource(platform=platform, chat_id=str(chat_id), thread_id=thread_id), f"[{label}]\n{text}"
        )

    def _allowed_send_targets(self, origin: dict[str, Any] | None) -> set[str]:
        """The chat destinations the agent may send to: its origin, each home channel, and
        every entry in ``gateway.send_targets``. Anything else is refused."""
        allowed: set[str] = set()
        if origin and origin.get("platform") and origin.get("chat_id"):
            allowed.add(f"{origin['platform']}:{origin['chat_id']}")
        for platform in self.adapters:
            home = self.home_channels.get(platform)
            if home:
                allowed.add(f"{platform}:{home}")
        for entry in get_path(self.config, "gateway.send_targets", []) or []:
            if isinstance(entry, str) and entry.strip():
                allowed.add(entry.strip())
        return allowed

    def _allowed_destination(
        self, target: str, origin: dict[str, Any] | None
    ) -> tuple[BasePlatformAdapter, str, str]:
        """The adapter, platform and chat that ``target`` names, once the agent may send there.

        ``target`` is a platform name (its home channel) or ``platform:chat``. Raises
        :class:`CliteError` when the platform is not connected or the destination is not
        allowed, naming what to change.
        """
        raw = target.strip()
        if not raw:
            raise CliteError("a target is required: a platform name or 'platform:chat id'")
        if ":" in raw:
            platform, _, chat_id = raw.partition(":")
            chat_id = chat_id.strip()
        else:
            platform, chat_id = raw, self.home_channels.get(raw) or ""
        if not platform or not chat_id:
            raise CliteError(
                f"target {target!r} has no chat id and no home channel is set; use "
                f"'platform:chat id' or run /sethome in that chat first"
            )
        adapter = self.adapters.get(platform)
        if adapter is None:
            raise CliteError(f"platform {platform!r} is not connected; connect it in gateway.platforms first")
        destination = f"{platform}:{chat_id}"
        if destination not in self._allowed_send_targets(origin):
            raise CliteError(
                f"destination {destination!r} is not allowed; add it to gateway.send_targets "
                f"or run /sethome in that chat"
            )
        return adapter, platform, chat_id

    def send_to(self, target: str, text: str, *, origin: dict[str, Any] | None = None) -> str:
        """Send ``text`` to ``target`` from the agent, enforcing the destination allowlist.

        ``target`` is a platform name (its home channel) or ``platform:chat``. Returns a short
        description of where the message went. Raises :class:`CliteError` when the platform is
        not connected or the destination is not allowed, naming what to change.
        """
        text = text.strip()
        if not text:
            raise CliteError("the message text is empty; nothing was sent")
        _adapter, platform, chat_id = self._allowed_destination(target, origin)
        destination = f"{platform}:{chat_id}"
        self.reply(SessionSource(platform=platform, chat_id=chat_id), text)
        logger.info("send_message delivered to %s (%d chars)", destination, len(text))
        return destination

    def send_file_to(
        self, target: str, path: str, *, caption: str = "", origin: dict[str, Any] | None = None
    ) -> str:
        """Send a local file to ``target``, under the same destination rules as ``send_to``."""
        adapter, platform, chat_id = self._allowed_destination(target, origin)
        destination = f"{platform}:{chat_id}"
        result = adapter.send_file(chat_id, path, caption=caption)
        if not result.success:
            raise CliteError(f"could not send {path}: {result.error or 'the platform refused it'}")
        logger.info("send_file delivered %s to %s", path, destination)
        return destination

    # ── button presses ───────────────────────────────────────────────────────────────────
    # The entry points adapters with buttons call, kept here so an adapter only knows the
    # runner; what a press may do is decided in `model_picker.py` and `questions.py`.

    def handle_model_picker_callback(
        self, source: SessionSource, callback_id: str, data: str, message_id: str
    ) -> None:
        """Apply a model picker tap after the runner's usual authorization and busy checks."""
        self._model_picker.handle_callback(source, callback_id, data, message_id)

    def handle_approval_callback(
        self, source: SessionSource, callback_id: str, data: str, message_id: str
    ) -> None:
        """Resolve an approval button only for its authorized owner and live pending session."""
        self._questions.handle_approval_callback(source, callback_id, data, message_id)

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
        self.reply(
            source,
            (
                "I do not know you yet. Ask the owner of this agent to approve you with:\n\n"
                f"clite gateway pair approve {source.platform} {code}\n\nThe code is valid for one hour."
            ),
        )

    # ── sessions ─────────────────────────────────────────────────────────────────────────

    def _callbacks(self, key: str, source: SessionSource) -> AgentCallbacks:
        timeout = float(get_path(self.config, "approvals.timeout", 300) or 300)

        def approve(*, command: str, description: str, pattern_keys: list[str]) -> str:
            return self._questions.approve(
                key, source, command=command, description=description, timeout=timeout
            )

        def clarify(question: str, choices: list[str]) -> str:
            return self._questions.clarify(key, source, question, choices, timeout=timeout)

        def on_status(kind: str, text: str) -> None:
            if kind in ("fallback", "compressed"):
                self.reply(source, f"[{text}]")

        return AgentCallbacks(approve=approve, clarify=clarify, on_status=on_status)

    def _should_reset_session(self, entry: dict[str, Any] | None, now: float) -> bool:
        if not entry:
            return False
        last_activity = float(entry.get("last_activity") or 0.0)
        if not last_activity:
            return False

        mode = str(get_path(self.config, "gateway.session_reset.mode", "none")).lower()
        if mode == "idle":
            idle_minutes = float(get_path(self.config, "gateway.session_reset.idle_minutes", 120))
            return (now - last_activity) >= (idle_minutes * 60.0)
        if mode == "daily":
            daily_hour = int(get_path(self.config, "gateway.session_reset.daily_hour", 4))
            import datetime

            dt_last = datetime.datetime.fromtimestamp(last_activity)
            dt_now = datetime.datetime.fromtimestamp(now)
            cutoff_today = dt_now.replace(hour=daily_hour, minute=0, second=0, microsecond=0)
            if dt_now >= cutoff_today:
                return dt_last < cutoff_today
            cutoff_yesterday = cutoff_today - datetime.timedelta(days=1)
            return dt_last < cutoff_yesterday
        return False

    def session_for(self, source: SessionSource) -> GatewaySession:
        """The session a message from ``source`` belongs to, resumed or started as needed."""
        key = build_session_key(
            source,
            group_sessions_per_user=bool(get_path(self.config, "gateway.group_sessions_per_user", True)),
        )
        now = self.now_fn()
        with self._lock:
            self._evict_idle()
            entry = self.session_map.get_entry(key)
            if self._should_reset_session(entry, now):
                if key in self.sessions:
                    self._close_session(self.sessions.pop(key), "reset_policy")
                self.session_map.reset(key)
                self.reply(
                    source,
                    "[Starting a new conversation per session reset policy. Use /resume to return to the previous session.]",
                )

            session = self.sessions.get(key)
            if session is None:
                chat = ChatSession(
                    platform=source.platform,
                    callbacks=self._callbacks(key, source),
                    session_id=self.session_map.get(key),
                    client=self.client_factory() if self.client_factory else None,
                    session_meta={
                        "session_key": key,
                        "user_id": source.user_id,
                        "chat_id": source.chat_id,
                        "chat_type": source.chat_type,
                        "thread_id": source.thread_id,
                        "display_name": source.user_name,
                        "origin": source.to_dict(),
                    },
                )
                session = self.sessions[key] = GatewaySession(
                    key,
                    source,
                    chat,
                    turns=TurnQueue(
                        chat,
                        lambda turn: self._run_turn(key, turn),
                        merge_bursts=self._merge_bursts(),
                        thread_name=f"clite-gw-{key}",
                    ),
                )
                self.session_map.set(key, chat.session_id, source, last_activity=now)
            else:
                self.session_map.update_activity(key, now)
            session.last_used = time.monotonic()
            return session

    def _evict_idle(self) -> None:
        ttl = float(get_path(self.config, "gateway.agent_cache_ttl_seconds", 3600) or 0)
        if not ttl:
            return
        now = time.monotonic()
        for key in [
            key
            for key, session in self.sessions.items()
            if now - session.last_used > ttl and not session.busy
        ]:
            # The conversation is not lost: the next message resumes it from the database.
            self._close_session(self.sessions.pop(key), "idle")

    # ── dispatch ─────────────────────────────────────────────────────────────────────────

    def dispatch(self, event: MessageEvent) -> None:
        """Handle one inbound message. Called from adapter threads; returns quickly."""
        try:
            self._dispatch(event)
        except CliteError as exc:
            self.reply(event.source, f"Error: {exc}")
        except Exception:  # a bad message must not kill the adapter's receive loop
            logger.exception("gateway dispatch failed")
            self.reply(event.source, "Something went wrong handling that message. The error was logged.")

    def _dispatch(self, event: MessageEvent) -> None:
        if not self.accepting:
            return
        text = self._apply_dispatch_hooks(event)
        if text is None or (not text and not event.attachments):
            return
        if not self.is_authorized(event.source):
            self._handle_unauthorized(event.source)
            return

        session = self.session_for(event.source)
        if session.pending is not None and self._questions.answer(session, text):
            return

        if text == "/model" and not session.busy and self._model_picker.offer(session):
            return

        if split_command(text)[0]:
            submitted = self._run_command(session, event, text)
            if submitted is None:
                return
            text = submitted  # a skill command: run it as a turn
        self._submit_message(session, event, text)

    def _apply_dispatch_hooks(self, event: MessageEvent) -> str | None:
        """The message text after plugins had their say; ``None`` when one dropped it."""
        text = event.text.strip()
        if not has_hook("pre_gateway_dispatch"):
            return text
        for directive in invoke_hook("pre_gateway_dispatch", event=event, gateway=self):
            if isinstance(directive, dict) and directive.get("action") == "skip":
                return None
            if isinstance(directive, dict) and directive.get("action") == "rewrite":
                text = str(directive.get("text") or "").strip()
        return text

    def _run_command(self, session: GatewaySession, event: MessageEvent, text: str) -> str | None:
        """Run a slash command. Returns the text to submit as a turn, or ``None`` when the
        command was answered (or refused) here."""
        name, _args = split_command(text)
        reply_to = event.reply_to or event.message_id
        if name in ("approve", "deny"):
            self.reply(event.source, "Nothing is waiting for approval.")
            return None
        definition = resolve_command(name)
        if session.busy:
            if definition is not None and definition.name == "new":
                session.chat.interrupt()
                if session.turns is not None:
                    session.turns.clear()
                self.reply(event.source, "Stopping running turn and resetting session…")
            elif definition is None or definition.busy_policy != BUSY_ALLOW:
                self.reply(event.source, f"/{name} has to wait: I am still working. Send /stop to interrupt.")
                return None
        result = session.chat.run_slash(text)
        if result.action == ACTION_NEW:
            self.session_map.set(session.key, session.chat.session_id, event.source)
        if result.action == ACTION_RESTART:
            self.reply(event.source, result.text, reply_to=reply_to)
            self.request_restart()
            return None
        if result.action != ACTION_SUBMIT:
            self.reply(event.source, result.text, reply_to=reply_to)
            return None
        return result.text

    def _submit_message(self, session: GatewaySession, event: MessageEvent, text: str) -> None:
        """Turn the message and its attachments into the next turn."""
        images, notes, transcript = collect_attachments(
            event,
            session.key,
            adapter=self.adapters.get(event.source.platform),
            config=self.config,
            reply=self.reply,
        )
        if transcript:
            text = f"{text}\n\n{transcript}".strip() if text else transcript
        if notes:
            text = f"{text}\n\n{notes}".strip()
        if not text:
            return
        payload: dict[str, Any] = {"images": images} if images else {}
        if transcript:
            payload["voice"] = True  # the turn came from a recording; how to answer is a policy
        payload["reply_to"] = event.reply_to or event.message_id
        self._submit(session, text, payload=payload)

    def _merge_bursts(self) -> bool:
        """Several messages sent in quick succession are one thought: answer them together.
        That only reads right in ``interrupt`` mode; ``queue`` mode keeps them apart."""
        return str(get_path(self.config, "display.busy_input_mode", "interrupt")) == BUSY_INTERRUPT

    def _submit(self, session: GatewaySession, text: str, *, payload: dict[str, Any] | None = None) -> None:
        assert session.turns is not None
        session.turns.submit(Turn(text=text, payload=payload))

    def _run_turn(self, key: str, turn: Turn) -> None:
        session = self.sessions.get(key)
        if session is None:  # the session was closed while this turn waited
            return
        adapter = self.adapters.get(session.source.platform)
        typing_keeper = (
            start_typing(adapter, session.source.chat_id, thread_id=session.source.thread_id)
            if adapter is not None
            else None
        )
        reply_to = str((turn.payload or {}).get("reply_to") or "") or None
        live = (
            LiveReply(
                adapter,
                session.source,
                reply_to=reply_to,
                typing_keeper=typing_keeper,
                tool_progress=session.chat.tool_progress,
            )
            if adapter is not None
            else None
        )
        stream = live.stream if live is not None else None
        try:
            with live.wired(session.chat.callbacks) if live is not None else contextlib.nullcontext():
                result = session.chat.submit(turn.text, images=(turn.payload or {}).get("images"))
        except Exception as exc:
            if typing_keeper is not None:
                typing_keeper.stop()
            logger.exception("gateway turn failed for %s", session.key)
            self.reply(
                session.source, f"Something went wrong: {type(exc).__name__}: {exc}", reply_to=reply_to
            )
            return
        finally:
            if typing_keeper is not None:
                typing_keeper.stop()
        session.last_used = time.monotonic()
        if stream is not None:
            # Settle whatever is already on screen. An interrupted turn has no final answer, so
            # it is left as the partial text the user already saw rather than a placeholder.
            stream.finish(None if result.interrupted else (result.final_response or "(no response)"))
        if result.interrupted:
            return  # the user moved on; whatever interrupted this turn runs next
        if stream is None:
            self.reply(session.source, result.final_response or "(no response)", reply_to=reply_to)
        speak_reply(
            session.source,
            session.key,
            adapter,
            result.final_response or "",
            voice=bool((turn.payload or {}).get("voice")),
        )
