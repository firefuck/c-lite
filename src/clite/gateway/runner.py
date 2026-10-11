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
from clite.gateway import media
from clite.gateway.event import CHAT_DM, MessageEvent, SessionSource
from clite.gateway.media import MediaError
from clite.gateway.media import store as media_store
from clite.gateway.pairing import PairingStore
from clite.gateway.platforms.base import PLATFORMS, BasePlatformAdapter, split_message
from clite.gateway.session import HomeChannels, SessionMap, build_session_key
from clite.gateway.stream import ProgressReporter, StreamSender, tool_line, tool_message
from clite.plugins.hooks import has_hook, invoke_hook
from clite.plugins.manager import ensure_plugins_loaded
from clite.runtime.commands import BUSY_ALLOW, resolve_command, split_command
from clite.runtime.session import ACTION_NEW, ACTION_SUBMIT, BUSY_INTERRUPT, ChatSession, Turn, TurnQueue
from clite.tools import speech

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


_APPROVAL_WORDS = {
    "approve": "once",
    "yes": "once",
    "y": "once",
    "ok": "once",
    "once": "once",
    "session": "session",
    "always": "always",
    "deny": "deny",
    "no": "deny",
    "n": "deny",
}


@dataclass
class _Pending:
    """A question the agent asked that the next message from this chat answers."""

    kind: str  # "approval" | "clarify"
    choices: list[str] = field(default_factory=list)
    answered: threading.Event = field(default_factory=threading.Event)
    answer: str = ""


@dataclass
class _ModelPicker:
    """A Telegram model picker owned by one authorized gateway session."""

    key: str
    session_key: str
    source: SessionSource
    providers: list[str]
    provider: str | None = None
    models: list[str] = field(default_factory=list)
    page: int = 0


@dataclass
class GatewaySession:
    key: str
    source: SessionSource
    chat: ChatSession
    last_used: float = field(default_factory=time.monotonic)
    turns: TurnQueue | None = None  # set by the runner; owns the queue, the worker and the policy
    pending: _Pending | None = None

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
        self._model_pickers: dict[str, _ModelPicker] = {}
        self._lock = threading.RLock()
        self._scheduler: Any = None
        self.running = False
        self.accepting = True

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def start(self, *, with_cron: bool = True) -> list[str]:
        """Connect every enabled platform. Returns the names that started."""
        import clite.gateway.platforms.discord  # noqa: F401
        import clite.gateway.platforms.local  # noqa: F401 - registers the built-in adapters
        import clite.gateway.platforms.slack  # noqa: F401
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
            except Exception:  # noqa: BLE001
                logger.debug("disconnect failed for %s", adapter.name, exc_info=True)
        self.adapters.clear()

    def _close_session(self, session: GatewaySession, reason: str) -> None:
        if session.pending is not None:
            session.pending.answered.set()
        session.chat.interrupt()
        if session.turns is not None:
            session.turns.join(timeout=5)
        session.chat.close(reason)
        media.cleanup_media(session.key)  # the files belong to this conversation only

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

    def send_to(self, target: str, text: str, *, origin: dict[str, Any] | None = None) -> str:
        """Send ``text`` to ``target`` from the agent, enforcing the destination allowlist.

        ``target`` is a platform name (its home channel) or ``platform:chat``. Returns a short
        description of where the message went. Raises :class:`CliteError` when the platform is
        not connected or the destination is not allowed, naming what to change.
        """
        text = text.strip()
        if not text:
            raise CliteError("the message text is empty; nothing was sent")
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
        if platform not in self.adapters:
            raise CliteError(f"platform {platform!r} is not connected; connect it in gateway.platforms first")
        destination = f"{platform}:{chat_id}"
        if destination not in self._allowed_send_targets(origin):
            raise CliteError(
                f"destination {destination!r} is not allowed; add it to gateway.send_targets "
                f"or run /sethome in that chat"
            )
        self.reply(SessionSource(platform=platform, chat_id=chat_id), text)
        logger.info("send_message delivered to %s (%d chars)", destination, len(text))
        return destination

    def send_file_to(
        self, target: str, path: str, *, caption: str = "", origin: dict[str, Any] | None = None
    ) -> str:
        """Send a local file to ``target``, under the same destination rules as ``send_to``."""
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
        result = adapter.send_file(chat_id, path, caption=caption)
        if not result.success:
            raise CliteError(f"could not send {path}: {result.error or 'the platform refused it'}")
        logger.info("send_file delivered %s to %s", path, destination)
        return destination

    # ── Telegram model picker ────────────────────────────────────────────────────────────

    @staticmethod
    def _model_picker_label(model: str, *, current: bool) -> str:
        """A Telegram-safe label: Bot API button text is limited to 64 UTF-8 bytes."""
        prefix = "✓ " if current else ""
        budget = 64 - len(prefix.encode("utf-8"))
        encoded = model.encode("utf-8")
        if len(encoded) > budget:
            encoded = encoded[: max(0, budget - len("…".encode()))]
            while encoded and (encoded[-1] & 0xC0) == 0x80:
                encoded = encoded[:-1]
            model = encoded.decode("utf-8", errors="ignore") + "…"
        return prefix + model

    def _model_picker_view(self, picker: _ModelPicker, session: GatewaySession) -> tuple[str, list[list[dict[str, str]]]]:
        page_size = 8
        selecting_provider = picker.provider is None
        choices = picker.providers if selecting_provider else picker.models
        total_pages = max(1, (len(choices) + page_size - 1) // page_size)
        picker.page = min(max(picker.page, 0), total_pages - 1)
        start = picker.page * page_size
        rows: list[list[dict[str, str]]] = []
        if selecting_provider:
            buttons = [
                {
                    "text": self._model_picker_label(provider, current=provider == session.chat.agent.route.provider),
                    "callback_data": f"mp:{picker.key}:provider:{index}",
                }
                for index, provider in enumerate(choices[start : start + page_size], start=start)
            ]
        else:
            buttons = [
                {
                    "text": self._model_picker_label(
                        model,
                        current=picker.provider == session.chat.agent.route.provider
                        and model == session.chat.agent.route.model,
                    ),
                    "callback_data": f"mp:{picker.key}:select:{index}",
                }
                for index, model in enumerate(choices[start : start + page_size], start=start)
            ]
        rows.extend([buttons[index : index + 2] for index in range(0, len(buttons), 2)])
        if total_pages > 1:
            navigation: list[dict[str, str]] = []
            if picker.page:
                navigation.append({"text": "◀ Prev", "callback_data": f"mp:{picker.key}:page:{picker.page - 1}"})
            navigation.append({"text": f"{picker.page + 1}/{total_pages}", "callback_data": f"mp:{picker.key}:noop"})
            if picker.page < total_pages - 1:
                navigation.append({"text": "Next ▶", "callback_data": f"mp:{picker.key}:page:{picker.page + 1}"})
            rows.append(navigation)
        if not selecting_provider:
            rows.append([{"text": "◀ Back", "callback_data": f"mp:{picker.key}:back:0"}])
        rows.append([{"text": "Cancel", "callback_data": f"mp:{picker.key}:cancel"}])
        if selecting_provider:
            text = f"Model: {session.chat.agent.route.model}\nChoose a provider ({picker.page + 1}/{total_pages})."
        else:
            text = f"Provider: {picker.provider}\nChoose a model ({picker.page + 1}/{total_pages})."
        return text, rows

    def _send_telegram_model_picker(self, session: GatewaySession) -> bool:
        """Render the Telegram-only interactive form of an argument-less ``/model`` command."""
        adapter = self.adapters.get(session.source.platform)
        if adapter is None:
            return False
        from clite.providers.registry import list_providers

        current = session.chat.agent.route.provider
        providers = [profile.name for profile in list_providers(session.chat.agent.config) if profile.is_configured()]
        if current not in providers:
            providers.insert(0, current)
        providers = list(dict.fromkeys(providers))
        if not providers:
            return False
        import secrets

        key = secrets.token_hex(4)
        picker = _ModelPicker(key=key, session_key=session.key, source=session.source, providers=providers)
        text, keyboard = self._model_picker_view(picker, session)
        result = adapter.send_model_picker(session.source.chat_id, text, keyboard, thread_id=session.source.thread_id)
        if not result.success:
            logger.warning("could not send Telegram model picker: %s", result.error)
            return False
        self._model_pickers[key] = picker
        return True

    def handle_model_picker_callback(
        self, source: SessionSource, callback_id: str, data: str, message_id: str
    ) -> None:
        """Apply a Telegram picker tap after the runner's usual authorization and busy checks."""
        adapter = self.adapters.get(source.platform)
        if adapter is None:
            return
        parts = data.split(":", 3)
        if len(parts) not in (3, 4) or parts[0] != "mp":
            adapter.answer_callback(callback_id, "Invalid model selection.")
            return
        _prefix, key, action = parts[:3]
        raw_value = parts[3] if len(parts) == 4 else ""
        if not self.is_authorized(source):
            adapter.answer_callback(callback_id, "You are not authorized.")
            return
        picker = self._model_pickers.get(key)
        if picker is None or picker.source.user_id != source.user_id or picker.source.chat_id != source.chat_id:
            adapter.answer_callback(callback_id, "This model picker has expired. Run /model again.")
            return
        session = self._get_session(source)
        if session.key != picker.session_key:
            adapter.answer_callback(callback_id, "This model picker has expired. Run /model again.")
            return
        if session.busy:
            adapter.answer_callback(callback_id, "The model change has to wait until the current turn ends.")
            return
        if action == "noop":
            adapter.answer_callback(callback_id)
            return
        if action == "cancel":
            adapter.edit_model_picker(source.chat_id, message_id, "Model selection cancelled.", [])
            self._model_pickers.pop(key, None)
            adapter.answer_callback(callback_id)
            return
        if action == "page":
            try:
                picker.page = int(raw_value)
            except ValueError:
                adapter.answer_callback(callback_id, "Invalid model page.")
                return
            text, keyboard = self._model_picker_view(picker, session)
            adapter.edit_model_picker(source.chat_id, message_id, text, keyboard)
            adapter.answer_callback(callback_id)
            return
        if action == "back":
            picker.provider = None
            picker.models = []
            picker.page = 0
            text, keyboard = self._model_picker_view(picker, session)
            adapter.edit_model_picker(source.chat_id, message_id, text, keyboard)
            adapter.answer_callback(callback_id)
            return
        if action == "provider":
            try:
                provider = picker.providers[int(raw_value)]
            except (ValueError, IndexError):
                adapter.answer_callback(callback_id, "Invalid provider selection.")
                return
            from clite.providers.models import list_models

            route = session.chat.agent.route
            models = [model.id for model in list_models(provider, route=route if provider == route.provider else None)]
            if provider == route.provider and route.model not in models:
                models.insert(0, route.model)
            models = list(dict.fromkeys(models))
            if not models:
                adapter.answer_callback(callback_id, "That provider has no models available.")
                return
            picker.provider = provider
            picker.models = models
            picker.page = 0
            text, keyboard = self._model_picker_view(picker, session)
            adapter.edit_model_picker(source.chat_id, message_id, text, keyboard)
            adapter.answer_callback(callback_id)
            return
        if action != "select" or picker.provider is None:
            adapter.answer_callback(callback_id, "Invalid model selection.")
            return
        try:
            model = picker.models[int(raw_value)]
        except (ValueError, IndexError):
            adapter.answer_callback(callback_id, "Invalid model selection.")
            return
        result = session.chat.switch_model(f"{picker.provider}:{model}")
        text = f"Switched to {session.chat.agent.route.model}." if result.success else result.message
        adapter.edit_model_picker(source.chat_id, message_id, text, [])
        if result.success:
            self._model_pickers.pop(key, None)
            adapter.answer_callback(callback_id, "Model switched.")
        else:
            adapter.answer_callback(callback_id, "Could not switch model.")

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
            answer = ask(
                _Pending("approval"),
                (
                    f"This command needs your approval ({description}):\n\n{command}\n\n"
                    "Reply /approve (once), /approve session, /approve always, or /deny."
                ),
            )
            return answer or "deny"  # silence is a no

        def clarify(question: str, choices: list[str]) -> str:
            options = "".join(f"\n{number}. {choice}" for number, choice in enumerate(choices, start=1))
            return ask(_Pending("clarify", choices), f"{question}{options}")

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

    def _get_session(self, source: SessionSource) -> GatewaySession:
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
        except Exception:  # noqa: BLE001 - a bad message must not kill the adapter's receive loop
            logger.exception("gateway dispatch failed")
            self.reply(event.source, "Something went wrong handling that message. The error was logged.")

    def _dispatch(self, event: MessageEvent) -> None:
        if not self.accepting:
            return
        text = event.text.strip()
        if has_hook("pre_gateway_dispatch"):
            for directive in invoke_hook("pre_gateway_dispatch", event=event, gateway=self):
                if isinstance(directive, dict) and directive.get("action") == "skip":
                    return
                if isinstance(directive, dict) and directive.get("action") == "rewrite":
                    text = str(directive.get("text") or "").strip()
        if not text and not event.attachments:
            return
        if not self.is_authorized(event.source):
            self._handle_unauthorized(event.source)
            return

        session = self._get_session(event.source)
        if session.pending is not None and self._answer_pending(session, text):
            return

        if event.source.platform == "telegram" and text == "/model" and not session.busy and self._send_telegram_model_picker(session):
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
        images, notes, transcript = self._collect_attachments(session, event)
        if transcript:
            text = f"{text}\n\n{transcript}".strip() if text else transcript
        if notes:
            text = f"{text}\n\n{notes}".strip()
        if not text:
            return
        payload: dict[str, Any] = {"images": images} if images else {}
        if transcript:
            payload["voice"] = True  # the turn came from a recording; how to answer is a policy
        self._submit(session, text, payload=payload or None)

    def _collect_attachments(
        self, session: GatewaySession, event: MessageEvent
    ) -> tuple[list[str], str, str]:
        """Store the message's files and say what the model gets.

        An image becomes a content part; a voice message becomes the words the transcription
        provider heard; anything else is announced as a path the model can read with its file
        tools. A file over the size limit is refused with a message to the user -- it is never
        written, so nothing large lands on disk.
        """
        if not event.attachments:
            return [], "", ""
        max_bytes = int(get_path(self.config, "attachments.max_bytes", 5_000_000) or 5_000_000)
        adapter = self.adapters.get(event.source.platform)
        images: list[str] = []
        notes: list[str] = []
        spoken: list[str] = []
        for attachment in event.attachments:
            try:
                if attachment.data is None:
                    fetch = getattr(adapter, "fetch_attachment", None)
                    if fetch is None:
                        raise MediaError(
                            f"{attachment.describe()} cannot be downloaded by the {event.source.platform} adapter"
                        )
                    attachment.data = fetch(attachment, max_bytes=max_bytes)
                stored = media_store(attachment, session.key, max_bytes=max_bytes)
            except MediaError as exc:
                self.reply(event.source, f"I could not take that file: {exc}")
                continue
            if stored.kind == media.IMAGE:
                images.append(str(stored.path))
            elif stored.kind == media.AUDIO:
                words, note = self._hear(attachment, stored)
                if words:
                    spoken.append(words)
                else:
                    notes.append(note)
            else:
                notes.append(
                    f"The user attached {attachment.describe()}, saved at {stored.path}. "
                    "Read it with the file tools if it is relevant."
                )
        logger.info(
            "session %s took %d attachment(s): %d image(s), %d voice note(s)",
            session.key,
            len(event.attachments),
            len(images),
            len(spoken),
        )
        return images, "\n".join(notes), "\n\n".join(spoken)

    def _hear(self, attachment: media.Attachment, stored: media.StoredFile) -> tuple[str, str]:
        """The words in one voice message, or the note explaining why there are none.

        Nothing here fails the turn. Without a provider, over the length or size ceiling, or
        with a provider that errors, the model still gets the file and the user is told what
        happened -- a voice message that ends in silence is worse than one that ends in text.
        """
        limits = speech.speech_limits()
        try:
            size = stored.path.stat().st_size
        except OSError as exc:
            return "", f"{attachment.describe()} could not be read back: {exc}"
        # A recording this large is not worth paying a transcription API for. Only a
        # ``speech.max_bytes`` set below ``attachments.max_bytes`` can bite: the larger file is
        # already refused, and the user told so, before it ever reaches this point.
        if limits["max_bytes"] and size > limits["max_bytes"]:
            return "", (
                f"{attachment.describe()} is larger than the "
                f"{limits['max_bytes']:,.0f} byte limit for transcription, so it was not "
                f"transcribed; it is saved at {stored.path}."
            )
        seconds = speech.audio_seconds(stored.path)
        if limits["max_seconds"] and seconds is not None and seconds > limits["max_seconds"]:
            return "", (
                f"The user sent a voice message of {seconds:.0f} seconds, longer than the "
                f"{limits['max_seconds']:.0f} second limit, so it was not transcribed; it is "
                f"saved at {stored.path}."
            )
        provider = speech.get_transcription_provider()
        if provider is None:
            return "", (
                f"The user attached {attachment.describe()}, saved at {stored.path}. "
                "No speech-to-text provider is configured, so it was not transcribed; read it "
                "with the file tools if it is relevant."
            )
        settings = speech.transcription_settings()
        try:
            # A provider that answers anything but a string is as broken as one that raises, and
            # the turn has to survive both the same way.
            words = provider.transcribe(
                stored.path, model=settings["model"], language=settings["language"]
            ).strip()
        except Exception as exc:  # noqa: BLE001 - a broken provider is reported, not fatal
            logger.warning("transcription failed for %s", stored.path, exc_info=True)
            return "", (
                f"The user's voice message could not be transcribed "
                f"({type(exc).__name__}: {exc}); it is saved at {stored.path}."
            )
        if not words:
            return "", (
                f"The user's voice message held no speech that could be transcribed; it is "
                f"saved at {stored.path}."
            )
        return words, ""

    def _answer_pending(self, session: GatewaySession, text: str) -> bool:
        pending = session.pending
        assert pending is not None
        if pending.kind == "approval":
            words = text.lower().lstrip("/").split()
            word = words[1] if len(words) > 1 and words[0] == "approve" else (words[0] if words else "")
            choice = _APPROVAL_WORDS.get(word)
            if choice is None:
                self.reply(
                    session.source, "Please answer /approve, /approve session, /approve always, or /deny."
                )
                return True
            pending.answer = choice
        else:
            pending.answer = (
                pending.choices[int(text) - 1]
                if text.isdigit() and 1 <= int(text) <= len(pending.choices)
                else text
            )
        pending.answered.set()
        return True

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
        if adapter is not None:
            adapter.send_typing(session.source.chat_id, thread_id=session.source.thread_id)

        # A chat that can edit a sent message gets the answer as it is written and one status
        # message for tool activity. A chat that cannot keeps the old behaviour: typing
        # indicator, then the whole answer. ``message`` mode instead gets one separate chat
        # message per tool call, sent as the call starts.
        stream: StreamSender | None = None
        progress: ProgressReporter | None = None
        per_tool_message = session.chat.tool_progress == "message"
        if adapter is not None:
            chat_id, thread_id = session.source.chat_id, session.source.thread_id

            def send(text: str) -> str | None:
                result = adapter.send(chat_id, text, thread_id=thread_id)
                return result.message_id if result.success else None

            def edit(message_id: str, text: str) -> bool:
                return adapter.edit(chat_id, message_id, text)

            if adapter.can_edit():
                stream = StreamSender(send, edit, max_length=adapter.max_message_length)
                if session.chat.tool_progress not in ("off", "message"):
                    progress = ProgressReporter(send, edit)

        callbacks = session.chat.callbacks
        saved_on_delta, saved_on_tool, saved_on_start = (
            callbacks.on_delta,
            callbacks.on_tool_complete,
            callbacks.on_tool_start,
        )
        if stream is not None:
            callbacks.on_delta = stream.push
        if progress is not None:
            callbacks.on_tool_complete = lambda _call_id, name, _args, result, seconds: progress.note(
                tool_line(name, result, seconds)
            )
        if per_tool_message and stream is not None:

            def on_tool_start(_call_id: str, name: str, args: dict[str, Any]) -> None:
                send(tool_message(name, args))

            callbacks.on_tool_start = on_tool_start
        try:
            result = session.chat.submit(turn.text, images=(turn.payload or {}).get("images"))
        except Exception as exc:  # noqa: BLE001
            logger.exception("gateway turn failed for %s", session.key)
            self.reply(session.source, f"Something went wrong: {type(exc).__name__}: {exc}")
            return
        finally:
            callbacks.on_delta, callbacks.on_tool_complete, callbacks.on_tool_start = (
                saved_on_delta,
                saved_on_tool,
                saved_on_start,
            )
        session.last_used = time.monotonic()
        if stream is not None:
            # Settle whatever is already on screen. An interrupted turn has no final answer, so
            # it is left as the partial text the user already saw rather than a placeholder.
            stream.finish(None if result.interrupted else (result.final_response or "(no response)"))
        if result.interrupted:
            return  # the user moved on; whatever interrupted this turn runs next
        if stream is None:
            self.reply(session.source, result.final_response or "(no response)")
        self._speak_reply(
            session,
            adapter,
            result.final_response or "",
            voice=bool((turn.payload or {}).get("voice")),
        )

    def _speak_reply(
        self,
        session: GatewaySession,
        adapter: BasePlatformAdapter | None,
        text: str,
        *,
        voice: bool,
    ) -> None:
        """Answer a voice message with a voice message, on the platforms that asked for that.

        The text answer is already in the chat, so this is a second, listenable copy, and nothing
        depends on it: no provider, no policy for this platform, an answer too long to speak, or a
        provider that fails all leave the turn exactly as it was. A long answer is left as text
        rather than spoken in part, because half an answer read aloud is worse than one read.
        """
        if not voice or adapter is None or not text.strip():
            return
        if not speech.speaks_on(session.source.platform):
            return
        provider = speech.get_speech_provider()
        if provider is None:
            return
        max_chars = speech.speech_limits()["max_chars"]
        if max_chars and len(text) > max_chars:
            logger.info(
                "session %s: a %d character answer is too long to speak", session.key, len(text)
            )
            return
        settings = speech.speech_settings()
        directory = media.media_dir(session.key) / "spoken"
        target = directory / f"reply-{int(time.time() * 1000)}.{provider.output_format}"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            provider.synthesize(text, target, voice=settings["voice"], model=settings["model"])
            sent = adapter.send_file(
                session.source.chat_id, str(target), thread_id=session.source.thread_id
            )
        except Exception:  # noqa: BLE001 - the text answer already landed; the voice copy is a bonus
            logger.warning("session %s: could not speak the reply", session.key, exc_info=True)
            try:  # a half-written file is worse than none, but failing to remove it is not a turn
                target.unlink()
            except OSError:
                pass
            return
        if not sent.success:
            # ``send_file`` reports a refusal rather than raising, so it is checked here too.
            logger.warning(
                "session %s: %s refused the spoken reply: %s",
                session.key,
                session.source.platform,
                sent.error or "no reason given",
            )
            try:
                target.unlink()
            except OSError:
                pass
