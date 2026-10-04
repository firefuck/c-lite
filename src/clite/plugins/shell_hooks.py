"""Shell hooks: run your own commands on lifecycle events, configured in ``config.yaml``.

::

    hooks:
      pre_tool_call:
        - command: "~/.clite/hooks/guard.py"
          matcher: "terminal|write_file"   # optional regex, matched against the tool name
          timeout: 10                      # seconds (default 30, at most 300)
          fail_closed: true                # pre_tool_call only: a hook that breaks blocks the call
      on_session_end:
        - "notify-send C-lite 'session ended'"

Wire protocol (the shape other agent CLIs use, so existing hook scripts port over):

* stdin: one JSON object ``{hook_event_name, tool_name, tool_input, session_id, cwd, extra}``.
* stdout, optional, one JSON object:
  ``{"decision": "block", "reason": "..."}`` refuses a tool call (``pre_tool_call``),
  ``{"decision": "modify", "tool_input": {...}}`` rewrites its arguments,
  ``{"context": "..."}`` adds context to the user message for this turn (``pre_llm_call``).
* exit code 2 on ``pre_tool_call`` blocks the call; stderr is the reason given to the model.

A hook fails open (a broken notification script must not stop the agent) unless it is a
``pre_tool_call`` hook marked ``fail_closed``.

Consent: a hook runs only after the user approved that exact ``(event, command)`` pair with
``clite hooks approve``. Hooks run outside the command-approval gate and on every surface,
so editing ``config.yaml`` alone must never be enough to make a command run.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clite.core.brand import ENV_PREFIX
from clite.core.config import load_config
from clite.core.constants import get_home
from clite.core.io import atomic_write_json, read_json
from clite.plugins.hooks import VALID_HOOKS, get_hook_bus

logger = logging.getLogger("clite.plugins.shell_hooks")

SHELL_HOOKS_OWNER = "shell-hooks"  # the plugin id these callbacks are registered under
ALLOWLIST_FILENAME = "shell-hooks-allowlist.json"
ACCEPT_ENV = f"{ENV_PREFIX}_ACCEPT_HOOKS"  # =1 approves every configured hook (CI, containers)
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 300.0
BLOCK_EXIT_CODE = 2
DEFAULT_BLOCK_MESSAGE = "Blocked by a shell hook."
MESSAGE_LIMIT = 400

BLOCKING_EVENTS = frozenset({"pre_tool_call"})
TOOL_EVENTS = frozenset({"pre_tool_call", "post_tool_call"})
# Hooks whose callbacks return replacement text, or receive live objects, are for Python
# plugins only: a JSON document on stdin cannot carry them.
SHELL_HOOK_EVENTS = frozenset(VALID_HOOKS - {
    "transform_tool_result", "transform_terminal_output", "transform_llm_output", "pre_gateway_dispatch",
})
_TOP_LEVEL_KEYS = frozenset({"tool_name", "args", "session_id", "cwd"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class ShellHook:
    event: str
    command: str
    matcher: str = ""
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    fail_closed: bool = False

    def matches_tool(self, tool_name: Any) -> bool:
        if not self.matcher:
            return True
        return bool(tool_name) and re.fullmatch(self.matcher, str(tool_name)) is not None


@dataclass
class HookRun:
    """What happened when a hook command ran."""

    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""  # could not start, or timed out
    seconds: float = 0.0


# ── configuration ────────────────────────────────────────────────────────────────────────


def configured_hooks(config: dict[str, Any] | None = None) -> list[ShellHook]:
    """Every well-formed entry under ``hooks:``. Malformed entries are logged and skipped."""
    section = (config if config is not None else load_config()).get("hooks") or {}
    if not isinstance(section, dict):
        logger.warning("config `hooks` must be a mapping of event name to a list of hooks; ignored")
        return []
    hooks: list[ShellHook] = []
    for event, entries in section.items():
        if event not in SHELL_HOOK_EVENTS:
            logger.warning("config hooks: %r is not an event a shell hook can handle; valid: %s",
                           event, ", ".join(sorted(SHELL_HOOK_EVENTS)))
            continue
        for index, raw in enumerate(entries if isinstance(entries, list) else [entries]):
            hook = _parse_entry(str(event), raw)
            if hook is None:
                logger.warning("config hooks.%s[%d] is not a command or a mapping with `command`; skipped", event, index)
            else:
                hooks.append(hook)
    return hooks


def _parse_entry(event: str, raw: Any) -> ShellHook | None:
    if isinstance(raw, str):
        raw = {"command": raw}
    if not isinstance(raw, dict) or not str(raw.get("command") or "").strip():
        return None
    matcher = str(raw.get("matcher") or "")
    if matcher:
        try:
            re.compile(matcher)
        except re.error:
            return None
    try:
        timeout = float(raw.get("timeout") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return None
    return ShellHook(
        event=event, command=str(raw["command"]).strip(), matcher=matcher,
        timeout=min(max(timeout, 1.0), MAX_TIMEOUT_SECONDS),
        fail_closed=bool(raw.get("fail_closed")) and event in BLOCKING_EVENTS,
    )


# ── consent ──────────────────────────────────────────────────────────────────────────────


def allowlist_path() -> Path:
    return get_home() / ALLOWLIST_FILENAME


def _load_approvals() -> list[dict[str, Any]]:
    data = read_json(allowlist_path(), default={})
    approvals = data.get("approvals") if isinstance(data, dict) else None
    return [entry for entry in approvals or [] if isinstance(entry, dict)]


def is_approved(hook: ShellHook) -> bool:
    if os.environ.get(ACCEPT_ENV, "").strip().lower() in _TRUTHY:
        return True
    return any(entry.get("event") == hook.event and entry.get("command") == hook.command for entry in _load_approvals())


def approve_hooks(hooks: Iterable[ShellHook]) -> int:
    """Record the user's consent for these hooks. Returns how many were newly approved."""
    approvals = _load_approvals()
    known = {(entry.get("event"), entry.get("command")) for entry in approvals}
    added = 0
    for hook in hooks:
        if (hook.event, hook.command) not in known:
            approvals.append({"event": hook.event, "command": hook.command,
                              "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            known.add((hook.event, hook.command))
            added += 1
    if added:
        atomic_write_json(allowlist_path(), {"approvals": approvals})
    return added


def revoke_hooks(command: str | None = None) -> int:
    """Withdraw consent for ``command``, or for everything. Returns how many were removed."""
    approvals = _load_approvals()
    kept = [entry for entry in approvals if command is not None and entry.get("command") != command]
    if len(kept) != len(approvals):
        atomic_write_json(allowlist_path(), {"approvals": kept})
    return len(approvals) - len(kept)


# ── running a hook ───────────────────────────────────────────────────────────────────────


def build_payload(event: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "hook_event_name": event,
        "tool_name": kwargs.get("tool_name"),
        "tool_input": kwargs.get("args"),
        "session_id": kwargs.get("session_id") or "",
        "cwd": str(kwargs.get("cwd") or os.getcwd()),
        "extra": {key: value for key, value in kwargs.items() if key not in _TOP_LEVEL_KEYS},
    }


def run_hook(hook: ShellHook, kwargs: dict[str, Any]) -> HookRun:
    """Run the command once with the event payload on stdin. Never raises."""
    payload = build_payload(hook.event, kwargs)
    try:
        argv = shlex.split(hook.command, posix=os.name != "nt")
    except ValueError as exc:
        return HookRun(error=f"the command cannot be parsed: {exc}")
    if not argv:
        return HookRun(error="the command is empty")
    argv[0] = os.path.expanduser(argv[0])
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - the user wrote and approved this command
            argv, input=json.dumps(payload, ensure_ascii=False, default=str), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=hook.timeout,
            cwd=payload["cwd"] if os.path.isdir(payload["cwd"]) else None,
        )
    except subprocess.TimeoutExpired:
        return HookRun(error=f"timed out after {hook.timeout:g}s", seconds=time.monotonic() - started)
    except OSError as exc:
        return HookRun(error=f"could not start: {exc.strerror or exc}", seconds=time.monotonic() - started)
    return HookRun(completed.returncode, completed.stdout or "", completed.stderr or "", seconds=time.monotonic() - started)


def _parse_stdout(event: str, stdout: str) -> dict[str, Any] | None:
    """The hook's JSON answer as a directive the hook bus understands, or ``None``."""
    text = stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        logger.warning("shell hook for %s printed something that is not JSON: %s", event, text[:200])
        return None
    if not isinstance(data, dict):
        return None
    if event == "pre_tool_call":
        verb = data.get("action") or data.get("decision")
        if verb == "block":
            reason = data.get("message") or data.get("reason")
            return {"action": "block", "message": reason if isinstance(reason, str) and reason else DEFAULT_BLOCK_MESSAGE}
        new_args = data.get("args") if isinstance(data.get("args"), dict) else data.get("tool_input")
        if verb == "modify" and isinstance(new_args, dict):
            return {"action": "modify", "args": new_args}
        return None
    context = data.get("context")
    return {"context": context} if isinstance(context, str) and context.strip() else None


def evaluate(hook: ShellHook, run: HookRun) -> dict[str, Any] | None:
    """Turn a finished run into the hook's contribution. The one place failure policy lives."""
    blocking = hook.event in BLOCKING_EVENTS

    def failed(reason: str) -> dict[str, Any] | None:
        logger.warning("shell hook %s (%s) %s", hook.command, hook.event, reason)
        return {"action": "block", "message": f"hook {hook.command} failed closed: {reason}"} if hook.fail_closed else None

    if run.error:
        return failed(run.error)
    stderr = run.stderr.strip()[:MESSAGE_LIMIT]
    directive = _parse_stdout(hook.event, run.stdout)
    if run.exit_code == BLOCK_EXIT_CODE and blocking:
        if directive is not None and directive.get("action") == "block":
            return directive
        return {"action": "block", "message": stderr or DEFAULT_BLOCK_MESSAGE}
    if run.exit_code != 0 and directive is None:
        return failed(f"exited {run.exit_code}" + (f": {stderr}" if stderr else ""))
    if directive is None and hook.fail_closed and run.stdout.strip():
        return failed("printed output that is not a directive")
    return directive


def _make_callback(hook: ShellHook) -> Callable[..., dict[str, Any] | None]:
    def callback(**kwargs: Any) -> dict[str, Any] | None:
        if hook.event in TOOL_EVENTS and not hook.matches_tool(kwargs.get("tool_name")):
            return None
        return evaluate(hook, run_hook(hook, kwargs))

    callback.__name__ = callback.__qualname__ = f"shell_hook[{hook.event}:{hook.command}]"
    return callback


# ── registration ─────────────────────────────────────────────────────────────────────────


def register_shell_hooks(config: dict[str, Any] | None = None) -> tuple[list[ShellHook], list[ShellHook]]:
    """(Re)register the configured hooks on the active home's bus.

    Returns ``(registered, pending)``: hooks that now run, and hooks waiting for
    ``clite hooks approve``. Idempotent: earlier shell-hook registrations are replaced.
    """
    bus = get_hook_bus()
    bus.unregister_plugin(SHELL_HOOKS_OWNER)
    registered: list[ShellHook] = []
    pending: list[ShellHook] = []
    for hook in configured_hooks(config):
        if not is_approved(hook):
            pending.append(hook)
            continue
        if bus.timeout and hook.timeout >= bus.timeout:
            # The bus abandons a callback after plugins.hook_callback_timeout, and for
            # pre_tool_call that means "block". Finish first, so the hook's own policy decides.
            hook = ShellHook(hook.event, hook.command, hook.matcher, max(bus.timeout - 1.0, 1.0), hook.fail_closed)
        bus.register(hook.event, _make_callback(hook), plugin=SHELL_HOOKS_OWNER)
        registered.append(hook)
    if pending:
        logger.warning("%d shell hook(s) are configured but not approved; run `clite hooks approve`", len(pending))
    return registered, pending
