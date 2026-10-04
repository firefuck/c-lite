"""Hook bus behaviour: additive kwargs, isolation, fail-closed policy hooks."""

from __future__ import annotations

import time

import pytest

from clite.core.constants import home_scope
from clite.plugins.hooks import (
    TIMEOUT_BLOCK_MESSAGE,
    first_result,
    get_hook_bus,
    has_hook,
    invoke_hook,
)


def test_unknown_hook_name_is_rejected():
    with pytest.raises(ValueError):
        get_hook_bus().register("on_tuesday", lambda: None)


def test_nothing_registered_returns_empty_list():
    assert has_hook("post_tool_call") is False
    assert invoke_hook("post_tool_call", tool_name="x") == []


def test_callback_receives_only_the_kwargs_it_names():
    seen = {}

    def narrow(tool_name):
        seen["narrow"] = tool_name

    def wide(**kwargs):
        seen["wide"] = sorted(kwargs)

    bus = get_hook_bus()
    bus.register("post_tool_call", narrow)
    bus.register("post_tool_call", wide)
    invoke_hook("post_tool_call", tool_name="terminal", result="{}", added_in_a_later_release=1)
    assert seen == {"narrow": "terminal", "wide": ["added_in_a_later_release", "result", "tool_name"]}


def test_results_keep_registration_order_and_drop_none():
    bus = get_hook_bus()
    bus.register("transform_tool_result", lambda: None)
    bus.register("transform_tool_result", lambda: "first")
    bus.register("transform_tool_result", lambda: "second")
    results = invoke_hook("transform_tool_result")
    assert results == ["first", "second"]
    assert first_result(results) == "first"


def test_a_failing_observer_does_not_affect_the_others():
    calls = []

    def broken():
        raise RuntimeError("plugin bug")

    bus = get_hook_bus()
    bus.register("post_tool_call", broken, plugin="bad")
    bus.register("post_tool_call", lambda: calls.append("ok"))
    assert invoke_hook("post_tool_call") == []
    assert calls == ["ok"]


def test_policy_hook_that_raises_blocks():
    def guard(tool_name):
        raise RuntimeError("cannot decide")

    get_hook_bus().register("pre_tool_call", guard, plugin="policy")
    (directive,) = invoke_hook("pre_tool_call", tool_name="terminal")
    assert directive["action"] == "block"
    assert "policy" in directive["message"]


def test_policy_hook_that_times_out_blocks():
    bus = get_hook_bus()
    bus.timeout = 0.05
    bus.register("pre_tool_call", lambda: time.sleep(1))
    assert invoke_hook("pre_tool_call") == [{"action": "block", "message": TIMEOUT_BLOCK_MESSAGE}]


def test_observer_that_times_out_is_skipped():
    bus = get_hook_bus()
    bus.timeout = 0.05
    bus.register("post_tool_call", lambda: time.sleep(1))
    assert invoke_hook("post_tool_call") == []


def test_unregister_plugin_removes_all_its_hooks():
    bus = get_hook_bus()
    bus.register("post_tool_call", lambda: 1, plugin="a")
    bus.register("pre_llm_call", lambda: 1, plugin="a")
    bus.register("post_tool_call", lambda: 2, plugin="b")
    assert bus.unregister_plugin("a") == 2
    assert invoke_hook("post_tool_call") == [2]
    assert has_hook("pre_llm_call") is False


def test_each_home_has_its_own_bus(tmp_path):
    get_hook_bus().register("post_tool_call", lambda: "default profile")
    with home_scope(tmp_path / "other-profile"):
        assert invoke_hook("post_tool_call") == []
    assert invoke_hook("post_tool_call") == ["default profile"]
