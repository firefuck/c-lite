"""The two entry points the agent loop uses: tool definitions in, tool results out.

``get_tool_definitions`` decides what the model is offered; ``handle_function_call`` runs one
call through the plugin hooks, the registry and the output cap.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from clite.core.config import get_path, load_config
from clite.plugins.hooks import first_result, has_hook, invoke_hook
from clite.tools.context import ToolContext
from clite.tools.registry import discover_builtin_tools, registry, tool_error
from clite.tools.toolsets import resolve_toolsets

logger = logging.getLogger("clite.tools.dispatch")

_DEFINITION_CACHE: OrderedDict[tuple, list[dict[str, Any]]] = OrderedDict()
_DEFINITION_CACHE_MAX = 8
_CACHE_LOCK = threading.Lock()


def reset_definition_cache() -> None:
    with _CACHE_LOCK:
        _DEFINITION_CACHE.clear()


def resolve_enabled_tools(
    enabled_toolsets: list[str] | None = None,
    disabled_toolsets: list[str] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Names of the tools a session may use, sorted, availability applied.

    ``disabled_toolsets`` is subtracted last so it always wins, including over a tool that a
    composite toolset pulled in.
    """
    discover_builtin_tools()
    cfg = config if config is not None else load_config()
    enabled = list(enabled_toolsets) if enabled_toolsets is not None else list(cfg.get("toolsets") or [])
    disabled = list(disabled_toolsets) if disabled_toolsets is not None else list(cfg.get("disabled_toolsets") or [])
    blocked = set(resolve_toolsets(disabled))
    names = [name for name in resolve_toolsets(enabled) if name not in blocked]
    return sorted(name for name in names if registry.is_available(name))


def get_tool_definitions(
    enabled_toolsets: list[str] | None = None,
    disabled_toolsets: list[str] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """OpenAI-format tool definitions, sorted by name so the request prefix is byte-stable."""
    names = resolve_enabled_tools(enabled_toolsets, disabled_toolsets, config=config)
    key = (tuple(names), registry.generation)
    with _CACHE_LOCK:
        cached = _DEFINITION_CACHE.get(key)
        if cached is not None and not _has_dynamic(names):
            _DEFINITION_CACHE.move_to_end(key)
            return copy.deepcopy(cached)
    definitions = []
    for name in names:
        entry = registry.get(name)
        if entry is None:
            continue
        schema = copy.deepcopy(entry.schema)
        if entry.dynamic_schema is not None:
            try:
                schema = entry.dynamic_schema(schema)
            except Exception:  # noqa: BLE001 - fall back to the static schema
                logger.warning("dynamic schema for %s failed", name, exc_info=True)
        definitions.append({"type": "function", "function": schema})
    with _CACHE_LOCK:
        _DEFINITION_CACHE[key] = definitions
        while len(_DEFINITION_CACHE) > _DEFINITION_CACHE_MAX:
            _DEFINITION_CACHE.popitem(last=False)
    return copy.deepcopy(definitions)


def _has_dynamic(names: list[str]) -> bool:
    return any((entry := registry.get(name)) is not None and entry.dynamic_schema is not None for name in names)


# ── argument coercion ────────────────────────────────────────────────────────────────────


def coerce_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Repair the common shape mistakes models make: ``"5"`` for 5, ``"true"`` for true,
    a JSON string where an array or object was declared."""
    properties = get_path(schema, "parameters.properties", {}) or {}
    coerced = dict(args)
    for key, value in args.items():
        declared = (properties.get(key) or {}).get("type")
        if not isinstance(value, str) or declared in (None, "string"):
            continue
        text = value.strip()
        try:
            if declared == "integer":
                coerced[key] = int(text)
            elif declared == "number":
                coerced[key] = float(text)
            elif declared == "boolean" and text.lower() in ("true", "false"):
                coerced[key] = text.lower() == "true"
            elif declared in ("array", "object"):
                parsed = json.loads(text)
                if isinstance(parsed, list if declared == "array" else dict):
                    coerced[key] = parsed
        except (ValueError, TypeError):
            continue  # leave it; the handler reports the bad value
    return coerced


# ── execution ────────────────────────────────────────────────────────────────────────────


def cap_result(result: str, limit: int | None) -> str:
    """Keep the head and the tail of an oversized result and say what was dropped."""
    if not limit or len(result) <= limit:
        return result
    head, tail = int(limit * 0.6), int(limit * 0.3)
    dropped = len(result) - head - tail
    return (
        result[:head]
        + f"\n\n[... {dropped} characters truncated. Narrow the request (offset/limit, a more specific "
        "query) to see the rest ...]\n\n"
        + result[-tail:]
    )


def handle_function_call(name: str, args: dict[str, Any] | None, ctx: ToolContext | None = None) -> str:
    """Run one tool call end to end and return the string that goes back to the model."""
    ctx = ctx or ToolContext()
    args = dict(args or {})
    entry = registry.get(name)
    if entry is None:
        return tool_error(f"Unknown tool: {name}", available_tools=sorted(ctx.enabled_tools) or registry.names())
    if ctx.enabled_tools and name not in ctx.enabled_tools:
        return tool_error(f"Tool {name!r} is not enabled in this session", available_tools=sorted(ctx.enabled_tools))
    args = coerce_args(entry.schema, args)

    if has_hook("pre_tool_call"):
        for directive in invoke_hook(
            "pre_tool_call", tool_name=name, args=args, session_id=ctx.session_id, platform=ctx.platform,
            tool_call_id=ctx.tool_call_id, cwd=ctx.cwd,
        ):
            if not isinstance(directive, dict):
                continue
            action = directive.get("action")
            if action == "block":
                return tool_error(str(directive.get("message") or "Blocked by a plugin"), blocked=True)
            if action == "modify" and isinstance(directive.get("args"), dict):
                args = directive["args"]

    started = time.monotonic()
    result = registry.dispatch(name, args, ctx=ctx)
    duration = time.monotonic() - started

    if has_hook("transform_tool_result"):
        replacement = first_result(
            invoke_hook("transform_tool_result", tool_name=name, args=args, result=result, session_id=ctx.session_id)
        )
        if replacement is not None:
            result = replacement

    limit = entry.max_result_chars or ctx.setting("tool_result_max_chars")
    result = cap_result(result, limit)

    if has_hook("post_tool_call"):
        invoke_hook(
            "post_tool_call", tool_name=name, args=args, result=result, duration=duration,
            session_id=ctx.session_id, platform=ctx.platform, tool_call_id=ctx.tool_call_id, cwd=ctx.cwd,
        )
    return result
