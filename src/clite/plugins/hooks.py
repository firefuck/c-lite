"""Lifecycle hooks: the bus core fires and plugins subscribe to.

This module is a leaf: it imports nothing from the rest of ``clite`` except ``core``, so any
layer (tools, agent, gateway) can fire a hook without creating an import cycle.

Contracts:

* ``invoke_hook(name, **kwargs)`` returns the non-``None`` results in registration order.
* Kwargs are additive. A callback receives only the kwargs it names (or all of them if it
  takes ``**kwargs``), so core can add a kwarg without breaking an older plugin.
* One callback failing never affects the others or the caller. The exception is a policy
  hook (``FAIL_CLOSED_HOOKS``): a guard that raised or timed out made no decision, and "no
  decision" on a security check must mean *block*.
"""

from __future__ import annotations

import contextvars
import inspect
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from clite.core.constants import home_key

logger = logging.getLogger("clite.plugins.hooks")

VALID_HOOKS: frozenset[str] = frozenset(
    {
        # Tools. pre_tool_call may return {"action": "block", "message": ..} or
        # {"action": "modify", "args": {...}}; transform_* return a replacement string.
        "pre_tool_call",
        "post_tool_call",
        "transform_tool_result",
        "transform_terminal_output",
        # Model calls. pre_llm_call may return {"context": "..."} which is appended to the
        # current user message (never the system prompt: that would break the prompt cache).
        "pre_llm_call",
        "post_llm_call",
        "transform_llm_output",
        "pre_api_request",
        "post_api_request",
        "api_request_error",
        # Sessions.
        "on_session_start",
        "on_session_end",
        "on_session_reset",
        # Delegation.
        "subagent_start",
        "subagent_stop",
        # Approvals (observers only; use pre_tool_call to veto).
        "pre_approval_request",
        "post_approval_response",
        # Skills and gateway.
        "on_skill_lifecycle",
        "pre_gateway_dispatch",
    }
)

FAIL_CLOSED_HOOKS: frozenset[str] = frozenset({"pre_tool_call"})
# A plugin's prompt section is paid for on every request, so it is capped.
MAX_PROMPT_SECTION_CHARS = 2000
MAX_PROMPT_SECTIONS_TOTAL_CHARS = 8000
TIMEOUT_BLOCK_MESSAGE = "pre_tool_call plugin callback timed out or is still running"


@dataclass
class HookRegistration:
    name: str
    callback: Callable[..., Any]
    plugin: str = ""
    accepts_var_kwargs: bool = False
    params: frozenset[str] = field(default_factory=frozenset)


def _describe(callback: Callable[..., Any]) -> tuple[bool, frozenset[str]]:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return True, frozenset()
    var_kwargs = any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())
    names = frozenset(
        name for name, p in signature.parameters.items() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    )
    return var_kwargs, names


class HookBus:
    """Hook registrations for one home (one profile)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._hooks: dict[str, list[HookRegistration]] = {}
        self._sections: dict[str, tuple[str, Any]] = {}  # section id -> (plugin, text or callable)
        self.timeout: float | None = None  # seconds per callback; None = run inline, unbounded

    # ── system prompt sections ───────────────────────────────────────────────────────────

    def register_prompt_section(self, section_id: str, content: Any, *, plugin: str = "") -> None:
        """Add a block to the system prompt's volatile tier. ``content`` is a string or a
        zero-argument callable returning one; it is rendered once, when a session starts."""
        with self._lock:
            self._sections[section_id] = (plugin, content)

    def render_prompt_sections(self) -> list[str]:
        with self._lock:
            sections = list(self._sections.items())
        rendered: list[str] = []
        total = 0
        for section_id, (plugin, content) in sections:
            try:
                text = content() if callable(content) else content
            except Exception:  # noqa: BLE001
                logger.warning("prompt section %s from plugin %r failed", section_id, plugin, exc_info=True)
                continue
            text = str(text or "").strip()[:MAX_PROMPT_SECTION_CHARS]
            if text and total + len(text) <= MAX_PROMPT_SECTIONS_TOTAL_CHARS:
                rendered.append(text)
                total += len(text)
        return rendered

    def register(self, name: str, callback: Callable[..., Any], *, plugin: str = "") -> HookRegistration:
        if name not in VALID_HOOKS:
            raise ValueError(f"unknown hook {name!r}; valid hooks: {sorted(VALID_HOOKS)}")
        var_kwargs, params = _describe(callback)
        registration = HookRegistration(name, callback, plugin, var_kwargs, params)
        with self._lock:
            self._hooks.setdefault(name, []).append(registration)
        return registration

    def unregister(self, registration: HookRegistration) -> None:
        with self._lock:
            entries = self._hooks.get(registration.name, [])
            if registration in entries:
                entries.remove(registration)

    def unregister_plugin(self, plugin: str) -> int:
        removed = 0
        with self._lock:
            for section_id in [key for key, (owner, _) in self._sections.items() if owner == plugin]:
                del self._sections[section_id]
            for name, entries in self._hooks.items():
                kept = [entry for entry in entries if entry.plugin != plugin]
                removed += len(entries) - len(kept)
                self._hooks[name] = kept
        return removed

    def has(self, name: str) -> bool:
        with self._lock:
            return bool(self._hooks.get(name))

    def invoke(self, name: str, **kwargs: Any) -> list[Any]:
        with self._lock:
            registrations = list(self._hooks.get(name, ()))
        results: list[Any] = []
        fail_closed = name in FAIL_CLOSED_HOOKS
        for registration in registrations:
            payload = kwargs if registration.accepts_var_kwargs else {
                key: value for key, value in kwargs.items() if key in registration.params
            }
            try:
                outcome = self._call(registration, payload)
            except TimeoutError:
                logger.warning("hook %s from plugin %r timed out", name, registration.plugin)
                if fail_closed:
                    results.append({"action": "block", "message": TIMEOUT_BLOCK_MESSAGE})
                continue
            except Exception as exc:  # noqa: BLE001 - a plugin must never take the agent down
                logger.warning("hook %s from plugin %r failed: %s", name, registration.plugin, exc, exc_info=True)
                if fail_closed:
                    label = registration.plugin or getattr(registration.callback, "__name__", "callback")
                    results.append(
                        {"action": "block", "message": f"pre_tool_call guard {label!r} failed: {type(exc).__name__}"}
                    )
                continue
            if outcome is not None:
                results.append(outcome)
        return results

    def _call(self, registration: HookRegistration, payload: dict[str, Any]) -> Any:
        if not self.timeout or self.timeout <= 0:
            return registration.callback(**payload)
        box: dict[str, Any] = {}
        context = contextvars.copy_context()

        def run() -> None:
            try:
                box["value"] = context.run(registration.callback, **payload)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
                box["error"] = exc

        worker = threading.Thread(target=run, name=f"clite-hook-{registration.name}", daemon=True)
        worker.start()
        worker.join(self.timeout)
        if worker.is_alive():
            raise TimeoutError(registration.name)
        if "error" in box:
            raise box["error"]
        return box.get("value")


_BUSES: dict[str, HookBus] = {}
_BUSES_LOCK = threading.Lock()


def get_hook_bus() -> HookBus:
    """The bus for the active home. Each profile has its own plugins, hence its own bus."""
    key = home_key()
    with _BUSES_LOCK:
        bus = _BUSES.get(key)
        if bus is None:
            bus = _BUSES[key] = HookBus()
        return bus


def reset_hook_buses() -> None:
    with _BUSES_LOCK:
        _BUSES.clear()


def invoke_hook(name: str, **kwargs: Any) -> list[Any]:
    """Fire ``name`` on the active home's bus. Cheap when nothing is registered."""
    bus = get_hook_bus()
    return bus.invoke(name, **kwargs) if bus.has(name) else []


def has_hook(name: str) -> bool:
    return get_hook_bus().has(name)


def first_result(results: list[Any], kind: type | tuple[type, ...] = str) -> Any:
    """First result of the wanted type, for 'first non-None wins' transform hooks."""
    for result in results:
        if isinstance(result, kind):
            return result
    return None
