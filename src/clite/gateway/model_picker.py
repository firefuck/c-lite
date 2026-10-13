"""The ``/model`` picker's policy: when buttons are offered, who may tap them, what a tap changes.

``controls.py`` draws the picker; this module decides. An argument-less ``/model`` on a platform
that can show buttons gets a picker bound to the session that asked. Every tap is checked again
as a message would be (the tapper is authorized, owns the picker, is in its chat, and the session
is idle) before it pages, goes back, cancels, picks a provider, or switches the session's model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from clite.gateway.controls import MODEL_PICKER_PREFIX, Keyboard, ModelPicker, model_picker_view
from clite.gateway.event import SessionSource
from clite.gateway.platforms.base import BasePlatformAdapter

if TYPE_CHECKING:
    from clite.gateway.runner import GatewayRunner, GatewaySession

logger = logging.getLogger("clite.gateway")


@dataclass
class _PickerTap:
    """One tap on a model picker button, with what is needed to answer it."""

    adapter: BasePlatformAdapter
    source: SessionSource
    callback_id: str
    message_id: str
    value: str


class ModelPickerFlow:
    """The open ``/model`` pickers of one runner, and what a tap on one of them does.

    Part of the runner, kept apart for readability: it reads the runner's adapters and routes a
    tap to its session the way the runner routes a message.
    """

    def __init__(self, runner: GatewayRunner) -> None:
        self._runner = runner
        self._pickers: dict[str, ModelPicker] = {}

    def offer(self, session: GatewaySession) -> bool:
        """The button form of an argument-less ``/model``, on platforms that can show buttons."""
        adapter = self._runner.adapters.get(session.source.platform)
        if adapter is None or not adapter.can_send_buttons():
            return False
        from clite.providers.registry import list_providers

        current = session.chat.agent.route.provider
        providers = [
            profile.name for profile in list_providers(session.chat.agent.config) if profile.is_configured()
        ]
        if current not in providers:
            providers.insert(0, current)
        providers = list(dict.fromkeys(providers))
        if not providers:
            return False
        import secrets

        key = secrets.token_hex(4)
        picker = ModelPicker(key=key, session_key=session.key, source=session.source, providers=providers)
        text, keyboard = self._view(picker, session)
        result = adapter.send_model_picker(
            session.source.chat_id, text, keyboard, thread_id=session.source.thread_id
        )
        if not result.success:
            logger.warning("could not send the model picker: %s", result.error)
            return False
        self._pickers[key] = picker
        return True

    def handle_callback(self, source: SessionSource, callback_id: str, data: str, message_id: str) -> None:
        """Apply a model picker tap after the runner's usual authorization and busy checks."""
        adapter = self._runner.adapters.get(source.platform)
        if adapter is None:
            return
        parts = data.split(":", 3)
        if len(parts) not in (3, 4) or parts[0] != MODEL_PICKER_PREFIX:
            adapter.answer_callback(callback_id, "Invalid model selection.")
            return
        _prefix, key, action = parts[:3]
        tap = _PickerTap(
            adapter=adapter,
            source=source,
            callback_id=callback_id,
            message_id=message_id,
            value=parts[3] if len(parts) == 4 else "",
        )
        found = self._picker_for_tap(tap, key)
        if found is None:
            return
        picker, session = found
        if action == "noop":
            adapter.answer_callback(callback_id)
            return
        handler = {
            "cancel": self._cancel,
            "page": self._page,
            "back": self._back,
            "provider": self._provider,
            "select": self._select,
        }.get(action)
        if handler is None:
            adapter.answer_callback(callback_id, "Invalid model selection.")
            return
        handler(tap, picker, session)

    def _view(self, picker: ModelPicker, session: GatewaySession) -> tuple[str, Keyboard]:
        adapter = self._runner.adapters.get(picker.source.platform)
        route = session.chat.agent.route
        return model_picker_view(
            picker,
            current_provider=route.provider,
            current_model=route.model,
            label_bytes=adapter.max_button_label_bytes if adapter is not None else None,
        )

    def _picker_for_tap(self, tap: _PickerTap, key: str) -> tuple[ModelPicker, GatewaySession] | None:
        """The picker a tap belongs to, once the tapper may use it and the session is idle."""
        adapter, callback_id = tap.adapter, tap.callback_id
        if not self._runner.is_authorized(tap.source):
            adapter.answer_callback(callback_id, "You are not authorized.")
            return None
        picker = self._pickers.get(key)
        if (
            picker is None
            or picker.source.user_id != tap.source.user_id
            or picker.source.chat_id != tap.source.chat_id
        ):
            adapter.answer_callback(callback_id, "This model picker has expired. Run /model again.")
            return None
        session = self._runner.session_for(tap.source)
        if session.key != picker.session_key:
            adapter.answer_callback(callback_id, "This model picker has expired. Run /model again.")
            return None
        if session.busy:
            adapter.answer_callback(callback_id, "The model change has to wait until the current turn ends.")
            return None
        return picker, session

    def _redraw(self, tap: _PickerTap, picker: ModelPicker, session: GatewaySession) -> None:
        text, keyboard = self._view(picker, session)
        tap.adapter.edit_model_picker(tap.source.chat_id, tap.message_id, text, keyboard)
        tap.adapter.answer_callback(tap.callback_id)

    def _cancel(self, tap: _PickerTap, picker: ModelPicker, session: GatewaySession) -> None:
        tap.adapter.edit_model_picker(tap.source.chat_id, tap.message_id, "Model selection cancelled.", [])
        self._pickers.pop(picker.key, None)
        tap.adapter.answer_callback(tap.callback_id)

    def _page(self, tap: _PickerTap, picker: ModelPicker, session: GatewaySession) -> None:
        try:
            picker.page = int(tap.value)
        except ValueError:
            tap.adapter.answer_callback(tap.callback_id, "Invalid model page.")
            return
        self._redraw(tap, picker, session)

    def _back(self, tap: _PickerTap, picker: ModelPicker, session: GatewaySession) -> None:
        picker.provider = None
        picker.models = []
        picker.page = 0
        self._redraw(tap, picker, session)

    def _provider(self, tap: _PickerTap, picker: ModelPicker, session: GatewaySession) -> None:
        try:
            provider = picker.providers[int(tap.value)]
        except (ValueError, IndexError):
            tap.adapter.answer_callback(tap.callback_id, "Invalid provider selection.")
            return
        from clite.providers.models import list_models

        route = session.chat.agent.route
        models = [
            model.id for model in list_models(provider, route=route if provider == route.provider else None)
        ]
        if provider == route.provider and route.model not in models:
            models.insert(0, route.model)
        models = list(dict.fromkeys(models))
        if not models:
            tap.adapter.answer_callback(tap.callback_id, "That provider has no models available.")
            return
        picker.provider = provider
        picker.models = models
        picker.page = 0
        self._redraw(tap, picker, session)

    def _select(self, tap: _PickerTap, picker: ModelPicker, session: GatewaySession) -> None:
        if picker.provider is None:
            tap.adapter.answer_callback(tap.callback_id, "Invalid model selection.")
            return
        try:
            model = picker.models[int(tap.value)]
        except (ValueError, IndexError):
            tap.adapter.answer_callback(tap.callback_id, "Invalid model selection.")
            return
        result = session.chat.switch_model(f"{picker.provider}:{model}")
        text = f"Switched to {session.chat.agent.route.model}." if result.success else result.message
        tap.adapter.edit_model_picker(tap.source.chat_id, tap.message_id, text, [])
        if result.success:
            self._pickers.pop(picker.key, None)
            tap.adapter.answer_callback(tap.callback_id, "Model switched.")
        else:
            tap.adapter.answer_callback(tap.callback_id, "Could not switch model.")
