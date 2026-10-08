"""ChatSession and the slash commands every surface shares."""

from __future__ import annotations

import threading
import time

import pytest

from clite.core.config import load_config
from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.runtime import ChatSession
from clite.runtime.commands import (
    COMMAND_REGISTRY,
    command_catalog,
    commands_for,
    resolve_command,
    split_command,
)
from clite.runtime.factory import default_toolsets
from clite.runtime.session import ACTION_NEW, ACTION_QUIT, ACTION_SUBMIT, Turn
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
    session, client = make_session(
        [
            text_response("one"),
            text_response("two"),
            text_response("two, second try"),
            text_response("two, again"),
        ]
    )
    session.submit("first question")
    session.submit("second question")
    assert "second question" in session.run_slash("/undo").text
    assert [m["content"] for m in session.agent.messages] == ["first question", "one"]
    assert [m["content"] for m in get_session_db().get_messages(session.session_id)] == [
        "first question",
        "one",
    ]

    session.submit("second question")
    retried = session.handle_input("/retry")
    assert retried.final_response == "two, again"
    assert [m["content"] for m in session.agent.messages][-2:] == ["second question", "two, again"]
    session.run_slash("/new")
    assert session.run_slash("/undo").text == "Nothing to undo."


def test_undo_history_and_retry_look_past_messages_the_agent_wrote_itself(make_session):
    session, client = make_session(
        [
            text_response("The answer is ", finish_reason="length"),
            text_response("forty-two."),
            text_response("forty-two, on a second try."),
        ]
    )
    assert session.submit("what is the answer?").final_response == "The answer is forty-two."
    internal = [m for m in session.agent.messages if m.get("display_kind") == "internal"]
    assert len(internal) == 1 and "cut off" in internal[0]["content"]

    history = session.run_slash("/history").text
    assert "what is the answer?" in history and "forty-two." in history and "cut off" not in history

    # /retry resends what the user said, not the agent's own "continue" request.
    retried = session.handle_input("/retry")
    assert retried.final_response == "forty-two, on a second try."
    assert [m["content"] for m in session.agent.messages] == [
        "what is the answer?",
        "forty-two, on a second try.",
    ]


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
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-reloaded\ntoolsets: [file]\n"
    )
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
    session, _ = make_session(
        [
            tool_call_response(
                ("memory", {"action": "add", "target": "memory", "content": "Staging is db-7"})
            ),
            text_response("noted"),
        ]
    )
    session.submit("remember staging is db-7")
    assert "Staging is db-7" in session.run_slash("/memory").text
    assert "Output tokens" in session.run_slash("/usage").text
    assert "user: remember staging" in session.run_slash("/history").text
    assert "[tool memory]" in session.run_slash("/history").text
    assert "stable" in session.run_slash("/debug").text and "volatile" in session.run_slash("/debug").text
    assert "audit-log" in session.run_slash("/plugins").text
    assert "skill-authoring" in session.run_slash("/skills").text
    assert session.run_slash("/skills zzz-nothing").text == "No skills match."
    assert (
        "mock" in session.run_slash("/provider").text
        and "needs ANTHROPIC_API_KEY" in session.run_slash("/provider").text
    )
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
    (skill / "SKILL.md").write_text(
        "---\nname: release-notes\ndescription: Write release notes.\n---\n\nList merged PRs.\n"
    )
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
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\nplugins:\n  enabled: [demo]\n"
    )
    session, _ = make_session()
    assert session.run_slash("/shout hello").text == "HELLO in cli"
    assert "ZeroDivisionError" in session.run_slash("/crash").text
    assert "mock-1 via mock" in session.run_slash("/status").text
    kinds = {entry["name"]: entry["kind"] for entry in command_catalog("cli")}
    assert kinds["shout"] == "plugin" and kinds["status"] == "builtin"


# ── the F3-T4 slash commands ──────────────────────────────────────────────────────────────


def test_branch_copies_the_conversation_without_provider_data_and_links_the_parent(make_session):
    session, _ = make_session([text_response("first answer")])
    session.submit("first question")
    parent = session.session_id
    session.run_slash("/title Blue door")
    session.agent.messages[1]["provider_data"] = {"signed": "reasoning"}
    original = list(session.agent.messages)

    result = session.run_slash("/branch")
    assert result.action == ACTION_NEW
    branch = session.session_id
    assert branch != parent
    row = get_session_db().get_session(branch)
    assert row["parent_session_id"] == parent
    assert row["title"] == "Blue door (branch)"

    # The active messages were copied, without provider_data. The branch has its own row
    # ids (the parent's must not be written back); the parent's rows are untouched.
    copied = session.agent.messages
    assert [m["content"] for m in copied] == [m["content"] for m in original]
    assert all("provider_data" not in m for m in copied)
    stored = get_session_db().get_messages(branch)
    assert all(row.get("provider_data") is None for row in stored)
    assert len(stored) == len(copied)
    assert [row["_row_id"] for row in stored] != [m.get("_row_id") for m in original]

    # The parent is untouched.
    assert get_session_db().get_session(parent)["end_reason"] == "branched"


def test_branch_takes_a_title_and_reports_when_there_is_nothing_to_branch(make_session):
    session, _ = make_session()
    assert "Nothing to branch" in session.run_slash("/branch").text
    session.submit("hello")
    session.run_slash("/branch Explore option B")
    assert get_session_db().get_session(session.session_id)["title"] == "Explore option B"


def test_queue_notes_a_message_for_the_running_turn(make_session):
    session, _ = make_session()
    assert "Nothing is running" in session.run_slash("/queue hello").text
    session.agent._turn_lock.acquire()  # pretend a turn is running
    try:
        assert "Queued" in session.run_slash("/queue do this next").text
        assert session.agent.pending_notes() == ["do this next"]
    finally:
        session.agent._turn_lock.release()
    assert "Usage: /queue" in session.run_slash("/queue").text


def test_background_runs_a_turn_in_a_separate_session(make_session):
    session, _ = make_session([text_response("separate answer")])
    before = session.session_id
    result = session.run_slash("/background summarise the news")
    assert "separate answer" in result.text
    assert result.data["session_id"] != before
    assert session.session_id == before  # this conversation was not touched
    assert session.agent.messages == []
    assert "Usage: /background" in session.run_slash("/background").text


def test_export_writes_the_transcript_as_markdown_or_json(make_session, tmp_path):
    session, _ = make_session([text_response("the answer")])
    session.submit("the question")
    markdown = tmp_path / "transcript.md"
    assert str(markdown) in session.run_slash(f"/export {markdown}").text
    body = markdown.read_text()
    assert body.startswith("# ") and "## User" in body and "the question" in body and "the answer" in body

    data = tmp_path / "transcript.json"
    session.run_slash(f"/export {data}")
    import json

    payload = json.loads(data.read_text())
    assert payload["session_id"] == session.session_id
    assert payload["messages"][0] == {"role": "user", "content": "the question"}

    assert "Could not export" in session.run_slash(f"/export {tmp_path / 'notes.txt'}").text


def test_export_without_a_path_writes_into_the_working_directory(make_session, tmp_path):
    session, _ = make_session([text_response("hi")])
    session.submit("hello")
    result = session.run_slash("/export")
    from pathlib import Path

    written = Path(result.text.rsplit(" ", 1)[-1])
    assert written.parent == Path(session.agent.cwd) and written.is_file()


def test_context_breaks_the_window_into_prompt_tools_and_history(make_session):
    session, _ = make_session([text_response("answer")])
    session.submit("question")
    text = session.run_slash("/context").text
    assert "Context window:" in text
    assert "System prompt:" in text and "Tool schemas:" in text and "History:" in text
    assert "stable" in text and "volatile" in text  # the prompt tiers are named


def test_tasks_shows_the_sessions_todo_list(make_session):
    session, _ = make_session()
    assert "No tasks" in session.run_slash("/tasks").text
    session.agent.todos.write(
        [
            {"id": "1", "content": "wire the tests", "status": "in_progress"},
            {"id": "2", "content": "shipping", "status": "completed"},
        ]
    )
    text = session.run_slash("/tasks").text
    assert "wire the tests" in text and "[>]" in text
    assert "shipping" in text and "[x]" in text
    assert session.run_slash("/tasks").data["total"] == 2


def test_hooks_lists_registered_hooks_and_flags_pending_ones(make_session, clite_home):
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\n"
        "hooks:\n"
        "  on_session_end:\n"
        "    - command: 'notify-send done'\n"
        "  pre_tool_call:\n"
        "    - command: '~/.clite/hooks/guard.py'\n"
    )
    from clite.plugins.shell_hooks import ShellHook, approve_hooks, configured_hooks

    approve_hooks([ShellHook("on_session_end", "notify-send done")])
    session, _ = make_session()
    text = session.run_slash("/hooks").text
    assert "approved" in text and "notify-send done" in text
    assert "PENDING" in text and "guard.py" in text
    assert "clite hooks approve" in text
    assert len(configured_hooks()) == 2


def test_hooks_reports_when_none_are_configured(make_session):
    session, _ = make_session()
    assert "No shell hooks are configured" in session.run_slash("/hooks").text


def test_pin_and_archive_mark_the_session(make_session):
    session, _ = make_session()
    assert "pinned" in session.run_slash("/pin").text
    assert get_session_db().get_session(session.session_id)["pinned"] == 1
    assert "archived" in session.run_slash("/archive").text
    assert get_session_db().get_session(session.session_id)["archived"] == 1
    assert session.session_id not in {row["id"] for row in get_session_db().list_sessions()}


def test_verbose_sets_the_tool_progress_level_for_the_session(make_session, clite_home):
    session, _ = make_session()
    assert "all" in session.run_slash("/verbose").text
    assert "off" in session.run_slash("/verbose off").text
    assert session.tool_progress == "off"
    assert load_config()["display"]["tool_progress"] == "off"
    assert "Unknown level" in session.run_slash("/verbose loud").text
    assert session.run_slash("/help").text  # the catalog still lists it


def test_skin_shows_and_sets_the_theme(make_session, clite_home):
    session, _ = make_session()
    assert "default" in session.run_slash("/skin").text
    result = session.run_slash("/skin mono")
    assert result.data["skin"] == "mono" and session.skin == "mono"
    assert load_config()["display"]["skin"] == "mono"


def test_logs_shows_the_last_lines_of_the_agent_log(make_session, clite_home):
    session, _ = make_session()
    assert "No log yet" in session.run_slash("/logs").text
    logs = clite_home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "agent.log").write_text("\n".join(f"line {n}" for n in range(1, 11)) + "\n")
    assert session.run_slash("/logs 3").text.splitlines() == ["line 8", "line 9", "line 10"]


def test_copy_puts_the_last_answer_on_the_clipboard(make_session):
    session, _ = make_session([text_response("copy me")])
    assert "Nothing to copy" in session.run_slash("/copy").text
    session.submit("say something")
    result = session.run_slash("/copy")
    assert result.action == "clipboard" and result.text == "copy me"


def test_insights_slash_command(make_session):
    session, _ = make_session()
    result = session.run_slash("/insights")
    assert "Usage Insights" in result.text
    assert "Sessions:" in result.text

    # With days argument
    result_7 = session.run_slash("/insights 7")
    assert "Past 7 Days" in result_7.text


def test_the_new_commands_are_available_on_messaging_platforms_except_the_terminal_only_ones(make_session):
    session, _ = make_session(platform="telegram")
    assert "only available in the terminal" in session.run_slash("/skin").text
    assert "only available in the terminal" in session.run_slash("/logs").text
    assert "only available in the terminal" in session.run_slash("/copy").text
    assert session.run_slash("/tasks").action is None  # a non-terminal command runs everywhere


# ── image attachments (F2-T6) ─────────────────────────────────────────────────────────────


def _png(path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")
    return str(path)


def test_the_image_command_queues_a_file_for_the_next_message(make_session, tmp_path):
    session, client = make_session([text_response("nice picture")])
    result = session.run_slash(f"/image {_png(tmp_path / 'shot.png')}")
    assert "queued" in result.text.lower()
    assert session.pending_image_count == 1

    session.handle_input("what is this?")
    user_message = client.calls[0]["messages"][1]
    assert user_message["content"][0] == {"type": "text", "text": "what is this?"}
    assert user_message["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert session.pending_image_count == 0  # consumed by the turn


def test_the_image_command_with_a_caption_submits_in_one_step(make_session, tmp_path):
    session, client = make_session([text_response("ok")])
    outcome = session.handle_input(f"/image {_png(tmp_path / 'a.png')} what colour is it?")
    assert not isinstance(outcome, type(None)) and client.calls
    content = client.calls[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "what colour is it?"}
    assert content[1]["type"] == "image_url"


def test_the_image_command_reports_a_missing_file(make_session, tmp_path):
    session, _ = make_session()
    result = session.run_slash(f"/image {tmp_path / 'gone.png'}")
    assert "no file at" in result.text
    assert session.pending_image_count == 0


def test_submit_attaches_images_passed_directly(make_session, tmp_path):
    session, client = make_session([text_response("ok")])
    session.submit("look", images=[_png(tmp_path / "direct.png")])
    assert client.calls[0]["messages"][1]["content"][1]["type"] == "image_url"


def test_an_image_command_is_not_available_without_a_path(make_session):
    session, _ = make_session()
    assert "Usage: /image" in session.run_slash("/image").text
    assert "Usage: /image" in session.run_slash("/attach").text  # the alias works too


# ── busy input: the queue the REPL, RPC and gateway share (F3-T1) ──────────────────────────


class BlockingClient(ScriptedClient):
    """A client whose first call blocks until the test releases it.

    It stops the thread that is on a turn so a second submit arrives while the session is
    busy — the situation ``display.busy_input_mode`` is about.
    """

    def __init__(self) -> None:
        super().__init__([], default=text_response("ok"))
        self.started = threading.Event()
        self.release = threading.Event()
        self._blocked = True

    def complete(self, *args, **kwargs):
        if self._blocked:
            self._blocked = False
            self.started.set()
            self.release.wait(timeout=5)
        return super().complete(*args, **kwargs)


def _queue_for(session: ChatSession, run, *, mode: str = "interrupt"):
    """A TurnQueue bound to a session, with ``display.busy_input_mode`` set for the test."""
    # The mode is read from the config file, the way a real surface reads it.
    from clite.core.constants import get_home
    from clite.runtime.session import TurnQueue

    config = get_home() / "config.yaml"
    config.write_text(f"model:\n  provider: mock\n  default: mock-1\ndisplay:\n  busy_input_mode: {mode}\n")
    return TurnQueue(session, run, thread_name="clite-test-turn")


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def _record(session: ChatSession, ran: list[str]):
    """A ``run`` callback that actually runs the turn, recording the text in order."""

    def run(turn: Turn) -> None:
        ran.append(turn.text)
        session.submit(turn.text)

    return run


def test_a_line_sent_while_busy_is_queued_and_runs_after(clite_home, tmp_path):
    client = BlockingClient()
    ran: list[str] = []
    session = ChatSession(client=client, cwd=str(tmp_path))
    try:
        turns = _queue_for(session, _record(session, ran), mode="queue")
        assert turns.submit(Turn(text="first")) == "started"
        assert client.started.wait(timeout=5)
        assert turns.busy
        assert turns.submit(Turn(text="second")) == "queued"
        assert turns.pending == 1
        client.release.set()
        _wait_until(lambda: not turns.busy)
        assert ran == ["first", "second"]  # in order, the running turn first
    finally:
        client.release.set()
        turns.join(timeout=5)
        session.close("test")


def test_a_line_sent_while_busy_interrupts_when_the_mode_says_so(clite_home, tmp_path):
    client = BlockingClient()
    ran: list[str] = []
    session = ChatSession(client=client, cwd=str(tmp_path))
    try:
        turns = _queue_for(session, _record(session, ran), mode="interrupt")
        turns.submit(Turn(text="first"))
        assert client.started.wait(timeout=5)
        assert turns.submit(Turn(text="second")) == "queued"
        assert session.agent.interrupt_event.is_set()  # the running turn was told to stop
        client.release.set()
        _wait_until(lambda: not turns.busy)
        assert ran == ["first", "second"]
    finally:
        client.release.set()
        turns.join(timeout=5)
        session.close("test")


def test_a_line_sent_while_busy_steers_without_interrupting(clite_home, tmp_path):
    client = BlockingClient()
    session = ChatSession(client=client, cwd=str(tmp_path))
    turns = _queue_for(session, _record(session, []), mode="steer")
    try:
        turns.submit(Turn(text="first"))
        assert client.started.wait(timeout=5)
        assert turns.submit(Turn(text="aim left")) == "steered"
        assert not session.agent.interrupt_event.is_set()
        assert turns.pending == 0  # steering does not queue a new turn
    finally:
        client.release.set()
        turns.join(timeout=5)
        session.close("test")


def test_a_line_sent_while_busy_is_rejected_when_the_mode_says_so(clite_home, tmp_path):
    client = BlockingClient()
    session = ChatSession(client=client, cwd=str(tmp_path))
    turns = _queue_for(session, _record(session, []), mode="reject")
    try:
        turns.submit(Turn(text="first"))
        assert client.started.wait(timeout=5)
        assert turns.submit(Turn(text="second")) == "rejected"
        assert turns.pending == 0
    finally:
        client.release.set()
        turns.join(timeout=5)
        session.close("test")


def test_turn_cost_with_cache_read_and_write_calculated_from_profile_rates(make_session, clite_home):
    from clite.providers.base import ModelPricing, ProviderProfile
    from clite.providers.registry import register_provider
    from clite.providers.transports.types import Usage

    profile = ProviderProfile(
        name="test-priced-prov",
        api_mode="mock",
        auth_type="none",
        model_pricing={
            "priced-model": ModelPricing(
                input_cost_per_million=3.0,
                output_cost_per_million=15.0,
                cache_read_cost_per_million=0.30,
                cache_write_cost_per_million=3.75,
            )
        },
    )
    register_provider(profile)
    (clite_home / "config.yaml").write_text("model:\n  provider: test-priced-prov\n  default: priced-model\n")

    # input: 10,000 ($0.03), output: 2,000 ($0.03), cache_read: 50,000 ($0.015), cache_write: 20,000 ($0.075) -> $0.150
    turn_usage = Usage(
        input_tokens=10_000,
        output_tokens=2_000,
        cache_read_tokens=50_000,
        cache_write_tokens=20_000,
    )
    session, _ = make_session([text_response("answer", usage=turn_usage)])
    session.submit("calculate something")

    # In session DB:
    row = get_session_db().get_session(session.session_id)
    assert row["estimated_cost_usd"] == pytest.approx(0.15)

    # In /usage:
    usage_text = session.run_slash("/usage").text
    assert "Estimated cost:     $0.1500" in usage_text


def test_model_without_pricing_yields_unknown_in_usage_and_null_in_rpc(make_session):
    # Default model mock-1 has no pricing declared
    session, _ = make_session([text_response("answer")])
    session.submit("hi")

    # In session DB: estimated_cost_usd is None
    row = get_session_db().get_session(session.session_id)
    assert row["estimated_cost_usd"] is None

    # In /usage: shows unknown
    usage_text = session.run_slash("/usage").text
    assert "Estimated cost:     unknown" in usage_text or "tidak diketahui" in usage_text
