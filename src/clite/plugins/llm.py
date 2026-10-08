"""The auxiliary model a plugin may call: ``ctx.llm``.

A plugin sometimes needs a model for a side task of its own — classify this, rewrite that. It
gets one through this object, and only through this object. Three rules decide its shape:

* **Its own prompt only.** :meth:`PluginLLM.ask` takes the text the plugin wrote. No session is
  passed in and none is read, so a plugin cannot ask a question *about* the conversation: there
  is nothing here that hands it one. The messages sent are the plugin's system line (if it
  gives one) and its prompt, and nothing else.
* **A budget per plugin.** ``plugins.entries.<id>.llm.calls`` is how many calls a plugin may
  make in one run (default 0: no model access at all, like every other plugin capability). The
  call after the last one raises rather than quietly spending more. The count lives for the
  life of the process — it bounds a runaway plugin inside a run, it is not a quota on disk.
* **A ceiling per call.** ``plugins.llm.max_tokens`` (default :data:`DEFAULT_MAX_TOKENS`) caps
  how much the plugin can ask for, whatever it passes.

Which model answers is the user's choice, not the plugin's:
``auxiliary.plugin.provider``/``model``, falling back to the conversation's route and the
provider's cheap model, exactly like the other auxiliary tasks.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from clite.core.config import get_path, load_config
from clite.core.constants import home_key
from clite.core.errors import CliteError
from clite.providers.auxiliary import call_auxiliary
from clite.providers.runtime import resolve_runtime_provider

logger = logging.getLogger("clite.plugins.llm")

AUXILIARY_TASK = "plugin"  # auxiliary.plugin.provider / .model
DEFAULT_MAX_TOKENS = 1024
DEFAULT_CALLS = 0  # a plugin gets a model only when the user grants it one


class LlmError(RuntimeError):
    """A plugin asked for a model call it cannot make, and the message says why."""


_USED: dict[tuple[str, str], int] = {}  # (home, plugin id) -> calls made in this process
_LOCK = threading.Lock()


def calls_used(plugin_id: str) -> int:
    """How many calls ``plugin_id`` has made here (this home, this process)."""
    with _LOCK:
        return _USED.get((home_key(), plugin_id), 0)


def reset_llm_budgets() -> None:
    """Forget every count; called between tests and when profile state is reset."""
    with _LOCK:
        _USED.clear()


class PluginLLM:
    """What ``ctx.llm`` is. One per plugin; the counting lives in this module."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id

    @property
    def budget(self) -> int:
        """The calls this plugin may make in this run (``plugins.entries.<id>.llm.calls``)."""
        configured = self._setting("calls", DEFAULT_CALLS)
        try:
            return max(0, int(configured or 0))
        except (TypeError, ValueError):
            logger.warning("plugin %s has a non-numeric llm.calls (%r); using 0", self.plugin_id, configured)
            return 0

    @property
    def used(self) -> int:
        return calls_used(self.plugin_id)

    @property
    def remaining(self) -> int:
        """Calls left, never below zero. A plugin can watch this instead of failing."""
        return max(0, self.budget - self.used)

    def _setting(self, key: str, default: Any) -> Any:
        return get_path(load_config(), f"plugins.entries.{self.plugin_id}.llm.{key}", default)

    def ask(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send one prompt of the plugin's own and return the answer as text.

        Raises :class:`LlmError` when the budget is spent, when no model is configured, or when
        the call itself fails. A call that fails still counts against the budget: the point of
        the budget is to bound attempts, not successes.
        """
        text = str(prompt or "").strip()
        if not text:
            raise LlmError("nothing to ask: the prompt is empty")
        cfg = load_config()
        budget = self.budget
        with _LOCK:
            key = (home_key(), self.plugin_id)
            used = _USED.get(key, 0)
            if used >= budget:
                raise LlmError(
                    f"{self.plugin_id} has used all {budget} of its model calls for this run. "
                    f"Raise plugins.entries.{self.plugin_id}.llm.calls to allow more."
                )
            _USED[key] = used + 1
        messages: list[dict[str, Any]] = []
        if system and str(system).strip():
            messages.append({"role": "system", "content": str(system)})
        # The plugin's own prompt, verbatim and alone: no session message is ever appended here.
        messages.append({"role": "user", "content": text})
        try:
            limit = max(1, min(int(max_tokens or 0) or DEFAULT_MAX_TOKENS, self._ceiling(cfg)))
            route = resolve_runtime_provider(config=cfg)
            answer = call_auxiliary(
                AUXILIARY_TASK,
                messages,
                main_route=route,
                max_tokens=limit,
                temperature=temperature,
                config=cfg,
            )
        except CliteError as exc:
            raise LlmError(f"the model call failed: {exc}") from exc
        logger.info("plugin %s asked the model (call %d of %d)", self.plugin_id, used + 1, budget)
        return answer

    @staticmethod
    def _ceiling(cfg: dict[str, Any]) -> int:
        try:
            return max(1, int(get_path(cfg, "plugins.llm.max_tokens", DEFAULT_MAX_TOKENS) or 0))
        except (TypeError, ValueError):
            return DEFAULT_MAX_TOKENS
