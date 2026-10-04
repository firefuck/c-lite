"""The command-line surface: subcommands in process, the REPL with scripted input, and the
installed entry point as a real subprocess."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

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
    assert payload["final_response"] == "You said: hi" and payload["completed"] is True and payload["provider"] == "mock"
    assert main(["-q", "!error 400"]) == 1  # a failed turn is a failing exit code
    assert "400" in capsys.readouterr().out


def test_single_query_runs_tools_and_reports_progress_on_stderr(cli, tmp_path, capsys):
    (tmp_path / "data.txt").write_text("forty-two\n")
    assert main(["-q", '!read_file {"path": "data.txt"}']) == 0
    captured = capsys.readouterr()
    assert "forty-two" in captured.out
    assert "✓ read_file data.txt" in captured.err and "✓" not in captured.out  # progress never pollutes stdout


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
    repl = Repl(display=Display(stream=out, color=False), input_fn=fake_input, client=client, **options)
    assert repl.run() == 0
    return out.getvalue(), client


def test_repl_session(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    out, client = _repl(["hello", "", "/status", "/nonsense", "/quit", "never reached"],
                        [text_response("Hi! How can I help?")])
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
        [tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Done."),
         tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Done again.")],
    )
    assert "needs your approval" in out and f"rm -rf {target}" in out
    assert out.count("needs your approval") == 1  # the second identical command was covered by "session"
    assert "✓ terminal" in out and "Done again." in out and not target.exists()


def test_repl_clarify_by_number_and_eof_exits(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)
    out, client = _repl(["deploy", "2"], [tool_call_response(("clarify", {"question": "Where to?", "choices": ["staging", "production"]})),
                                         text_response("Deploying to production.")])
    assert "Where to?" in out and "2. production" in out and "Deploying to production." in out
    assert json.loads(client.calls[1]["messages"][-1]["content"])["answer"] == "production"


def test_display_helpers(clite_home):
    assert tool_preview("terminal", {"command": "echo   hi\nthere", "timeout": 5}) == "echo hi there"
    assert tool_preview("unknown_tool", {"n": 3, "query": "first string wins"}) == "first string wins"
    assert len(tool_preview("terminal", {"command": "x" * 200})) == 70
    assert result_failed('{"error": "nope"}') and not result_failed('{"output": "fine"}') and not result_failed("plain")
    (clite_home / "skins").mkdir()
    (clite_home / "skins" / "ocean.yaml").write_text("prompt: '~> '\ntool: blue\nnot_a_key: ignored\n")
    skin = load_skin("ocean")
    assert skin["prompt"] == "~> " and skin["tool"] == "blue" and "not_a_key" not in skin
    assert load_skin("missing")["prompt"] == load_skin("default")["prompt"]
    out = io.StringIO()
    display = Display(stream=out, color=True, skin="ocean")
    display.tool_done("terminal", {"command": "ls"}, '{"error": "x"}', 0.25)
    assert "\x1b[34m" in out.getvalue() and "✗ terminal ls" in out.getvalue()


# ── management subcommands ───────────────────────────────────────────────────────────────


def test_config_commands(cli, clite_home):
    assert "provider: mock" in cli("config", "show")
    assert "threshold: 0.5" in cli("config", "show", "--all")
    cli("config", "set", "compression.threshold", "0.6")
    cli("config", "set", "skills.external_dirs", "[~/shared-skills]")
    assert load_config()["compression"]["threshold"] == 0.6 and load_config()["skills"]["external_dirs"] == ["~/shared-skills"]
    assert cli("config", "get", "compression.threshold").strip() == "0.6"
    cli("config", "get", "no.such.key", expect=1)
    assert "reset to its default" in cli("config", "unset", "compression.threshold")
    assert load_config()["compression"]["threshold"] == 0.5
    assert cli("config", "path").strip() == str(clite_home / "config.yaml")
    (clite_home / ".env").write_text("OPENROUTER_API_KEY=sk-or-abcdefghijklmnop\n")
    assert "OPENROUTER_API_KEY=sk-o…mnop" in cli("config", "env")
    assert "already current" in cli("config", "migrate")


def test_setup_without_questions(clite_home, capsys):
    assert main(["setup", "--provider", "deepseek", "--api-key", "sk-ds-123456789012", "--model", "deepseek-chat"]) == 0
    assert load_config()["model"]["provider"] == "deepseek" and load_config()["model"]["default"] == "deepseek-chat"
    assert "DEEPSEEK_API_KEY=sk-ds-123456789012" in (clite_home / ".env").read_text()
    assert oct((clite_home / ".env").stat().st_mode & 0o777) == "0o600"
    capsys.readouterr()
    assert main(["setup", "--provider", "imaginary"]) == 1
    assert main(["setup"]) == 1  # not a terminal: the interactive wizard refuses to guess


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
    assert "tangerine" in cli("sessions", "search", "tangerine") and first in cli("sessions", "search", "tangerine")
    assert "No matches." in cli("sessions", "search", "zzzzqq")
    assert "USER: the launch code is tangerine" in cli("sessions", "show", first)
    assert "Title: Launch notes" in cli("sessions", "rename", first, "Launch", "notes")
    exported = tmp_path / "out.json"
    cli("sessions", "export", "Launch notes", "-o", exported)
    data = json.loads(exported.read_text())
    assert data["session"]["title"] == "Launch notes" and [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert "would be deleted" in cli("sessions", "prune", "--older-than", "0")
    assert "Deleted" in cli("sessions", "delete", first)
    cli("sessions", "show", first, expect=1)


def test_profile_commands_and_the_profile_flag(cli, clite_home, tmp_path):
    assert "* default" in cli("profile", "list")
    assert "Created profile work" in cli("profile", "create", "work", "--clone-from", "default")
    work_home = tmp_path / ".clite" / "profiles" / "work"
    assert (work_home / "config.yaml").read_text() == MOCK
    cli("profile", "create", "Bad Name", expect=1)

    # -p runs one command in that profile: its sessions land in its own database.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    env.pop("CLITE_HOME", None)
    env["HOME"] = str(tmp_path)
    result = subprocess.run([sys.executable, "-m", "clite", "-p", "work", "-q", "hello from work"],
                            capture_output=True, text=True, env=env, timeout=60)
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
    (clite_home / "config.yaml").write_text(MOCK + "gateway:\n  platforms:\n    telegram: {enabled: true}\n    imaginary: {enabled: false}\n")
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
    assert "[ok  ] Model provider is configured: mock-1 via mock" in doctor and "Everything needed is in place." in doctor
    cli("logs", "--errors", "-n", "5")
    assert "entries" in cli("memory")
    cli("acp", expect=2)


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
    for command in ("chat", "setup", "model", "config", "tools", "skills", "plugins", "sessions", "profile", "cron",
                    "gateway", "serve", "dashboard", "tui", "doctor"):
        assert command in out


def test_serve_prints_the_ready_line_as_a_real_process(clite_home):
    """`clite serve` the way the desktop app starts it: token in the environment, port 0."""
    import urllib.request

    (clite_home / "config.yaml").write_text(MOCK)
    env = {**os.environ, "CLITE_HOME": str(clite_home), "CLITE_SESSION_TOKEN": "parent-token",
           "PYTHONPATH": os.pathsep.join(sys.path)}
    process = subprocess.Popen([sys.executable, "-m", "clite", "serve", "--port", "0"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env)
    try:
        line = process.stdout.readline().strip()
        assert line.startswith("CLITE_BACKEND_READY port="), process.stderr.read()
        port = int(line.split("=")[1])
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers={"Authorization": "Bearer parent-token"})
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
