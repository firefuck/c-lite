"""Registry behaviour: registration, dispatch contract, availability caching."""

from __future__ import annotations

import json

import pytest

from clite.tools import registry as registry_module
from clite.tools.registry import discover_builtin_tools, registry, tool_error, tool_result

SCHEMA = {"description": "test tool", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}}}


def _register(name="t_echo", handler=None, **kwargs):
    return registry.register(name, "test-set", dict(SCHEMA), handler or (lambda args: tool_result(args)),
                             origin="test", **kwargs)


def test_register_fills_in_the_schema_name():
    entry = _register()
    assert entry.schema["name"] == "t_echo"
    assert registry.get("t_echo") is entry
    assert "t_echo" in registry.tools_in_toolset("test-set")


def test_schema_name_must_match():
    with pytest.raises(ValueError):
        registry.register("t_a", "test-set", {"name": "t_b"}, lambda args: "{}", origin="test")


def test_another_origin_cannot_replace_a_tool_silently():
    _register()
    with pytest.raises(ValueError):
        registry.register("t_echo", "x", dict(SCHEMA), lambda args: "{}", origin="plugin:other")
    registry.register("t_echo", "x", dict(SCHEMA), lambda args: '{"v": 2}', origin="plugin:other", override=True)
    try:
        assert json.loads(registry.dispatch("t_echo", {})) == {"v": 2}
    finally:
        registry.deregister("t_echo")


def test_registration_bumps_the_generation():
    before = registry.generation
    _register()
    assert registry.generation == before + 1
    registry.deregister("t_echo")
    assert registry.generation == before + 2


def test_dispatch_returns_a_json_string():
    _register()
    assert json.loads(registry.dispatch("t_echo", {"x": 1})) == {"x": 1}


def test_dispatch_serialises_non_string_results():
    _register(handler=lambda args: {"ok": True})
    assert json.loads(registry.dispatch("t_echo", {})) == {"ok": True}


def test_unknown_tool_is_an_error_result_not_an_exception():
    assert "Unknown tool" in json.loads(registry.dispatch("nope", {}))["error"]


def test_handler_exception_becomes_an_error_result():
    def boom(args):
        raise ValueError("bad input")

    _register(handler=boom)
    assert json.loads(registry.dispatch("t_echo", {}))["error"] == "ValueError: bad input"


def test_context_kwargs_reach_only_handlers_that_name_them():
    seen = {}

    def wants_ctx(args, ctx=None):
        seen["ctx"] = ctx
        return "{}"

    def wants_nothing(args):
        seen["plain"] = True
        return "{}"

    def wants_everything(args, **kwargs):
        seen["all"] = sorted(kwargs)
        return "{}"

    _register("t_ctx", wants_ctx)
    _register("t_plain", wants_nothing)
    _register("t_all", wants_everything)
    for name in ("t_ctx", "t_plain", "t_all"):
        registry.dispatch(name, {}, ctx="CTX", future_kwarg=1)
    assert seen == {"ctx": "CTX", "plain": True, "all": ["ctx", "future_kwarg"]}


def test_async_handlers_are_awaited():
    async def handler(args):
        return tool_result(value=args["x"] * 2)

    _register(handler=handler)
    assert json.loads(registry.dispatch("t_echo", {"x": 21})) == {"value": 42}


def test_tool_without_check_fn_is_always_available():
    _register()
    assert registry.is_available("t_echo") is True
    assert registry.is_available("missing") is False


def test_check_fn_result_is_cached(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(registry_module.time, "monotonic", lambda: clock["now"])
    calls = []
    _register(check_fn=lambda: calls.append(1) or False)
    assert registry.is_available("t_echo") is False
    assert registry.is_available("t_echo") is False
    assert len(calls) == 1
    clock["now"] += registry_module.CHECK_TTL_SECONDS + 1
    registry.is_available("t_echo")
    assert len(calls) == 2


def test_a_recently_passing_check_survives_one_flake(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(registry_module.time, "monotonic", lambda: clock["now"])
    state = {"ok": True}
    _register(check_fn=lambda: state["ok"])
    assert registry.is_available("t_echo") is True

    state["ok"] = False
    clock["now"] += registry_module.CHECK_TTL_SECONDS + 1
    assert registry.is_available("t_echo") is True  # inside the grace window

    clock["now"] += registry_module.CHECK_FLAKE_GRACE_SECONDS + registry_module.CHECK_TTL_SECONDS
    assert registry.is_available("t_echo") is False  # still failing after the grace window


def test_check_fn_that_raises_means_unavailable():
    def probe():
        raise OSError("daemon not running")

    _register(check_fn=probe)
    assert registry.is_available("t_echo") is False


def test_result_helpers():
    assert json.loads(tool_error("nope", code=3)) == {"error": "nope", "code": 3}
    assert json.loads(tool_result({"a": 1}, b=2)) == {"a": 1, "b": 2}


def test_builtin_discovery_registers_the_core_tools():
    discover_builtin_tools()
    assert {"terminal", "process", "read_file", "write_file", "patch", "search_files", "web_fetch"} <= set(registry.names())
