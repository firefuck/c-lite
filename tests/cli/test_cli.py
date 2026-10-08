"""The command-line surface: subcommands in process, the REPL with scripted input, and the
installed entry point as a real subprocess."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import threading

import pytest

from clite.cli.display import Display, load_skin
from clite.cli.main import main
from clite.cli.repl import Repl
from clite.core.config import load_config
from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.runtime.presentation import result_failed, tool_preview
from clite.state import get_session_db

MOCK = "model:\n  provider: mock\n  default: mock-1\n"


@pytest.fixture
def cli(clite_home, capsys):
    (clite_home / "config.yaml").write_text(MOCK)

    def run(*argv, expect=0):
        code = main([str(arg) for arg in argv])
        captured = capsys.readouterr()
        assert code == expect, f"exit {code}\nstdout: {captured.out}\nstderr: {captured.err}"
        return captured.out

    return run


# ── chat ─────────────────────────────────────────────────────────────────────────────────


def test_single_query_prints_only_the_answer(cli):
    assert cli("-q", "hello there") == "You said: hello there\n"
    assert cli("chat", "-q", "same thing") == "You said: same thing\n"


def test_single_query_json_and_exit_code(cli, capsys):
    payload = json.loads(cli("-q", "hi", "--json"))
    assert (
        payload["final_response"] == "You said: hi"
        and payload["completed"] is True
        and payload["provider"] == "mock"
    )
    assert main(["-q", "!error 400"]) == 1  # a failed turn is a failing exit code
    assert "400" in capsys.readouterr().out


def test_single_query_runs_tools_and_reports_progress_on_stderr(cli, tmp_path, capsys):
    (tmp_path / "data.txt").write_text("forty-two\n")
    assert main(["-q", '!read_file {"path": "data.txt"}']) == 0
    captured = capsys.readouterr()
    assert "forty-two" in captured.out
    assert (
        "✓ read_file data.txt" in captured.err and "✓" not in captured.out
    )  # progress never pollutes stdout


def test_single_query_attaches_an_image_with_the_flag(cli, tmp_path, capsys):
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")
    out = cli("-q", "what is this?", "--image", str(image))
    # The mock provider echoes the caption it received; the picture travelled as a content part.
    assert out == "You said: what is this?\n"
    assert main(["-q", "hi", "--image", str(tmp_path / "missing.png")]) == 1
    assert "no file at" in capsys.readouterr().err


def test_single_query_refuses_dangerous_commands_with_nobody_to_ask(cli, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    out = cli("-q", '!terminal {"command": "rm -rf ./victim"}')
    assert "no one to ask" in out and victim.exists()
    cli("-q", '!terminal {"command": "rm -rf ./victim"}', "--yolo")
    assert not victim.exists()


def test_model_and_toolset_flags(cli):
    payload = json.loads(cli("-q", "hi", "--json", "-m", "mock:mock-9"))
    assert payload["model"] == "mock-9"
    assert "unknown directive or tool 'terminal'" in cli("-q", '!terminal {"command": "ls"}', "-t", "file")


def test_resume_and_continue(cli):
    cli("-q", "remember the red door")
    session_id = get_session_db().list_sessions()[0]["id"]
    payload = json.loads(cli("-q", "and now?", "--json", "--resume", session_id[:13]))
    assert payload["session_id"] == session_id
    assert json.loads(cli("-q", "again", "--json", "-c"))["session_id"] == session_id
    assert get_session_db().count_messages(session_id) == 6
    cli("-q", "x", "--resume", "no-such-session", expect=1)


def test_unconfigured_install_explains_what_to_do(clite_home, capsys):
    assert main(["-q", "hi"]) == 1
    assert "clite setup" in capsys.readouterr().err


# ── the REPL ─────────────────────────────────────────────────────────────────────────────


def _repl(lines, responses=None, **options):
    feed = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError from None

    out = io.StringIO()
    client = ScriptedClient(list(responses or []), default=text_response("ok"))
    images = options.pop("images", None)
    repl = Repl(
        display=Display(stream=out, color=False), input_fn=fake_input, images=images, client=client, **options
    )
    assert repl.run() == 0
    return out.getvalue(), client


def test_repl_session(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    out, client = _repl(
        ["hello", "", "/status", "/nonsense", "/quit", "never reached"],
        [text_response("Hi! How can I help?")],
    )
    assert "C-lite 0.1.0" in out and "mock-1 via mock" in out
    assert "Hi! How can I help?" in out
    assert "Unknown command: /nonsense" in out and "Goodbye." in out
    assert "Resume this session with: clite chat --resume" in out
    assert len(client.calls) == 1  # the empty line and the commands did not reach the model


def test_repl_shows_tools_and_asks_for_approval(clite_home, tmp_path):
    (clite_home / "config.yaml").write_text(MOCK)
    target = tmp_path / "junk"
    target.mkdir()
    out, _ = _repl(
        ["clean up", "s", "clean again"],  # "s" answers the approval prompt: approve for this session
        [
            tool_call_response(("terminal", {"command": f'rm -rf "{target.as_posix()}"'})),
            text_response("Done."),
            tool_call_response(("terminal", {"command": f'rm -rf "{target.as_posix()}"'})),
            text_response("Done again."),
        ],
    )
    assert "needs your approval" in out and f'rm -rf "{target.as_posix()}"' in out
    assert out.count("needs your approval") == 1  # the second identical command was covered by "session"
    assert "✓ terminal" in out and "Done again." in out and not target.exists()


def test_repl_clarify_by_number_and_eof_exits(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    out, client = _repl(
        ["deploy", "2"],
        [
            tool_call_response(("clarify", {"question": "Where to?", "choices": ["staging", "production"]})),
            text_response("Deploying to production."),
        ],
    )
    assert "Where to?" in out and "2. production" in out and "Deploying to production." in out
    assert json.loads(client.calls[1]["messages"][-1]["content"])["answer"] == "production"


def test_the_copy_command_puts_the_last_answer_on_the_clipboard(clite_home, monkeypatch):
    (clite_home / "config.yaml").write_text(MOCK)
    copied = []
    monkeypatch.setattr(
        "clite.cli.clipboard.copy_to_clipboard", lambda text, stream=None: copied.append(text) or True
    )
    out, _ = _repl(["hello"], [text_response("You said: hello")])
    assert copied == []  # nothing was copied yet
    out, _ = _repl(["/copy", "/quit"])
    assert "Nothing to copy" in out


def test_the_skin_command_changes_the_theme_for_the_session(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    out, _ = _repl(["/skin mono"])
    assert "Skin set to: mono" in out
    assert load_config()["display"]["skin"] == "mono"


def test_display_helpers(clite_home):
    assert tool_preview("terminal", {"command": "echo   hi\nthere", "timeout": 5}) == "echo hi there"
    assert tool_preview("unknown_tool", {"n": 3, "query": "first string wins"}) == "first string wins"
    assert len(tool_preview("terminal", {"command": "x" * 200})) == 70
    assert (
        result_failed('{"error": "nope"}')
        and not result_failed('{"output": "fine"}')
        and not result_failed("plain")
    )
    (clite_home / "skins").mkdir()
    (clite_home / "skins" / "ocean.yaml").write_text("prompt: '~> '\ntool: blue\nnot_a_key: ignored\n")
    skin = load_skin("ocean")
    assert skin["prompt"] == "~> " and skin["tool"] == "blue" and "not_a_key" not in skin
    assert load_skin("missing")["prompt"] == load_skin("default")["prompt"]
    out = io.StringIO()
    display = Display(stream=out, color=True, skin="ocean")
    display.tool_done("terminal", {"command": "ls"}, '{"error": "x"}', 0.25)
    assert "\x1b[34m" in out.getvalue() and "✗ terminal ls" in out.getvalue()


# ── classic REPL input: multi-line, paste, completion, the stdlib fallback (F3-T1) ─────────


def test_multi_line_input_with_a_trailing_backslash_reaches_the_model_as_one_message(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    out, client = _repl(["first part \\", "second part", "/quit"], [text_response("ok")])
    assert len(client.calls) == 1  # the two lines were one message, not two
    sent = client.calls[0]["messages"][1]["content"]
    assert sent == "first part\nsecond part"
    assert "\\" not in sent


def test_bracketed_paste_arrives_as_one_message(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    pasted = "\x1b[200~line one\nline two\nline three\x1b[201~"
    _, client = _repl([pasted, "/quit"], [text_response("ok")])
    assert len(client.calls) == 1
    assert client.calls[0]["messages"][1]["content"] == "line one\nline two\nline three"


def test_the_stdlib_reader_handles_multi_line_and_paste_without_prompt_toolkit():
    from clite.cli.input import PASTE_END, PASTE_START, StdlibReader, needs_continuation

    assert needs_continuation("keep going \\") and not needs_continuation("closing \\\\")

    lines = iter(["hello \\", "world"])
    reader = StdlibReader(lambda prompt="": next(lines))
    assert reader.read_message("> ") == "hello\nworld"

    lines = iter([f"{PASTE_START}a\nb{PASTE_END}"])
    assert StdlibReader(lambda prompt="": next(lines)).read_message("> ") == "a\nb"

    def eof(prompt=""):
        raise EOFError

    assert StdlibReader(eof).read_message("> ") is None


def test_the_reader_is_the_standard_library_one_when_input_is_injected():
    from clite.cli.input import StdlibReader, make_reader

    # Tests and embedded callers pass input_fn; the REPL must use it, not prompt_toolkit.
    assert isinstance(make_reader(input_fn=lambda prompt="": ""), StdlibReader)


def test_tab_completion_offers_commands_and_their_arguments(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    from clite.cli.input import Suggestion, build_completer

    completer = build_completer(surface="cli")
    commands = [s.text for s in completer.suggest("/mod")]
    assert "/model" in commands and all(text.startswith("/mod") for text in commands)

    models = [s.text for s in completer.suggest("/model mo")]
    assert "mock-1" in models  # from the configured default
    assert all(s.kind == "model" for s in completer.suggest("/model mo"))

    sessions = [s.text for s in completer.suggest("/resume ")]
    assert completer.suggest("/nothing-here") == []
    if sessions:  # there may be none yet, but the pool must be the session ids
        assert all(s.kind == "session" for s in completer.suggest("/resume "))
    assert Suggestion("x", "session").display() == "x  (session)"


def test_completion_includes_skills_by_name(clite_home):
    skill = clite_home / "skills" / "deploy-check"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: deploy-check\ndescription: Check a deploy.\n---\n\nDo it.\n")
    (clite_home / "config.yaml").write_text(MOCK)
    from clite.cli.input import build_completer

    completer = build_completer(surface="cli")
    assert "deploy-check" in [s.text for s in completer.suggest("/skills dep")]


def _blocking_repl(clite_home, mode, responses):
    """A Repl whose client blocks on the first turn, so a second line arrives "while busy"."""
    from clite.providers.testing import ScriptedClient

    class BlockingClient(ScriptedClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.release = threading.Event()

        def complete(self, *args, **kwargs):
            self.release.wait(timeout=5)
            return super().complete(*args, **kwargs)

    (clite_home / "config.yaml").write_text(f"{MOCK}\ndisplay:\n  busy_input_mode: {mode}\n")
    client = BlockingClient(list(responses), default=text_response("ok"))
    out = io.StringIO()
    repl = Repl(display=Display(stream=out, color=False), client=client, input_fn=lambda prompt="": "")
    return repl, client, out


def test_a_line_sent_over_the_classic_loop_follows_the_busy_mode(clite_home):
    repl, client, out = _blocking_repl(clite_home, "queue", [text_response("first"), text_response("second")])
    try:
        assert repl._dispatch("first") is True  # starts the worker; it blocks inside the client
        assert repl.busy  # a turn is now running
        assert repl._dispatch("second") is True  # typed while busy -> queued (mode: queue)
        assert "queued" in out.getvalue().lower()
        client.release.set()
        repl.turns.join(timeout=5)
        assert len(client.calls) == 2  # both lines reached the model, in order
        assert [c["messages"][-1]["content"] for c in client.calls] == ["first", "second"]
    finally:
        client.release.set()
        repl.turns.join(timeout=5)
        repl.session.close("test")


def test_a_slash_command_that_must_wait_is_refused_while_busy(clite_home):
    repl, client, out = _blocking_repl(clite_home, "queue", [text_response("first")])
    try:
        repl._dispatch("hello")
        assert repl.busy
        assert repl._dispatch("/model") is True  # a command that touches the session must wait
        assert "waits for the running turn" in out.getvalue()
        assert repl._dispatch("/stop") is True  # BUSY_ALLOW: runs at once, no refusal
        assert "waits for the running turn" in out.getvalue().split("/stop")[0]
    finally:
        client.release.set()
        repl.turns.join(timeout=5)
        repl.session.close("test")


# ── management subcommands ───────────────────────────────────────────────────────────────


def test_config_commands(cli, clite_home):
    assert "provider: mock" in cli("config", "show")
    assert "threshold: 0.5" in cli("config", "show", "--all")
    cli("config", "set", "compression.threshold", "0.6")
    cli("config", "set", "skills.external_dirs", "[~/shared-skills]")
    assert load_config()["compression"]["threshold"] == 0.6 and load_config()["skills"]["external_dirs"] == [
        "~/shared-skills"
    ]
    assert cli("config", "get", "compression.threshold").strip() == "0.6"
    cli("config", "get", "no.such.key", expect=1)
    assert "reset to its default" in cli("config", "unset", "compression.threshold")
    assert load_config()["compression"]["threshold"] == 0.5
    assert cli("config", "path").strip() == str(clite_home / "config.yaml")
    (clite_home / ".env").write_text("OPENROUTER_API_KEY=sk-or-abcdefghijklmnop\n")
    assert "OPENROUTER_API_KEY=sk-o…mnop" in cli("config", "env")
    assert "already current" in cli("config", "migrate")


def test_setup_without_questions(clite_home, capsys, assert_private_file):
    assert (
        main(
            [
                "setup",
                "--provider",
                "deepseek",
                "--api-key",
                "sk-ds-123456789012",
                "--model",
                "deepseek-chat",
                "--skip-verify",
            ]
        )
        == 0
    )
    assert (
        load_config()["model"]["provider"] == "deepseek"
        and load_config()["model"]["default"] == "deepseek-chat"
    )
    assert "DEEPSEEK_API_KEY=sk-ds-123456789012" in (clite_home / ".env").read_text()
    assert_private_file(clite_home / ".env")
    capsys.readouterr()
    assert main(["setup", "--provider", "imaginary"]) == 1
    assert main(["setup"]) == 1  # not a terminal: the interactive wizard refuses to guess


def test_setup_interactive_wizard_and_verification(clite_home, monkeypatch, capsys):
    from clite.providers.registry import list_providers

    # Simulate an interactive terminal
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    # 1. Test full interactive wizard with mock provider
    # Provider: mock index, Model: 1, Toolsets: 1, Approvals: 1, Telegram: empty
    mock_idx = str([p.name for p in list_providers()].index("mock") + 1)
    answers = iter([mock_idx, "1", "1", "1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "test-key")

    assert main(["setup"]) == 0
    cfg = load_config()
    assert cfg["model"]["provider"] == "mock"
    assert cfg["toolsets"] == ["clite-cli"]
    assert cfg["approvals"]["mode"] == "manual"
    out = capsys.readouterr().out
    assert "Setup complete!" in out

    # 2. Test invalid API key rejected with clear message
    # Mock verify_provider_key to fail with auth error
    from clite.cli.subcommands import setup as setup_mod

    monkeypatch.setattr(
        setup_mod, "verify_provider_key", lambda *args, **kwargs: (False, "401 Unauthorized: Invalid API key")
    )

    assert (
        main(["setup", "--provider", "openrouter", "--api-key", "wrong-key", "--model", "deepseek-v3"]) == 1
    )
    err = capsys.readouterr().err
    assert "API key rejected by openrouter: 401 Unauthorized" in err

    # 3. Test non-interactive flags produce matching config
    assert (
        main(
            [
                "setup",
                "--provider",
                "mock",
                "--model",
                "mock-2",
                "--toolsets",
                "file",
                "terminal",
                "--approval-mode",
                "smart",
                "--skip-verify",
            ]
        )
        == 0
    )
    cfg_non_interactive = load_config()
    assert cfg_non_interactive["model"]["provider"] == "mock"
    assert cfg_non_interactive["model"]["default"] == "mock-2"
    assert cfg_non_interactive["toolsets"] == ["file", "terminal"]
    assert cfg_non_interactive["approvals"]["mode"] == "smart"


def test_model_commands(cli):
    assert "Model:    mock-1" in cli("model")
    assert "mock: 1 models" in cli("model", "list", "mock")
    assert "saved as default" in cli("model", "set", "mock:mock-5")
    assert load_config()["model"]["default"] == "mock-5"
    assert "needs ANTHROPIC_API_KEY" in cli("model", "providers")
    cli("model", "set", "anthropic:claude-x", expect=1)


def test_tools_commands(cli):
    listing = cli("tools", "list", "-v")
    assert "terminal" in listing and "* read_file" in listing
    cli("tools", "disable", "web")
    assert load_config()["disabled_toolsets"] == ["web"]
    assert "off  web" in cli("tools")
    cli("tools", "enable", "web")
    assert load_config()["disabled_toolsets"] == []
    cli("tools", "disable", "imaginary", expect=1)


def test_skills_commands(cli, tmp_path, clite_home):
    assert "skill-authoring" in cli("skills", "list")
    assert "# Writing a skill" in cli("skills", "view", "skill-authoring")
    cli("skills", "view", "nope", expect=1)
    source = tmp_path / "my-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: my-skill\ndescription: Does my thing.\n---\n\nSteps.\n")
    assert "Installed my-skill" in cli("skills", "install", source)
    assert (clite_home / "skills" / "my-skill" / "SKILL.md").is_file()
    cli("skills", "install", source, expect=1)  # already there
    assert "Removed my-skill" in cli("skills", "remove", "my-skill")
    cli("skills", "remove", "skill-authoring", expect=1)  # bundled skills cannot be deleted
    assert "No agent-created skill" in cli("skills", "curate")


def test_plugins_commands_and_plugin_cli_command(cli, clite_home, tmp_path):
    assert "not_enabled" in cli("plugins", "list") and "audit-log" in cli("plugins")
    assert "audit-log: loaded" in cli("plugins", "enable", "audit-log")
    assert "No tool calls recorded yet." in cli("audit")  # the plugin's own subcommand
    cli("-q", '!read_file {"path": "nothing.txt"}')
    assert "read_file" in cli("audit", "--limit", "5")
    assert "audit-log: disabled" in cli("plugins", "disable", "audit-log")
    cli("plugins", "enable", "imaginary", expect=1)

    source = tmp_path / "demo"
    source.mkdir()
    (source / "plugin.yaml").write_text("name: demo\nversion: 2.0.0\n")
    (source / "__init__.py").write_text("def register(ctx):\n    pass\n")
    assert "clite plugins enable demo" in cli("plugins", "install", source)
    assert "Removed demo" in cli("plugins", "remove", "demo")


def test_sessions_commands(cli, tmp_path):
    cli("-q", "the launch code is tangerine")
    cli("-q", "unrelated question")
    listing = cli("sessions", "list")
    assert listing.count("cli") >= 2
    first = get_session_db().search_messages("tangerine")[0]["session_id"]
    assert "tangerine" in cli("sessions", "search", "tangerine") and first in cli(
        "sessions", "search", "tangerine"
    )
    assert "No matches." in cli("sessions", "search", "zzzzqq")
    assert "USER: the launch code is tangerine" in cli("sessions", "show", first)
    assert "Title: Launch notes" in cli("sessions", "rename", first, "Launch", "notes")
    exported = tmp_path / "out.json"
    cli("sessions", "export", "Launch notes", "-o", exported)
    data = json.loads(exported.read_text())
    assert data["session"]["title"] == "Launch notes" and [m["role"] for m in data["messages"]] == [
        "user",
        "assistant",
    ]
    assert "0 session(s) with no activity for 90 days would be deleted" in cli("sessions", "prune")
    assert "2 session(s)" in cli("sessions", "prune", "--older-than", "0")
    assert get_session_db().get_session(first) is not None  # counting deletes nothing
    assert "Deleted" in cli("sessions", "delete", first)
    cli("sessions", "show", first, expect=1)


def test_sessions_list_shows_cost(cli):
    db = get_session_db()
    db.create_session("s-unpriced", "cli", model="mock-1")
    db.create_session("s-priced", "cli", model="mock-1")
    db.add_usage("s-priced", cost_usd=0.0123)
    listing = cli("sessions", "list")
    assert "$0.0123" in listing
    assert "unknown" in listing


def test_profile_commands_and_the_profile_flag(cli, clite_home, tmp_path):
    assert "* default" in cli("profile", "list")
    assert "Created profile work" in cli("profile", "create", "work", "--clone-from", "default")
    work_home = clite_home / "profiles" / "work"
    assert (work_home / "config.yaml").read_text() == MOCK
    cli("profile", "create", "Bad Name", expect=1)

    # -p runs one command in that profile: its sessions land in its own database.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    env.pop("CLITE_HOME", None)
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "clite", "-p", "work", "-q", "hello from work"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0 and result.stdout == "You said: hello from work\n", result.stderr
    assert (work_home / "state.db").is_file() and not (clite_home / "state.db").exists()

    assert "New shells now start in profile work" in cli("profile", "use", "work")
    cli("profile", "delete", "work", expect=1)  # needs --yes
    assert "Deleted profile work" in cli("profile", "delete", "work", "--yes")
    assert not work_home.exists()


def test_cron_commands(cli):
    out = cli("cron", "add", "every 2h", "Check the build status", "--name", "build watch")
    job_id = out.split()[1]
    assert "build watch" in cli("cron", "list") and "every 2h" in cli("cron")
    assert "paused" in cli("cron", "pause", job_id) and "resumed" in cli("cron", "resume", job_id)
    assert "Nothing was due." in cli("cron", "tick")
    cli("cron", "run", job_id)
    assert f"{job_id}: ok" in cli("cron", "tick")
    assert "removed" in cli("cron", "remove", job_id)
    cli("cron", "remove", job_id, expect=1)
    cli("cron", "add", "sometime", "x", expect=1)


def test_gateway_commands(cli, clite_home):
    assert "No platform is configured" in cli("gateway", "status")
    (clite_home / "config.yaml").write_text(
        MOCK + "gateway:\n  platforms:\n    telegram: {enabled: true}\n    imaginary: {enabled: false}\n"
    )
    status = cli("gateway")
    assert "telegram     enabled" in status and "no adapter installed" in status
    assert "No pairing requests" in cli("gateway", "pair", "list")
    cli("gateway", "pair", "approve", "telegram", "WRONGCODE", expect=1)
    from clite.gateway.pairing import PairingStore

    code = PairingStore().request_code("telegram", "555", "Grace")
    assert code in cli("gateway", "pair")
    assert "Approved Grace on telegram" in cli("gateway", "pair", "approve", "telegram", code)
    assert "Revoked 555" in cli("gateway", "pair", "revoke", "telegram", "555")


def test_status_version_doctor_logs_memory(cli, clite_home):
    assert "C-lite 0.1.0" in cli("version")
    status = cli("status")
    assert "mock-1 via mock" in status and "Cron:      0 active job(s)" in status
    doctor = cli("doctor")
    assert (
        "[ok  ] Model provider is configured: mock-1 via mock" in doctor
        and "Everything needed is in place." in doctor
    )
    assert (
        "[ok  ] Shell hooks are approved\n" in doctor
    )  # nothing is waiting, so nothing is said about waiting
    cli("logs", "--errors", "-n", "5")
    assert "entries" in cli("memory")
    # `clite acp` is a server on stdin/stdout, so it is driven over pipes in tests/acp/.


def test_doctor_reports_real_problems(clite_home, capsys):
    (clite_home / "config.yaml").write_text("model: [unclosed\n")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] config.yaml is valid" in out and "problem(s) need attention" in out


def test_unknown_profile_and_help(clite_home, capsys):
    assert main(["-p", "ghost", "status"]) == 2
    assert "does not exist" in capsys.readouterr().err
    with pytest.raises(SystemExit) as raised:
        main(["--help"])
    assert raised.value.code == 0
    out = capsys.readouterr().out
    for command in (
        "chat",
        "setup",
        "model",
        "config",
        "tools",
        "skills",
        "plugins",
        "sessions",
        "profile",
        "cron",
        "gateway",
        "serve",
        "dashboard",
        "tui",
        "doctor",
    ):
        assert command in out


def test_the_session_token_cannot_be_given_on_the_command_line(clite_home):
    """Arguments are visible to every local user (`ps`), so the token only comes in through
    the environment. There is no `--token` option, and a value after it stops the parser rather
    than starting a server with it."""
    from clite.cli.main import build_parser

    for command in ("serve", "dashboard"):
        args, extra = build_parser().parse_known_args([command, "--token"])
        assert extra == ["--token"], command
        assert not hasattr(args, "token"), command
        with pytest.raises(SystemExit):
            build_parser().parse_args([command, "--token", "secret-token"])


def test_serve_token_commands_manage_named_tokens(clite_home, capsys):
    """`clite serve token create|list|revoke`: the value is shown once and stored as a hash."""
    from clite.cli.main import main
    from clite.server.tokens import get_token_store

    assert main(["serve", "token", "list"]) == 0
    assert "No named tokens" in capsys.readouterr().out

    assert main(["serve", "token", "create", "laptop", "--days", "7"]) == 0
    printed = capsys.readouterr().out
    assert "Copy it now" in printed
    secret = next(line for line in printed.splitlines() if line and " " not in line.strip())
    assert secret not in (clite_home / "tokens.json").read_text()
    assert get_token_store().verify(secret) is not None

    assert main(["serve", "token", "list"]) == 0
    listed = capsys.readouterr().out
    assert "laptop" in listed and "active" in listed and secret not in listed

    assert main(["serve", "token", "revoke", "laptop"]) == 0
    assert "Revoked" in capsys.readouterr().out
    assert get_token_store().verify(secret) is None
    assert main(["serve", "token", "revoke", "laptop"]) == 1  # already gone


def test_serve_prints_the_ready_line_as_a_real_process(clite_home):
    """`clite serve` the way the desktop app starts it: token in the environment, port 0."""
    import urllib.request

    (clite_home / "config.yaml").write_text(MOCK)
    env = {
        **os.environ,
        "CLITE_HOME": str(clite_home),
        "CLITE_SESSION_TOKEN": "parent-token",
        "PYTHONPATH": os.pathsep.join(sys.path),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "clite", "serve", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        line = process.stdout.readline().strip()
        assert line.startswith("CLITE_BACKEND_READY port="), process.stderr.read()
        port = int(line.split("=")[1])
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/status", headers={"Authorization": "Bearer parent-token"}
        )
        for _ in range(50):
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    assert json.loads(response.read())["model"] == "mock-1"
                break
            except OSError:
                import time

                time.sleep(0.1)
        else:
            raise AssertionError("the backend never answered")
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_a_repl_started_with_an_image_attaches_it_to_the_first_turn(clite_home, tmp_path):
    (clite_home / "config.yaml").write_text(MOCK)
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")
    out, client = _repl(["/status", "what is this?", "/quit"], images=[str(image)])
    assert "mock-1 via mock" in out  # the command did not consume the attachment
    content = client.calls[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "what is this?"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


# ── shell completion ─────────────────────────────────────────────────────────────────────


def test_the_bash_completion_script_names_every_subcommand(cli):
    from clite.cli.main import build_parser

    out = cli("completion", "bash")
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name in action.choices:
                assert name in out, f"{name} missing from the completion script"


def test_the_generated_bash_script_parses(cli, tmp_path):
    out = cli("completion", "bash")
    script = tmp_path / "clite.bash"
    script.write_text(out)
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_zsh_and_fish_scripts_are_not_empty(cli):
    assert "#compdef clite" in cli("completion", "zsh")
    assert "complete -c clite" in cli("completion", "fish")


def test_completion_values_for_profiles_list_the_known_profiles(cli):
    out = cli("completion", "--values", "profiles")
    assert "default" in out.split()


def test_completion_values_for_sessions_are_fast_and_load_no_plugins(cli):
    # The catalogue is read without starting plugins or a model; it still answers.
    out = cli("completion", "--values", "sessions")
    assert isinstance(out, str)


def test_backup_and_restore(clite_home, tmp_path):
    import tarfile

    # Populate home with sample data
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n")
    (clite_home / ".env").write_text("MOCK_KEY=secret-123\n")
    (clite_home / "auth.json").write_text('{"token": "xyz"}')
    sessions_dir = clite_home / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "sess-1.json").write_text('{"title": "test session"}')
    memories_dir = clite_home / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)
    (memories_dir / "facts.json").write_text('{"facts": ["user is azis"]}')
    skills_dir = clite_home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "my_skill.md").write_text("# Test skill")

    # 1. Backup without secrets: must not contain .env or auth.json
    archive_no_secrets = tmp_path / "backup_no_secrets.tar.gz"
    assert main(["backup", "create", str(archive_no_secrets)]) == 0
    assert archive_no_secrets.is_file()

    with tarfile.open(archive_no_secrets, "r:gz") as tar:
        names = tar.getnames()
        assert ".env" not in names
        assert "auth.json" not in names
        assert "config.yaml" in names
        assert "sessions/sess-1.json" in names
        assert "memories/facts.json" in names
        assert "skills/my_skill.md" in names

    # 2. Backup with secrets: must contain .env and mode 0600
    archive_with_secrets = tmp_path / "backup_with_secrets.tar.gz"
    assert main(["backup", "create", str(archive_with_secrets), "--include-secrets"]) == 0
    assert archive_with_secrets.is_file()

    with tarfile.open(archive_with_secrets, "r:gz") as tar:
        names = tar.getnames()
        assert ".env" in names
        assert "auth.json" in names

    assert oct(archive_with_secrets.stat().st_mode)[-3:] == "600"

    # 3. Restore to a new, empty home
    new_home = tmp_path / "new_home"
    from unittest.mock import patch

    with patch("clite.cli.subcommands.backup.get_home", return_value=new_home):
        assert main(["backup", "restore", str(archive_with_secrets)]) == 0

    assert (new_home / "config.yaml").read_text() == "model:\n  provider: mock\n"
    assert (new_home / ".env").read_text() == "MOCK_KEY=secret-123\n"
    assert (new_home / "sessions" / "sess-1.json").read_text() == '{"title": "test session"}'
    assert (new_home / "memories" / "facts.json").read_text() == '{"facts": ["user is azis"]}'
    assert (new_home / "skills" / "my_skill.md").read_text() == "# Test skill"


def test_update_check_and_status(monkeypatch, capsys):
    from clite import __version__

    # 1. Mock newer version available
    monkeypatch.setenv("CLITE_UPDATE_MOCK_VERSION", "99.0.0")
    assert main(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "Update available: 99.0.0" in out

    # 2. Mock current version is up to date
    monkeypatch.setenv("CLITE_UPDATE_MOCK_VERSION", __version__)
    assert main(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "c-lite is up to date." in out


def test_cli_insights_command(cli, clite_home):
    import json

    # Text output
    out = cli("insights", "--days", "7")
    assert "Usage Insights" in out
    assert "Past 7 Days" in out

    # JSON output
    out_json = cli("insights", "--days", "7", "--json")
    data = json.loads(out_json)
    assert data["days"] == 7
    assert "total_sessions" in data
    assert "tokens" in data
    assert "cost" in data
