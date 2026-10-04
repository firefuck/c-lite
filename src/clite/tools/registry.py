"""Tool registry: one process-wide table of every tool the model can call.

Rules:

* A tool module registers itself at import time with ``registry.register(...)``.
* A handler takes the model's arguments as one ``dict`` and returns a JSON **string**.
  Errors are returned as ``{"error": ...}``, never raised to the model.
* Extra keyword arguments (``ctx`` and friends) are passed only to handlers that name them,
  so adding a new one never breaks an existing tool or plugin.
* ``check_fn`` decides whether a tool is offered at all. Its result is cached, because the
  tool list is part of the prompt prefix and must not flap between turns.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import json
import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("clite.tools.registry")

CHECK_TTL_SECONDS = 30.0
# A check that was passing and now fails keeps the tool visible this long: one flaky probe
# must not pull a tool out from under a running conversation.
CHECK_FLAKE_GRACE_SECONDS = 60.0

PARALLEL_NEVER = "never"  # side effects or user interaction: always sequential
PARALLEL_SAFE = "safe"  # read-only: may run alongside anything parallel
PARALLEL_PATH = "path"  # may run in parallel when its paths do not overlap another call's


@dataclass
class ToolEntry:
    name: str
    toolset: str
    schema: dict[str, Any]
    handler: Callable[..., Any]
    check_fn: Callable[[], bool] | None = None
    requires_env: tuple[str, ...] = ()
    emoji: str = ""
    parallel: str = PARALLEL_NEVER
    path_args: tuple[str, ...] = ()
    max_result_chars: int | None = None
    origin: str = "builtin"
    # Rewrites the schema when definitions are built (e.g. to list the names that exist now).
    dynamic_schema: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    is_async: bool = False
    _accepts_var_kwargs: bool = field(default=False, repr=False)
    _params: frozenset[str] = field(default_factory=frozenset, repr=False)

    @property
    def description(self) -> str:
        return str(self.schema.get("description", ""))


class ToolRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tools: dict[str, ToolEntry] = {}
        self._checks: dict[str, tuple[float, bool, float]] = {}  # name -> (checked_at, ok, last_ok_at)
        self.generation = 0  # bumped on every change; definition caches key on it

    # ── registration ─────────────────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict[str, Any],
        handler: Callable[..., Any],
        *,
        check_fn: Callable[[], bool] | None = None,
        requires_env: Iterable[str] = (),
        emoji: str = "",
        parallel: str = PARALLEL_NEVER,
        path_args: Iterable[str] = (),
        max_result_chars: int | None = None,
        origin: str = "builtin",
        dynamic_schema: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        override: bool = False,
    ) -> ToolEntry:
        if parallel not in (PARALLEL_NEVER, PARALLEL_SAFE, PARALLEL_PATH):
            raise ValueError(f"invalid parallel policy for {name}: {parallel!r}")
        normalized = dict(schema)
        normalized.setdefault("name", name)
        normalized.setdefault("parameters", {"type": "object", "properties": {}})
        if normalized["name"] != name:
            raise ValueError(f"schema name {normalized['name']!r} does not match tool name {name!r}")
        var_kwargs, params = _describe_handler(handler)
        entry = ToolEntry(
            name=name, toolset=toolset, schema=normalized, handler=handler, check_fn=check_fn,
            requires_env=tuple(requires_env), emoji=emoji, parallel=parallel, path_args=tuple(path_args),
            max_result_chars=max_result_chars, origin=origin, dynamic_schema=dynamic_schema,
            is_async=inspect.iscoroutinefunction(handler), _accepts_var_kwargs=var_kwargs, _params=params,
        )
        with self._lock:
            existing = self._tools.get(name)
            if existing is not None and existing.origin != origin and not override:
                raise ValueError(
                    f"tool {name!r} is already registered by {existing.origin}; "
                    f"{origin} may not replace it without override=True"
                )
            self._tools[name] = entry
            self._checks.pop(name, None)
            self.generation += 1
        return entry

    def deregister(self, name: str) -> bool:
        with self._lock:
            removed = self._tools.pop(name, None) is not None
            self._checks.pop(name, None)
            if removed:
                self.generation += 1
            return removed

    def restore(self, entry: ToolEntry) -> None:
        """Put back an entry that an override displaced (used when a plugin is unloaded)."""
        with self._lock:
            self._tools[entry.name] = entry
            self._checks.pop(entry.name, None)
            self.generation += 1

    def deregister_origin(self, origin: str) -> list[str]:
        with self._lock:
            names = [name for name, entry in self._tools.items() if entry.origin == origin]
        for name in names:
            self.deregister(name)
        return names

    # ── lookup ───────────────────────────────────────────────────────────────────────────

    def get(self, name: str) -> ToolEntry | None:
        with self._lock:
            return self._tools.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools)

    def entries(self) -> list[ToolEntry]:
        with self._lock:
            return [self._tools[name] for name in sorted(self._tools)]

    def toolset_names(self) -> list[str]:
        with self._lock:
            return sorted({entry.toolset for entry in self._tools.values()})

    def tools_in_toolset(self, toolset: str) -> list[str]:
        with self._lock:
            return sorted(name for name, entry in self._tools.items() if entry.toolset == toolset)

    # ── availability ─────────────────────────────────────────────────────────────────────

    def is_available(self, name: str) -> bool:
        entry = self.get(name)
        if entry is None:
            return False
        if entry.check_fn is None:
            return True
        now = time.monotonic()
        with self._lock:
            cached = self._checks.get(name)
        if cached is not None and now - cached[0] < CHECK_TTL_SECONDS:
            return cached[1]
        try:
            ok = bool(entry.check_fn())
        except Exception as exc:  # noqa: BLE001 - a broken probe means "unavailable", not a crash
            logger.debug("check_fn for %s raised: %s", name, exc)
            ok = False
        last_ok = now if ok else (cached[2] if cached else float("-inf"))
        if not ok and now - last_ok < CHECK_FLAKE_GRACE_SECONDS:
            ok = True  # passed recently: treat this failure as a flake
        with self._lock:
            self._checks[name] = (now, ok, last_ok)
        return ok

    def reset_check_cache(self) -> None:
        with self._lock:
            self._checks.clear()

    # ── dispatch ─────────────────────────────────────────────────────────────────────────

    def dispatch(self, name: str, args: dict[str, Any] | None, **context: Any) -> str:
        """Run a tool and return its JSON string. Never raises for a tool-level failure."""
        entry = self.get(name)
        if entry is None:
            return tool_error(f"Unknown tool: {name}")
        kwargs = context if entry._accepts_var_kwargs else {
            key: value for key, value in context.items() if key in entry._params
        }
        try:
            result = entry.handler(args or {}, **kwargs)
            if inspect.isawaitable(result):
                result = run_async(result)
        except Exception as exc:  # noqa: BLE001 - the model gets the error and can react to it
            logger.warning("tool %s raised", name, exc_info=True)
            return tool_error(f"{type(exc).__name__}: {exc}")
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            return tool_error(f"tool {name} returned an unserialisable result: {exc}")


def _describe_handler(handler: Callable[..., Any]) -> tuple[bool, frozenset[str]]:
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return True, frozenset()
    parameters = list(signature.parameters.values())
    var_kwargs = any(p.kind is p.VAR_KEYWORD for p in parameters)
    names = frozenset(p.name for p in parameters[1:] if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY))
    return var_kwargs, names


# ── async bridge ─────────────────────────────────────────────────────────────────────────

_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK = threading.Lock()


def get_background_loop() -> asyncio.AbstractEventLoop:
    """One long-lived event loop on a daemon thread, shared by async tools and MCP clients.

    ``asyncio.run`` per call would close the loop each time, which breaks any client object
    (an HTTP session, an MCP connection) that outlives a single call.
    """
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="clite-tool-loop", daemon=True)
            thread.start()
            _LOOP = loop
        return _LOOP


def run_async(awaitable: Any, timeout: float | None = None) -> Any:
    """Run a coroutine to completion from sync code, on the shared background loop."""
    future = asyncio.run_coroutine_threadsafe(awaitable, get_background_loop())
    return future.result(timeout)


# ── result helpers ───────────────────────────────────────────────────────────────────────


def tool_error(message: str, **extra: Any) -> str:
    return json.dumps({"error": str(message), **extra}, ensure_ascii=False, default=str)


def tool_result(data: dict[str, Any] | None = None, **fields: Any) -> str:
    payload = dict(data or {})
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False, default=str)


# ── discovery ────────────────────────────────────────────────────────────────────────────

registry = ToolRegistry()
_DISCOVERED = False
_DISCOVER_LOCK = threading.Lock()


def _registers_tools(path: Path) -> bool:
    """True when the module has a top-level ``registry.register(...)`` call."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        call = node.value if isinstance(node, ast.Expr) else None
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "register"
            and isinstance(func.value, ast.Name)
            and func.value.id == "registry"
        ):
            return True
    return False


def discover_builtin_tools(force: bool = False) -> list[str]:
    """Import every module in ``clite.tools.builtin`` that registers a tool.

    Adding a built-in tool is therefore one new file; there is no import list to maintain.
    """
    global _DISCOVERED
    with _DISCOVER_LOCK:
        if _DISCOVERED and not force:
            return []
        package_dir = Path(__file__).resolve().parent / "builtin"
        imported: list[str] = []
        for path in sorted(package_dir.glob("*.py")):
            if path.name.startswith("_") or not _registers_tools(path):
                continue
            module_name = f"clite.tools.builtin.{path.stem}"
            try:
                importlib.import_module(module_name)
                imported.append(module_name)
            except Exception:  # noqa: BLE001 - one broken tool file must not hide the rest
                logger.warning("could not import tool module %s", module_name, exc_info=True)
        _DISCOVERED = True
        return imported


def reset_check_cache() -> None:
    registry.reset_check_cache()
