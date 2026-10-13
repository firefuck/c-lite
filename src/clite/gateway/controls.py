"""Inline button controls the runner sends: the ``/model`` picker and the approval prompt.

This module only draws them: the picker's state, the button rows and their labels, and the
callback data a button carries. Who may press a button and what a press changes is policy, and
stays with the runner: ``model_picker.py`` for the picker, ``questions.py`` for approvals. An
adapter that can show buttons says so with ``can_send_buttons`` and routes a press whose data
starts with one of the prefixes below back to the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clite.gateway.event import SessionSource

Keyboard = list[list[dict[str, str]]]

MODEL_PICKER_PREFIX = "mp"
APPROVAL_PREFIX = "ap"
CALLBACK_PREFIXES = (f"{MODEL_PICKER_PREFIX}:", f"{APPROVAL_PREFIX}:")

APPROVAL_BUTTONS = (
    ("Approve once", "once"),
    ("Approve for session", "session"),
    ("Always approve", "always"),
    ("Deny", "deny"),
)
_PAGE_SIZE = 8


@dataclass
class ModelPicker:
    """A ``/model`` picker owned by one authorized gateway session."""

    key: str
    session_key: str
    source: SessionSource
    providers: list[str]
    provider: str | None = None
    models: list[str] = field(default_factory=list)
    page: int = 0


def button_label(text: str, *, current: bool, max_bytes: int | None) -> str:
    """``text`` marked when ``current``, shortened with an ellipsis to fit ``max_bytes`` of
    UTF-8 without splitting a character. ``None`` means the platform sets no limit."""
    prefix = "✓ " if current else ""
    if max_bytes is not None:
        budget = max_bytes - len(prefix.encode("utf-8"))
        encoded = text.encode("utf-8")
        if len(encoded) > budget:
            encoded = encoded[: max(0, budget - len("…".encode()))]
            while encoded and (encoded[-1] & 0xC0) == 0x80:
                encoded = encoded[:-1]
            text = encoded.decode("utf-8", errors="ignore") + "…"
    return prefix + text


def model_picker_view(
    picker: ModelPicker, *, current_provider: str, current_model: str, label_bytes: int | None
) -> tuple[str, Keyboard]:
    """The picker's message text and buttons for its current page. Clamps ``picker.page``."""
    selecting_provider = picker.provider is None
    choices = picker.providers if selecting_provider else picker.models
    total_pages = max(1, (len(choices) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    picker.page = min(max(picker.page, 0), total_pages - 1)
    start = picker.page * _PAGE_SIZE
    data = f"{MODEL_PICKER_PREFIX}:{picker.key}"

    buttons = []
    for index, choice in enumerate(choices[start : start + _PAGE_SIZE], start=start):
        if selecting_provider:
            current, action = choice == current_provider, "provider"
        else:
            current, action = picker.provider == current_provider and choice == current_model, "select"
        label = button_label(choice, current=current, max_bytes=label_bytes)
        buttons.append({"text": label, "callback_data": f"{data}:{action}:{index}"})
    rows: Keyboard = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]

    if total_pages > 1:
        navigation: list[dict[str, str]] = []
        if picker.page:
            navigation.append({"text": "◀ Prev", "callback_data": f"{data}:page:{picker.page - 1}"})
        navigation.append({"text": f"{picker.page + 1}/{total_pages}", "callback_data": f"{data}:noop"})
        if picker.page < total_pages - 1:
            navigation.append({"text": "Next ▶", "callback_data": f"{data}:page:{picker.page + 1}"})
        rows.append(navigation)
    if not selecting_provider:
        rows.append([{"text": "◀ Back", "callback_data": f"{data}:back:0"}])
    rows.append([{"text": "Cancel", "callback_data": f"{data}:cancel"}])

    position = f"({picker.page + 1}/{total_pages})"
    if selecting_provider:
        text = f"Model: {current_model}\nChoose a provider {position}."
    else:
        text = f"Provider: {picker.provider}\nChoose a model {position}."
    return text, rows


def approval_keyboard(key: str) -> Keyboard:
    """Two rows of two buttons, one per approval choice, bound to the prompt ``key``."""
    buttons = [
        {"text": label, "callback_data": f"{APPROVAL_PREFIX}:{key}:{choice}"}
        for label, choice in APPROVAL_BUTTONS
    ]
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
