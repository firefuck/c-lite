"""Shell hooks: commands from ``hooks:`` in config.yaml, run on lifecycle events."""

from __future__ import annotations

import json
import sys
import textwrap

import pytest
import yaml

from clite.cli.main import main
from clite.core.config import reset_config_cache
from clite.plugins.hooks import get_hook_bus, invoke_hook
from clite.plugins.manager import get_plugin_manager
from clite.plugins.shell_hooks import (
    ACCEPT_ENV,
    ShellHook,
    approve_hooks,
    configured_hooks,
    evaluate,
    is_approved,
    register_shell_hooks,
    revoke_hooks,
    run_hook,
)
from clite.providers.testing import ScriptedClient, text_response
from clite.runtime.factory import build_agent
from clite.tools.context import ToolContext
from clite.tools.dispatch import handle_function_call
from clite.tools.file_safety import write_denied_reason
from clite.tools.registry import registry, tool_result

MOCK = {"model": {"provider": "mock", "default": "mock-1"}}


@pytest.fixture
def hook_script(tmp_path):
    """``hook_script(name, body) -> command``: a Python script usable as a hook command.

    Inside ``body``, ``event`` is the parsed stdin payload and ``here`` the script's directory.
    """

    def write(name: str, body: str) -> str:
        path = tmp_path / f"{name}.py"
        path.write_text(
            "import json, pathlib, sys\n"
            "event = json.load(sys.stdin)\n"
            "here = pathlib.Path(__file__).parent\n" + textwrap.dedent(body)
        )
        return f"{sys.executable} {path}"

    return write


@pytest.fixture
def configure(clite_home):
    """``configure(hooks, approve=True)``: write the hooks section and (re)load plugins."""

    def apply(hooks: dict, *, approve: bool = True, **extra) -> None:
        (clite_home / "config.yaml").write_text(yaml.safe_dump({**MOCK, "hooks": hooks, **extra}))
        reset_config_cache()
        if approve:
            approve_hooks(configured_hooks())
        get_plugin_manager().load_all()

    return apply


@pytest.fixture
def probe():
    """A tool that reports the arguments it was called with."""
    schema = {"description": "probe", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}
    registry.register("probe", "probe", schema, lambda args: tool_result(ran=True, args=args), origin="test")
    registry.register("other", "probe", dict(schema), lambda args: tool_result(ran=True, args=args), origin="test")

    def call(name="probe", **args):
        return json.loads(handle_function_call(name, args, ToolContext(session_id="s1", cwd="/tmp")))

    return call


# ── consent ──────────────────────────────────────────────────────────────────────────────


def test_a_configured_hook_does_not_run_until_it_is_approved(configure, hook_script, probe):
    command = hook_script("block", 'print(json.dumps({"decision": "block", "reason": "no"}))')
    configure({"pre_tool_call": [{"command": command}]}, approve=False)
    assert probe()["ran"] is True
    assert [hook.command for hook in get_plugin_manager().pending_shell_hooks] == [command]

    assert approve_hooks(configured_hooks()) == 1
    assert approve_hooks(configured_hooks()) == 0  # already recorded
    get_plugin_manager().load_all()
    assert probe() == {"error": "no", "blocked": True}
    assert get_plugin_manager().pending_shell_hooks == []


def test_approval_is_for_the_exact_event_and_command(configure, hook_script):
    command = hook_script("a", "")
    approve_hooks([ShellHook("pre_tool_call", command)])
    assert is_approved(ShellHook("pre_tool_call", command))
    assert not is_approved(ShellHook("post_tool_call", command))
    assert not is_approved(ShellHook("pre_tool_call", command + " --extra"))
    assert revoke_hooks(command) == 1 and not is_approved(ShellHook("pre_tool_call", command))
    approve_hooks([ShellHook("pre_tool_call", "one"), ShellHook("pre_tool_call", "two")])
    assert revoke_hooks(None) == 2


def test_the_accept_variable_approves_everything(configure, hook_script, probe, monkeypatch):
    command = hook_script("block", 'print(json.dumps({"decision": "block", "reason": "no"}))')
    monkeypatch.setenv(ACCEPT_ENV, "1")
    configure({"pre_tool_call": [command]}, approve=False)
    assert probe()["blocked"] is True


def test_the_allowlist_cannot_be_written_with_the_file_tools(clite_home):
    assert "credentials or settings" in write_denied_reason(clite_home / "shell-hooks-allowlist.json")


# ── the wire protocol ────────────────────────────────────────────────────────────────────


def test_a_hook_receives_the_event_as_json_on_stdin(configure, hook_script, probe, tmp_path):
    command = hook_script("record", '(here / "seen.json").write_text(json.dumps(event))')
    configure({"post_tool_call": [command]})
    probe(path="notes.txt")
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert seen["hook_event_name"] == "post_tool_call" and seen["tool_name"] == "probe"
    assert seen["tool_input"] == {"path": "notes.txt"} and seen["session_id"] == "s1" and seen["cwd"] == "/tmp"
    assert json.loads(seen["extra"]["result"])["ran"] is True and "duration" in seen["extra"]


def test_exit_code_2_blocks_and_stderr_is_the_reason(configure, hook_script, probe):
    configure({"pre_tool_call": [hook_script("deny", 'sys.stderr.write("not on a Friday"); sys.exit(2)')]})
    assert probe() == {"error": "not on a Friday", "blocked": True}


def test_both_block_dialects_and_modify_are_understood(configure, hook_script, probe):
    configure({"pre_tool_call": [hook_script("a", 'print(json.dumps({"action": "block", "message": "native"}))')]})
    assert probe()["error"] == "native"
    configure({"pre_tool_call": [hook_script("b", 'print(json.dumps({"decision": "block"}))')]})
    assert probe()["error"] == "Blocked by a shell hook."
    configure({"pre_tool_call": [hook_script(
        "c", 'print(json.dumps({"decision": "modify", "tool_input": {"path": event["tool_input"]["path"] + ".bak"}}))')]})
    assert probe(path="notes.txt")["args"] == {"path": "notes.txt.bak"}


def test_the_matcher_limits_a_hook_to_matching_tools(configure, hook_script, probe):
    command = hook_script("block", 'print(json.dumps({"decision": "block", "reason": "no"}))')
    configure({"pre_tool_call": [{"command": command, "matcher": "probe|terminal"}]})
    assert probe("probe")["blocked"] is True
    assert probe("other")["ran"] is True
    # The whole name must match: "pro" does not select "probe".
    configure({"pre_tool_call": [{"command": command, "matcher": "pro"}]})
    assert probe("probe")["ran"] is True


def test_pre_llm_call_context_rides_the_user_message(configure, hook_script):
    configure({"pre_llm_call": [hook_script("ctx", 'print(json.dumps({"context": "Today is deploy day."}))')]})
    client = ScriptedClient([text_response("noted")])
    agent = build_agent(client=client)
    try:
        agent.run_conversation("what should I know?")
    finally:
        agent.close()
    system, user = client.calls[0]["messages"][0], client.calls[0]["messages"][-1]
    assert user["content"].startswith("what should I know?") and "Today is deploy day." in user["content"]
    assert "deploy day" not in system["content"]
    assert agent.messages[0]["content"] == "what should I know?"  # not stored


def test_observer_events_run_the_command(configure, hook_script, tmp_path):
    configure({"on_session_end": [hook_script("bye", '(here / "ended").write_text(event["extra"]["reason"])')]})
    agent = build_agent(client=ScriptedClient([text_response("hi")]))
    agent.run_conversation("hello")
    agent.close("user_quit")
    assert (tmp_path / "ended").read_text() == "user_quit"


# ── failure policy ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body", ["sys.exit(1)", "raise SystemExit(3)", 'print("Traceback: oops")', "import time; time.sleep(30)"],
    ids=["exit-1", "exit-3", "garbage-output", "timeout"],
)
def test_a_broken_hook_fails_open_by_default_and_closed_on_request(configure, hook_script, probe, body):
    command = hook_script("broken", body)
    configure({"pre_tool_call": [{"command": command, "timeout": 1}]})
    assert probe()["ran"] is True
    configure({"pre_tool_call": [{"command": command, "timeout": 1, "fail_closed": True}]})
    result = probe()
    assert result["blocked"] is True and "failed closed" in result["error"]


def test_a_command_that_does_not_exist_is_reported_not_raised(configure, probe):
    configure({"pre_tool_call": ["/no/such/hook-binary --flag"]})
    assert probe()["ran"] is True
    run = run_hook(ShellHook("pre_tool_call", "/no/such/hook-binary"), {})
    assert "could not start" in run.error and evaluate(ShellHook("pre_tool_call", "x", fail_closed=True), run)["action"] == "block"
    assert "cannot be parsed" in run_hook(ShellHook("pre_tool_call", "unbalanced 'quote"), {}).error


def test_fail_closed_applies_only_to_events_that_can_block(configure, hook_script):
    configure({"post_tool_call": [{"command": hook_script("x", "sys.exit(1)"), "fail_closed": True}]})
    assert configured_hooks()[0].fail_closed is False
    assert invoke_hook("post_tool_call", tool_name="probe", args={}) == []


def test_the_hook_timeout_stays_below_the_bus_timeout(configure, hook_script):
    configure({"pre_tool_call": [{"command": hook_script("slow", ""), "timeout": 120}]},
              plugins={"hook_callback_timeout": 5})
    registered, _ = register_shell_hooks()
    assert registered[0].timeout == 4.0  # the hook's own failure policy decides, not the bus timeout


# ── configuration ────────────────────────────────────────────────────────────────────────


def test_malformed_entries_are_skipped_and_the_rest_still_load(configure, hook_script, caplog):
    good = hook_script("good", "")
    configure({
        "pre_tool_call": [good, {"matcher": "x"}, {"command": good, "matcher": "("}, 42],
        "transform_tool_result": [good],  # needs a return value a shell command cannot give
        "no_such_event": [good],
    })
    assert [(hook.event, hook.command) for hook in configured_hooks()] == [("pre_tool_call", good)]
    assert "not an event a shell hook can handle" in caplog.text


def test_reloading_replaces_registrations_instead_of_stacking_them(configure, hook_script, tmp_path):
    command = hook_script("count", '(here / "count").open("a").write("x")')
    configure({"on_session_reset": [command]})
    get_plugin_manager().load_all()
    get_plugin_manager().load_all()
    invoke_hook("on_session_reset", session_id="s1", platform="cli")
    assert (tmp_path / "count").read_text() == "x"
    configure({})  # removed from config: gone from the bus
    assert not get_hook_bus().has("on_session_reset")


# ── the CLI ──────────────────────────────────────────────────────────────────────────────


def test_hooks_cli_lists_approves_tests_and_revokes(configure, hook_script, capsys, clite_home):
    command = hook_script("guard", 'print(json.dumps({"decision": "block", "reason": "blocked: " + event["tool_name"]}))')
    configure({"pre_tool_call": [{"command": command, "matcher": "terminal", "fail_closed": True}]}, approve=False)

    def cli(*argv, expect=0):
        assert main(list(argv)) == expect
        return capsys.readouterr().out

    listing = cli("hooks")
    assert "PENDING" in listing and command in listing and "tools matching /terminal/" in listing and "fail closed" in listing
    assert "1 configured hook(s) will not run until you approve them" in cli("doctor", expect=0)
    assert "re-run with --yes" in cli("hooks", "approve", expect=1)  # no terminal to confirm on
    assert "Approved 1 hook(s)" in cli("hooks", "approve", "--yes")
    assert "Nothing to approve." in cli("hooks", "approve")
    assert "approved" in cli("hooks", "list") and "PENDING" not in cli("hooks", "list")

    tried = cli("hooks", "test", "pre_tool_call")
    assert "exit 0" in tried and '"message": "blocked: terminal"' in tried
    assert "does not match tool 'read_file'" in cli("hooks", "test", "pre_tool_call", "--tool", "read_file")
    assert "No hooks are configured for on_session_end." in cli("hooks", "test", "on_session_end", expect=1)

    assert "Revoked 1 approval(s)." in cli("hooks", "revoke", command)
    assert "No matching approval." in cli("hooks", "revoke", "--all")
    assert "Say which command" in cli("hooks", "revoke", expect=2)
    assert "PENDING" in cli("hooks")


def test_no_hooks_configured(clite_home, capsys):
    assert main(["hooks"]) == 0
    assert "No shell hooks are configured" in capsys.readouterr().out
