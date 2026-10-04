"""The JSON-RPC server: protocol rules, session lifecycle, turns as event streams."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

import pytest

from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.rpc.contracts.base import EVENTS, METHODS, SERVER_REQUESTS
from clite.rpc.server import (
    HANDLERS,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    SESSION_BUSY,
    SESSION_NOT_FOUND,
    RpcServer,
)
from clite.rpc.transport import MemoryTransport
from clite.state import get_session_db


class Client:
    """A minimal JSON-RPC client over the in-memory transport."""

    def __init__(self, responses=None, auto_reply=None):
        self.transport = MemoryTransport()
        self.scripted = ScriptedClient(list(responses or []), default=text_response("ok"))
        self.server = RpcServer(self.transport, platform="tui", client_factory=lambda: self.scripted)
        self.auto_reply = auto_reply or {}
        self._next = 0
        self._answered: set[str] = set()

    def call_raw(self, method, params=None):
        self._next += 1
        request_id = self._next
        self.server.handle_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        return self.transport.wait_for(lambda m: m.get("id") == request_id and "method" not in m)

    def call(self, method, params=None):
        reply = self.call_raw(method, params)
        assert "error" not in reply, reply
        return reply["result"]

    def error(self, method, params=None):
        return self.call_raw(method, params)["error"]

    def wait_event(self, event_type, timeout=5.0):
        return self.transport.wait_for(
            lambda m: m.get("method") == "event" and m["params"]["type"] == event_type, timeout)["params"]

    def answer_server_requests(self):
        """Reply to any pending server request using ``auto_reply[method]``."""
        for message in list(self.transport.messages):
            request_id = message.get("id")
            if isinstance(request_id, str) and request_id.startswith("srq-") and request_id not in self._answered:
                self._answered.add(request_id)
                self.server.handle_message({"jsonrpc": "2.0", "id": request_id, "result": self.auto_reply[message["method"]]})

    def run_turn(self, session_id, text, **params):
        started = len(self.transport.events("turn.complete"))
        result = self.call("prompt.submit", {"session_id": session_id, "text": text, **params})
        self.transport.wait_for(lambda m: len(self.transport.events("turn.complete")) > started)
        return result


@pytest.fixture(autouse=True)
def mock_model(clite_home):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")


@pytest.fixture
def client():
    clients = []

    def factory(responses=None, **kwargs):
        instance = Client(responses, **kwargs)
        clients.append(instance)
        return instance

    yield factory
    for instance in clients:
        instance.server.close()


# ── protocol ─────────────────────────────────────────────────────────────────────────────


def test_every_declared_method_has_a_handler_and_the_reverse(client):
    client()  # constructing a server registers the handlers
    assert set(HANDLERS) == set(METHODS)
    assert {"approval.request", "clarify.request"} == set(SERVER_REQUESTS)
    assert "turn.complete" in EVENTS and "gateway.ready" in EVENTS


def test_ready_event_and_ping(client):
    rpc = client()
    rpc.server.announce()
    ready = rpc.wait_event("gateway.ready")
    assert ready["payload"]["protocol_version"] == 1 and ready["seq"] == 1
    assert rpc.call("ping")["pong"] is True
    info = rpc.call("system.info")
    assert info["configured"] is True and info["model"] == "mock-1" and info["profile"] == "default"


def test_protocol_errors_are_replies_not_crashes(client):
    rpc = client()
    assert rpc.error("no.such.method")["code"] == METHOD_NOT_FOUND
    invalid = rpc.error("session.info", {"session_id": "x", "unexpected": 1})
    assert invalid["code"] == INVALID_PARAMS and invalid["data"][0]["field"] == "unexpected"
    assert rpc.error("session.info", {})["code"] == INVALID_PARAMS  # a required field is missing
    assert rpc.error("session.info", {"session_id": "missing"})["code"] == SESSION_NOT_FOUND

    rpc.server.handle_line("this is not json")
    assert rpc.transport.messages[-1]["error"]["code"] == -32700
    rpc.server.handle_message({"jsonrpc": "2.0", "method": "ping"})  # a notification gets no reply
    assert rpc.call("ping")["pong"] is True  # and the connection still works


def test_an_unconfigured_install_reports_a_specific_error(client, clite_home):
    (clite_home / "config.yaml").write_text("")
    rpc = client()
    assert rpc.call("system.info")["configured"] is False
    error = rpc.error("session.create")
    assert error["code"] == 4003 and error["data"]["code"] == "no_provider"


# ── sessions and turns ───────────────────────────────────────────────────────────────────


def test_a_turn_is_a_stream_of_events_ending_with_turn_complete(client, tmp_path):
    (tmp_path / "notes.txt").write_text("the launch is on friday\n")
    rpc = client([tool_call_response(("read_file", {"path": "notes.txt"})), text_response("Friday.")])
    session = rpc.call("session.create", {"cwd": str(tmp_path)})
    assert session["session_id"] != session["stored_session_id"] and session["model"] == "mock-1"

    submitted = rpc.run_turn(session["session_id"], "when is the launch?")
    assert submitted["accepted"] is True and submitted["queued"] is False

    events = rpc.transport.events()
    types = [event["type"] for event in events]
    assert types == ["turn.start", "turn.step", "message.complete", "tool.start", "tool.complete", "turn.step",
                     "message.delta", "message.complete", "turn.complete"]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["session_id"] == session["session_id"] for event in events)

    tool_start, tool_done = events[3]["payload"], events[4]["payload"]
    assert tool_start["name"] == "read_file" and tool_start["preview"] == "notes.txt"
    assert tool_done["call_id"] == tool_start["call_id"] and tool_done["failed"] is False
    done = events[-1]["payload"]
    assert done["turn_id"] == submitted["turn_id"] and done["final_response"] == "Friday." and done["completed"] is True
    assert done["api_calls"] == 2 and done["usage"]["output_tokens"] == 10

    history = rpc.call("session.history", {"session_id": session["session_id"]})["messages"]
    assert [(m["role"], m["tool_name"]) for m in history] == [("user", ""), ("assistant", ""), ("tool", "read_file"), ("assistant", "")]
    assert history[1]["tool_calls"] == ["read_file"]
    usage = rpc.call("session.usage", {"session_id": session["session_id"]})
    assert usage["usage"]["input_tokens"] == 20 and usage["context"]["messages"] == 4


def test_resume_lists_and_reopens_a_stored_session(client):
    rpc = client()
    first = rpc.call("session.create")
    rpc.run_turn(first["session_id"], "remember the green door")
    rpc.call("session.title", {"session_id": first["session_id"], "title": "Green door"})
    rpc.call("session.close", {"session_id": first["session_id"]})
    assert rpc.error("session.info", {"session_id": first["session_id"]})["code"] == SESSION_NOT_FOUND

    listed = rpc.call("session.list")["sessions"]
    assert [(s["id"], s["title"]) for s in listed] == [(first["stored_session_id"], "Green door")]
    resumed = rpc.call("session.create", {"resume": "Green door"})
    assert resumed["stored_session_id"] == first["stored_session_id"] and resumed["message_count"] == 2
    assert "no stored session" in rpc.error("session.create", {"resume": "nothing"})["message"]

    assert "open" in rpc.error("session.delete", {"stored_session_id": first["stored_session_id"]})["message"]
    rpc.call("session.close", {"session_id": resumed["session_id"]})
    rpc.call("session.delete", {"stored_session_id": first["stored_session_id"]})
    assert get_session_db().get_session(first["stored_session_id"]) is None


def test_busy_modes(client):
    release = threading.Event()

    def slow(cancel, **kwargs):
        while not release.is_set():
            if cancel.wait(0.01):
                raise InterruptedError
        return text_response("first done")

    rpc = client([slow, text_response("second done")])
    sid = rpc.call("session.create")["session_id"]
    rpc.call("prompt.submit", {"session_id": sid, "text": "first"})
    rpc.wait_event("turn.step")

    assert rpc.error("prompt.submit", {"session_id": sid, "text": "x", "busy_mode": "reject"})["code"] == SESSION_BUSY
    assert rpc.error("slash.exec", {"session_id": sid, "command": "/new"})["code"] == SESSION_BUSY
    assert "working" in rpc.call("slash.exec", {"session_id": sid, "command": "/status"})["text"]  # allowed while busy
    steered = rpc.call("prompt.submit", {"session_id": sid, "text": "be brief", "busy_mode": "steer"})
    assert steered == {"accepted": True, "turn_id": "", "queued": False}
    queued = rpc.call("prompt.submit", {"session_id": sid, "text": "second", "busy_mode": "queue"})
    assert queued["queued"] is True

    release.set()
    rpc.transport.wait_for(lambda m: len(rpc.transport.events("turn.complete")) == 2)
    completes = [event["payload"] for event in rpc.transport.events("turn.complete")]
    assert [c["final_response"] for c in completes] == ["first done", "second done"]
    assert completes[1]["turn_id"] == queued["turn_id"]


def test_interrupt_mode_stops_the_running_turn_and_runs_the_new_prompt(client):
    def blocked(cancel, **kwargs):
        cancel.wait(5)
        raise InterruptedError

    rpc = client([blocked, text_response("new answer")])
    sid = rpc.call("session.create")["session_id"]
    rpc.call("prompt.submit", {"session_id": sid, "text": "long task"})
    rpc.wait_event("turn.step")
    rpc.call("prompt.submit", {"session_id": sid, "text": "actually do this", "busy_mode": "interrupt"})
    rpc.transport.wait_for(lambda m: len(rpc.transport.events("turn.complete")) == 2)
    first, second = [event["payload"] for event in rpc.transport.events("turn.complete")]
    assert first["interrupted"] is True and second["final_response"] == "new answer"


def test_session_interrupt_method(client):
    def blocked(cancel, **kwargs):
        cancel.wait(5)
        raise InterruptedError

    rpc = client([blocked])
    sid = rpc.call("session.create")["session_id"]
    rpc.call("prompt.submit", {"session_id": sid, "text": "long task"})
    rpc.wait_event("turn.step")
    rpc.call("session.interrupt", {"session_id": sid})
    assert rpc.wait_event("turn.complete")["payload"]["interrupted"] is True


# ── server requests ──────────────────────────────────────────────────────────────────────


def _pump(rpc, until_event="turn.complete"):
    """Answer server requests until the turn ends."""
    for _ in range(500):
        rpc.answer_server_requests()
        if rpc.transport.events(until_event):
            return
        threading.Event().wait(0.01)
    raise AssertionError("turn did not finish")


@pytest.mark.platforms("posix")
def test_approval_goes_to_the_client_and_back(client, tmp_path):
    target = tmp_path / "scratch"
    target.mkdir()
    rpc = client([tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("removed")],
                 auto_reply={"approval.request": {"choice": "once"}})
    sid = rpc.call("session.create", {"cwd": str(tmp_path)})["session_id"]
    rpc.call("prompt.submit", {"session_id": sid, "text": "clean up"})
    _pump(rpc)
    request = next(m for m in rpc.transport.messages if m.get("method") == "approval.request")
    assert request["params"]["command"] == f"rm -rf {target}" and request["params"]["session_id"] == sid
    assert "rm_recursive_or_force" in request["params"]["pattern_keys"]
    assert not target.exists()


@pytest.mark.platforms("posix")
def test_no_answer_to_an_approval_means_deny(client, tmp_path, clite_home):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\napprovals:\n  timeout: 0.2\n")
    target = tmp_path / "keep"
    target.mkdir()
    rpc = client([tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("could not")])
    sid = rpc.call("session.create")["session_id"]
    rpc.run_turn(sid, "clean up")
    assert target.exists()
    assert rpc.transport.events("tool.complete")[0]["payload"]["failed"] is True


def test_clarify_goes_to_the_client_and_back(client):
    rpc = client([tool_call_response(("clarify", {"question": "Which environment?", "choices": ["staging", "prod"]})),
                  text_response("deploying to staging")], auto_reply={"clarify.request": {"answer": "staging"}})
    sid = rpc.call("session.create")["session_id"]
    rpc.call("prompt.submit", {"session_id": sid, "text": "deploy"})
    _pump(rpc)
    request = next(m for m in rpc.transport.messages if m.get("method") == "clarify.request")
    assert request["params"]["choices"] == ["staging", "prod"]
    history = rpc.call("session.history", {"session_id": sid})["messages"]
    assert json.loads(history[2]["text"])["answer"] == "staging"


# ── commands and management methods ──────────────────────────────────────────────────────


def test_slash_commands_through_rpc(client, clite_home):
    skill = clite_home / "skills" / "standup"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: standup\ndescription: Write a standup note.\n---\n\nThree bullets.\n")
    rpc = client([text_response("- did\n- doing\n- blocked")])
    sid = rpc.call("session.create")["session_id"]

    switched = rpc.call("slash.exec", {"session_id": sid, "command": "/model mock-7"})
    assert "mock-7" in switched["text"]
    assert rpc.wait_event("session.info")["payload"]["model"] == "mock-7"

    started = rpc.call("slash.exec", {"session_id": sid, "command": "/standup for today"})
    assert started["action"] == "submit" and started["turn_id"]
    assert rpc.wait_event("turn.complete")["payload"]["final_response"].startswith("- did")
    assert "Three bullets." in rpc.scripted.calls[0]["messages"][1]["content"]

    old = rpc.call("session.info", {"session_id": sid})["stored_session_id"]
    fresh = rpc.call("slash.exec", {"session_id": sid, "command": "/new"})
    assert fresh["action"] == "new"
    assert rpc.call("session.info", {"session_id": sid})["stored_session_id"] != old


def test_catalog_and_completion(client):
    rpc = client()
    commands = {entry["name"]: entry for entry in rpc.call("commands.catalog")["commands"]}
    assert commands["model"]["args_hint"] and commands["skill-authoring"]["kind"] == "skill"
    names = [item["name"] for item in rpc.call("complete.slash", {"prefix": "/re"})["items"]]
    assert names == ["new", "retry", "resume", "reasoning", "reload"]  # /new matches through its alias /reset
    assert [item["name"] for item in rpc.call("complete.slash", {"prefix": "exi"})["items"]] == ["quit"]  # by alias


def test_model_and_provider_methods(client):
    rpc = client()
    sid = rpc.call("session.create")["session_id"]
    listed = rpc.call("model.list")
    assert listed["provider"] == "mock" and listed["current"] == "mock-1" and listed["models"][0]["id"] == "mock-1"
    changed = rpc.call("model.set", {"session_id": sid, "model": "mock-3", "persist": True})
    assert changed["success"] is True and changed["model"] == "mock-3"
    assert rpc.call("config.get", {"key": "model.default"})["value"] == "mock-3"
    failed = rpc.call("model.set", {"session_id": sid, "model": "anthropic:claude-x"})
    assert failed["success"] is False and "ANTHROPIC_API_KEY" in failed["message"]

    providers = {p["name"]: p for p in rpc.call("providers.list")["providers"]}
    assert providers["mock"]["configured"] is True and providers["anthropic"]["configured"] is False
    assert providers["custom"]["needs_base_url"] is True and providers["anthropic"]["env_vars"] == ["ANTHROPIC_API_KEY"]


def test_setup_from_a_client_stores_key_and_choice(client, clite_home):
    rpc = client()
    applied = rpc.call("setup.apply", {"provider": "deepseek", "api_key": "sk-ds-from-the-gui", "model": "deepseek-chat"})
    assert applied == {"provider": "deepseek", "model": "deepseek-chat"}
    assert "DEEPSEEK_API_KEY=sk-ds-from-the-gui" in (clite_home / ".env").read_text()
    info = rpc.call("system.info")
    assert (info["provider"], info["model"]) == ("deepseek", "deepseek-chat")
    assert "unknown provider" in rpc.error("setup.apply", {"provider": "nope"})["message"]


def test_config_tools_skills_plugins_memory_cron(client):
    rpc = client()
    rpc.call("config.set", {"key": "display.skin", "value": "mono"})
    assert rpc.call("config.get", {"key": "display.skin"})["value"] == "mono"
    assert rpc.call("config.get")["value"]["compression"]["threshold"] == 0.5
    assert rpc.error("config.set", {"key": "_config_version", "value": 9})["code"] == 4004

    toolsets = {t["name"]: t for t in rpc.call("tools.list")["toolsets"]}
    assert toolsets["file"]["enabled_tools"] == toolsets["file"]["tools"] == ["read_file", "write_file", "patch", "search_files"]

    assert "skill-authoring" in {s["name"] for s in rpc.call("skills.list")["skills"]}
    viewed = rpc.call("skills.view", {"name": "skill-authoring"})
    assert viewed["content"].startswith("---") and "no skill" in rpc.error("skills.view", {"name": "zzz"})["message"]

    plugins = {p["name"]: p for p in rpc.call("plugins.list")["plugins"]}
    assert plugins["audit-log"]["status"] == "not_enabled"
    enabled = {p["name"]: p for p in rpc.call("plugins.set_enabled", {"name": "audit-log", "enabled": True})["plugins"]}
    assert enabled["audit-log"]["status"] == "loaded"

    assert rpc.call("memory.get") == {"memory": [], "user": [], "memory_limit": 2200, "user_limit": 1375, "provider": ""}

    job = rpc.call("cron.create", {"prompt": "check the queue", "schedule": "every 1h", "name": "queue"})
    assert job["schedule_display"] == "every 1h" and job["enabled"] is True
    paused = rpc.call("cron.action", {"job_id": job["id"], "action": "pause"})["jobs"]
    assert paused[0]["enabled"] is False
    assert rpc.call("cron.action", {"job_id": job["id"], "action": "remove"})["jobs"] == []
    assert "cannot read schedule" in rpc.error("cron.create", {"prompt": "x", "schedule": "whenever"})["message"]


def test_closing_the_server_ends_its_sessions(client):
    rpc = client()
    stored = rpc.call("session.create")["stored_session_id"]
    rpc.run_turn(next(iter(rpc.server.sessions)), "hi")
    rpc.server.close()
    assert get_session_db().get_session(stored)["end_reason"] == "rpc_closed"
    assert rpc.transport.closed is True


# ── the real process over stdio ──────────────────────────────────────────────────────────


def test_stdio_entry_point_end_to_end(clite_home):
    """Spawn the server as the TUI does and talk to it over pipes."""
    env = {**os.environ, "CLITE_HOME": str(clite_home), "PYTHONPATH": os.pathsep.join(sys.path)}
    process = subprocess.Popen([sys.executable, "-m", "clite.rpc.entry"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env)

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def read_until(predicate):
        while True:
            line = process.stdout.readline()
            assert line, f"server exited early: {process.stderr.read()}"
            message = json.loads(line)  # every line on stdout must be protocol
            if predicate(message):
                return message

    try:
        ready = read_until(lambda m: m.get("method") == "event")
        assert ready["params"]["type"] == "gateway.ready"
        send({"jsonrpc": "2.0", "id": 1, "method": "session.create", "params": {}})
        session_id = read_until(lambda m: m.get("id") == 1)["result"]["session_id"]
        send({"jsonrpc": "2.0", "id": 2, "method": "prompt.submit", "params": {"session_id": session_id, "text": "hello pipes"}})
        done = read_until(lambda m: m.get("method") == "event" and m["params"]["type"] == "turn.complete")
        assert done["params"]["payload"]["final_response"] == "You said: hello pipes"
    finally:
        process.stdin.close()
        assert process.wait(timeout=10) == 0
