"""Toolset resolution, tool definitions and the handle_function_call pipeline."""

from __future__ import annotations

import json

from clite.plugins.hooks import get_hook_bus
from clite.tools.context import ToolContext
from clite.tools.dispatch import (
    cap_result,
    coerce_args,
    get_tool_definitions,
    handle_function_call,
    resolve_enabled_tools,
)
from clite.tools.registry import registry, tool_result
from clite.tools.toolsets import TOOLSETS, all_toolsets, register_toolset, resolve_toolset, resolve_toolsets

SCHEMA = {
    "description": "test tool",
    "parameters": {
        "type": "object",
        "properties": {
            "count": {"type": "integer"}, "ratio": {"type": "number"}, "flag": {"type": "boolean"},
            "items": {"type": "array"}, "name": {"type": "string"},
        },
    },
}


def _register(name="t_tool", handler=None, toolset="test-set", **kwargs):
    return registry.register(name, toolset, dict(SCHEMA), handler or (lambda args: tool_result(args)),
                             origin="test", **kwargs)


def _names(definitions):
    return [definition["function"]["name"] for definition in definitions]


# ── toolsets ─────────────────────────────────────────────────────────────────────────────


def test_composite_toolset_follows_includes():
    tools = resolve_toolset("clite-cli")
    assert {"terminal", "read_file", "web_fetch", "todo", "memory", "delegate_task", "clarify"} <= set(tools)
    assert len(tools) == len(set(tools))


def test_subagent_toolset_cannot_delegate_ask_or_write_memory():
    assert not {"delegate_task", "clarify", "memory", "cronjob"} & set(resolve_toolset("clite-subagent"))


def test_cron_toolset_cannot_ask_or_schedule():
    assert not {"clarify", "cronjob"} & set(resolve_toolset("clite-cron"))


def test_unknown_toolset_resolves_to_nothing():
    assert resolve_toolset("does-not-exist") == []


def test_include_cycle_terminates(monkeypatch):
    monkeypatch.setitem(TOOLSETS, "a", {"description": "", "tools": ["x"], "includes": ["b"]})
    monkeypatch.setitem(TOOLSETS, "b", {"description": "", "tools": ["y"], "includes": ["a"]})
    assert resolve_toolset("a") == ["x", "y"]


def test_a_tool_registered_into_a_new_toolset_name_resolves():
    _register("t_plugin_tool", toolset="my-plugin")
    assert resolve_toolset("my-plugin") == ["t_plugin_tool"]
    assert "my-plugin" in all_toolsets()


def test_register_toolset_and_all_alias(monkeypatch):
    monkeypatch.setattr("clite.tools.toolsets.TOOLSETS", dict(TOOLSETS))
    register_toolset("pair", "two tools", tools=["read_file"], includes=["terminal"])
    assert resolve_toolsets(["pair"]) == ["read_file", "terminal", "process"]
    _register()
    assert "t_tool" in resolve_toolset("all")


# ── definitions ──────────────────────────────────────────────────────────────────────────


def test_definitions_are_sorted_and_openai_shaped():
    definitions = get_tool_definitions(["file", "terminal"], [])
    assert _names(definitions) == sorted(_names(definitions))
    assert all(d["type"] == "function" and "parameters" in d["function"] for d in definitions)


def test_disabled_toolsets_win_over_a_composite():
    names = _names(get_tool_definitions(["clite-cli"], ["terminal"]))
    assert "terminal" not in names and "process" not in names
    assert "read_file" in names


def test_defaults_come_from_config(clite_home):
    (clite_home / "config.yaml").write_text("toolsets: [file]\ndisabled_toolsets: []\n")
    assert resolve_enabled_tools() == ["patch", "read_file", "search_files", "write_file"]


def test_unavailable_tools_are_not_offered():
    _register("t_gated", check_fn=lambda: False)
    _register("t_open")
    assert _names(get_tool_definitions(["test-set"], [])) == ["t_open"]


def test_definitions_are_copies():
    first = get_tool_definitions(["file"], [])
    first[0]["function"]["description"] = "mutated"
    assert get_tool_definitions(["file"], [])[0]["function"]["description"] != "mutated"


def test_dynamic_schema_is_applied_each_time():
    counter = {"n": 0}

    def rewrite(schema):
        counter["n"] += 1
        schema["description"] = f"call {counter['n']}"
        return schema

    _register("t_dynamic", dynamic_schema=rewrite)
    assert get_tool_definitions(["test-set"], [])[0]["function"]["description"] == "call 1"
    assert get_tool_definitions(["test-set"], [])[0]["function"]["description"] == "call 2"


# ── handle_function_call ─────────────────────────────────────────────────────────────────


def test_string_arguments_are_coerced_to_declared_types():
    coerced = coerce_args(SCHEMA, {"count": "5", "ratio": "0.5", "flag": "TRUE", "items": '["a"]', "name": "7"})
    assert coerced == {"count": 5, "ratio": 0.5, "flag": True, "items": ["a"], "name": "7"}


def test_uncoercible_values_are_left_for_the_handler():
    assert coerce_args(SCHEMA, {"count": "many", "items": "not json"}) == {"count": "many", "items": "not json"}


def test_call_runs_the_handler():
    _register()
    assert json.loads(handle_function_call("t_tool", {"count": "2"})) == {"count": 2}


def test_unknown_tool_lists_what_is_available():
    result = json.loads(handle_function_call("nope", {}, ToolContext(enabled_tools=frozenset({"read_file"}))))
    assert "Unknown tool" in result["error"]
    assert result["available_tools"] == ["read_file"]


def test_tool_outside_the_session_toolset_is_refused():
    _register()
    result = json.loads(handle_function_call("t_tool", {}, ToolContext(enabled_tools=frozenset({"read_file"}))))
    assert "not enabled" in result["error"]


def test_pre_tool_call_can_block():
    _register()
    get_hook_bus().register("pre_tool_call", lambda tool_name: {"action": "block", "message": "policy says no"})
    assert json.loads(handle_function_call("t_tool", {})) == {"error": "policy says no", "blocked": True}


def test_pre_tool_call_can_rewrite_arguments():
    _register()
    get_hook_bus().register("pre_tool_call", lambda args: {"action": "modify", "args": {**args, "name": "rewritten"}})
    assert json.loads(handle_function_call("t_tool", {"count": 1})) == {"count": 1, "name": "rewritten"}


def test_a_crashing_guard_blocks_the_call():
    ran = []
    _register(handler=lambda args: ran.append(1) or "{}")

    def guard(tool_name):
        raise RuntimeError("guard bug")

    get_hook_bus().register("pre_tool_call", guard, plugin="guard")
    assert json.loads(handle_function_call("t_tool", {}))["blocked"] is True
    assert ran == []


def test_transform_tool_result_replaces_the_result():
    _register()
    get_hook_bus().register("transform_tool_result", lambda result: result.replace("secret", "***"))
    assert handle_function_call("t_tool", {"name": "secret"}) == '{"name": "***"}'


def test_post_tool_call_observes_the_final_result():
    seen = {}
    _register()
    get_hook_bus().register("post_tool_call", lambda tool_name, result, duration: seen.update(tool=tool_name, result=result))
    handle_function_call("t_tool", {"count": 1})
    assert seen == {"tool": "t_tool", "result": '{"count": 1}'}


def test_oversized_results_keep_head_and_tail():
    capped = cap_result("H" * 500 + "M" * 5000 + "T" * 500, 1000)
    assert capped.startswith("H" * 500) and capped.endswith("T" * 300)
    assert "characters truncated" in capped
    assert cap_result("short", 1000) == "short"


def test_per_tool_cap_applies():
    _register(handler=lambda args: "x" * 10_000, max_result_chars=1000)
    assert len(handle_function_call("t_tool", {})) < 1300
