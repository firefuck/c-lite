"""ChatSession and the slash commands every surface shares."""

from __future__ import annotations

import pytest

from clite.core.config import load_config
from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.runtime import ChatSession
from clite.runtime.commands import COMMAND_REGISTRY, command_catalog, commands_for, resolve_command, split_command
from clite.runtime.factory import default_toolsets
from clite.runtime.session import ACTION_NEW, ACTION_QUIT, ACTION_SUBMIT
from clite.runtime.slash import SLASH_HANDLERS
from clite.state import get_session_db


@pytest.fixture(autouse=True)
def mock_model(clite_home):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")


@pytest.fixture
def make_session(clite_home, tmp_path):
    created = []

    def factory(responses=None, **kwargs):
        client = ScriptedClient(list(responses or []), default=text_response("ok"))
        kwargs.setdefault("cwd", str(tmp_path))
        session = ChatSession(client=client, **kwargs)
        created.append(session)
        return session, client

    yield factory
    for session in created:
        session.close()


# ── the registry ─────────────────────────────────────────────────────────────────────────


def test_every_command_has_a_handler_and_every_handler_a_command():
    assert set(SLASH_HANDLERS) == {command.name for command in COMMAND_REGISTRY}
    names = [command.name for command in COMMAND_REGISTRY] + [a for c in COMMAND_REGISTRY for a in c.aliases]
    assert len(names) == len(set(names)), "command names and aliases must be unique"


def test_resolve_and_split():
    assert resolve_command("/reset").name == "new" and resolve_command("EXIT").name == "quit"
    assert resolve_command("nope") is None
    assert split_command("/model  mock:mock-2 --global") == ("model", "mock:mock-2 --global")
    assert split_command("just a prompt") == ("", "just a prompt")
    assert split_command("/ not a command") == ("", "/ not a command")
    assert split_command("//also not") == ("", "//also not")


def test_terminal_only_commands_are_hidden_from_messaging():
    assert "quit" in {c.name for c in commands_for("cli")}
    assert "quit" not in {c.name for c in commands_for("telegram")}


def test_platform_toolsets():
    config = load_config()
    assert default_toolsets("cli", config) == ["clite-cli"]
    assert default_toolsets("cron", config) == ["clite-cron"]
    assert default_toolsets("telegram", config) == ["clite-gateway"]
    config["platform_toolsets"] = {"telegram": ["file"]}
    assert default_toolsets("telegram", config) == ["file"]


# ── turns and input dispatch ─────────────────────────────────────────────────────────────


def test_input_is_a_prompt_or_a_command(make_session):
    session, client = make_session([text_response("hello there")])
    turn = session.handle_input("hi")
    assert turn.final_response == "hello there"
    status = session.handle_input("/status")
    assert "mock-1 via mock" in status.text and status.data["message_count"] == 2
    assert len(client.calls) == 1  # the command did not reach the model
    assert "Unknown command: /nonsense" in session.handle_input("/nonsense").text


def test_new_keeps_the_model_and_starts_an_empty_session(make_session):
    session, _ = make_session()
    session.submit("first")
    old_id = session.session_id
    session.run_slash("/model mock:mock-9")
    result = session.run_slash("/new")
    assert result.action == ACTION_NEW and session.session_id != old_id
    assert session.agent.messages == [] and session.agent.route.model == "mock-9"
    assert get_session_db().get_session(old_id)["end_reason"] == "new_session"


def test_resume_by_title_or_prefix(make_session):
    session, _ = make_session()
    session.submit("remember the blue door")
    first = session.session_id
    session.run_slash("/title Blue door")
    session.run_slash("/new")
    assert "No session matches" in session.run_slash("/resume nothing-like-this").text
    resumed = session.run_slash("/resume Blue door")
    assert resumed.action == ACTION_NEW and session.session_id == first
    assert len(session.agent.messages) == 2
    assert get_session_db().get_session(first)["ended_at"] is None  # live again
    assert "Blue door" in session.run_slash("/sessions").text


def test_undo_and_retry(make_session):
    session, client = make_session([text_response("one"), text_response("two"), text_response("two, second try"),
                                    text_response("two, again")])
    session.submit("first question")
    session.submit("second question")
    assert "second question" in session.run_slash("/undo").text
    assert [m["content"] for m in session.agent.messages] == ["first question", "one"]
    assert [m["content"] for m in get_session_db().get_messages(session.session_id)] == ["first question", "one"]

    session.submit("second question")
    retried = session.handle_input("/retry")
    assert retried.final_response == "two, again"
    assert [m["content"] for m in session.agent.messages][-2:] == ["second question", "two, again"]
    session.run_slash("/new")
    assert session.run_slash("/undo").text == "Nothing to undo."


def test_model_switch_for_the_session_or_as_the_default(make_session, clite_home):
    session, client = make_session()
    assert "Model: mock-1" in session.run_slash("/model").text
    session.run_slash("/model mock-2")
    assert session.agent.route.model == "mock-2" and load_config()["model"]["default"] == "mock-1"
    session.submit("hi")
    assert client.calls[-1]["route"].model == "mock-2"
    assert "Model: mock-2" in client.calls[-1]["messages"][0]["content"]

    saved = session.run_slash("/model mock:mock-3 --global")
    assert "saved as default" in saved.text and load_config()["model"]["default"] == "mock-3"
    failed = session.run_slash("/model anthropic:claude-x")
    assert failed.data["success"] is False and session.agent.route.model == "mock-3"


def test_yolo_and_reasoning_are_session_settings(make_session):
    session, client = make_session()
    assert "OFF" in session.run_slash("/yolo").text and session.agent.approval_mode == "off"
    assert "back on" in session.run_slash("/yolo").text and session.agent.approval_mode is None
    assert "high" in session.run_slash("/reasoning high").text
    session.submit("think")
    assert client.calls[-1]["params"].reasoning_effort == "high"
    assert "Unknown level" in session.run_slash("/reasoning extreme").text
    session.run_slash("/reasoning default")
    assert session.agent.reasoning_effort == ""


def test_tools_can_be_listed_and_switched(make_session):
    session, _ = make_session()
    assert "terminal" in session.agent.tool_names
    listing = session.run_slash("/tools").text
    assert "terminal" in listing and "on " in listing
    session.run_slash("/tools disable terminal")
    assert "terminal" not in session.agent.tool_names and load_config()["disabled_toolsets"] == ["terminal"]
    session.run_slash("/tools enable terminal")
    assert "terminal" in session.agent.tool_names
    assert "Unknown toolset" in session.run_slash("/tools disable imaginary").text


def test_reload_picks_up_config_and_keeps_the_conversation(make_session, clite_home):
    session, client = make_session()
    session.submit("before reload")
    session_id = session.session_id
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-reloaded\ntoolsets: [file]\n")
    assert "mock-reloaded" in session.run_slash("/reload").text
    assert session.session_id == session_id and len(session.agent.messages) == 2
    assert session.agent.tool_names == {"read_file", "write_file", "patch", "search_files"}
    session.submit("after reload")
    assert [m["role"] for m in client.calls[-1]["messages"]] == ["system", "user", "assistant", "user"]


def test_compress_stop_and_steer_report_when_there_is_nothing_to_do(make_session):
    session, _ = make_session()
    assert "Nothing to compress" in session.run_slash("/compress").text
    assert session.run_slash("/stop").text == "Nothing is running."
    assert "Nothing is running" in session.run_slash("/steer go faster").text
    assert session.run_slash("/quit").action == ACTION_QUIT


def test_informational_commands(make_session, clite_home):
    session, _ = make_session([tool_call_response(("memory", {"action": "add", "target": "memory", "content": "Staging is db-7"})),
                               text_response("noted")])
    session.submit("remember staging is db-7")
    assert "Staging is db-7" in session.run_slash("/memory").text
    assert "Output tokens" in session.run_slash("/usage").text
    assert "user: remember staging" in session.run_slash("/history").text
    assert "[tool memory]" in session.run_slash("/history").text
    assert "stable" in session.run_slash("/debug").text and "volatile" in session.run_slash("/debug").text
    assert "audit-log" in session.run_slash("/plugins").text
    assert "skill-authoring" in session.run_slash("/skills").text
    assert session.run_slash("/skills zzz-nothing").text == "No skills match."
    assert "mock" in session.run_slash("/provider").text and "needs ANTHROPIC_API_KEY" in session.run_slash("/provider").text
    assert "compression.threshold = 0.5" in session.run_slash("/config compression.threshold").text
    assert "is not set" in session.run_slash("/config no.such.key").text
    assert "Active profile: default" in session.run_slash("/profile").text
    assert "No scheduled jobs" in session.run_slash("/cron").text
    help_text = session.run_slash("/help").text
    assert "/model [provider:model] [--global]" in help_text and "Skills:" in help_text


def test_cli_only_commands_are_refused_on_messaging_platforms(make_session):
    session, _ = make_session(platform="telegram")
    assert "only available in the terminal" in session.run_slash("/quit").text
    assert "/quit" not in session.run_slash("/help").text


# ── plugin, quick and skill commands ─────────────────────────────────────────────────────


def test_skill_command_becomes_a_user_message(make_session, clite_home):
    skill = clite_home / "skills" / "release-notes"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: release-notes\ndescription: Write release notes.\n---\n\nList merged PRs.\n")
    session, client = make_session([text_response("Here are the notes.")])
    expanded = session.run_slash("/release-notes for v2.1")
    assert expanded.action == ACTION_SUBMIT and expanded.data == {"skill": "release-notes"}

    turn = session.handle_input("/release-notes for v2.1")
    assert turn.final_response == "Here are the notes."
    sent = client.calls[0]["messages"]
    assert "List merged PRs." in sent[1]["content"] and "for v2.1" in sent[1]["content"]
    assert "List merged PRs." not in sent[0]["content"]  # the system prompt was not touched


def test_quick_commands_run_without_the_model(make_session, clite_home):
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\n"
        "quick_commands:\n"
        "  hello: {type: exec, command: 'echo quick-output'}\n"
        "  st: {type: alias, target: '/status'}\n"
        "  loop: {type: alias, target: '/loop'}\n"
        "  odd: {type: mystery}\n"
    )
    session, client = make_session()
    assert session.run_slash("/hello").text == "quick-output"
    assert "mock-1 via mock" in session.run_slash("/st").text
    assert "invalid alias" in session.run_slash("/loop").text
    assert "unknown type" in session.run_slash("/odd").text
    assert client.calls == []
    assert {"hello", "st"} <= {entry["name"] for entry in command_catalog("cli")}


def test_plugin_commands_and_their_failures(make_session, clite_home):
    plugin = clite_home / "plugins" / "demo"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: demo\n")
    (plugin / "__init__.py").write_text(
        "def register(ctx):\n"
        "    ctx.register_command('shout', lambda args, session: args.upper() + ' in ' + session.platform)\n"
        "    ctx.register_command('crash', lambda args, session: 1 / 0)\n"
        "    ctx.register_command('status', lambda args, session: 'a plugin cannot shadow a built-in')\n"
    )
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\nplugins:\n  enabled: [demo]\n")
    session, _ = make_session()
    assert session.run_slash("/shout hello").text == "HELLO in cli"
    assert "ZeroDivisionError" in session.run_slash("/crash").text
    assert "mock-1 via mock" in session.run_slash("/status").text
    kinds = {entry["name"]: entry["kind"] for entry in command_catalog("cli")}
    assert kinds["shout"] == "plugin" and kinds["status"] == "builtin"
