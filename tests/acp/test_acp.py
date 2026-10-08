"""The ACP server: the handshake an editor makes, sessions, and the pipe it all goes over.

Nothing here mocks the agent: the tests drive the real ``AcpServer`` over the same in-memory
transport the RPC tests use, and one test spawns the real process and talks over pipes.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

from clite.acp.entry import serve_stdio
from clite.acp.server import ACP_METHODS, PROTOCOL_VERSION, AcpServer
from clite.providers.testing import ScriptedClient, text_response
from clite.rpc.transport import MemoryTransport

MOCK = "model:\n  provider: mock\n  default: mock-1\n"


class Client:
    """A minimal ACP client over the in-memory transport."""

    def __init__(self, responses=None) -> None:
        self.transport = MemoryTransport()
        self.scripted = ScriptedClient(list(responses or []), default=text_response("ok"))
        self.server = AcpServer(self.transport, client_factory=lambda: self.scripted)
        self._next = 0

    # ── sending ──────────────────────────────────────────────────────────────────────────

    def send(self, method: str, params: dict | None = None, *, notify: bool = False):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self._next += 1
            message["id"] = self._next
        self.server.handle_message(message)
        return None if notify else self._next

    def call(self, method: str, params: dict | None = None) -> dict:
        request_id = self.send(method, params)
        reply = self.reply_to(request_id)
        assert "error" not in reply, reply
        return reply["result"]

    def error(self, method: str, params: dict | None = None) -> dict:
        request_id = self.send(method, params)
        return self.reply_to(request_id)["error"]

    def reply_to(self, request_id: int, timeout: float = 5.0) -> dict:
        return self.transport.wait_for(
            lambda message: message.get("id") == request_id and "method" not in message, timeout
        )

    def updates(self, name: str | None = None) -> list[dict]:
        return [
            message["params"]
            for message in self.transport.messages
            if message.get("method") == "session/update"
            and (name is None or message["params"]["update"]["sessionUpdate"] == name)
        ]

    def initialize(self) -> dict:
        return self.call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {"fs": {"readTextFile": True}},
                "clientInfo": {"name": "test-client", "title": "Test Client", "version": "0.0.1"},
            },
        )

    def new_session(self, cwd: str = "/tmp/project") -> str:
        if not self.server.initialized:
            self.initialize()
        return self.call("session/new", {"cwd": cwd, "mcpServers": []})["sessionId"]


@pytest.fixture(autouse=True)
def mock_model(clite_home):
    (clite_home / "config.yaml").write_text(MOCK)


@pytest.fixture
def client():
    clients: list[Client] = []

    def factory(responses=None) -> Client:
        instance = Client(responses)
        clients.append(instance)
        return instance

    yield factory
    for instance in clients:
        instance.server.close()


# ── the handshake ────────────────────────────────────────────────────────────────────────


def test_the_handshake_answers_with_our_version_and_capabilities(client):
    acp = client()
    result = acp.initialize()
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["agentInfo"]["name"] == "c-lite"
    assert result["agentInfo"]["title"] == "C-lite"
    assert result["agentInfo"]["version"]  # the package version, whatever it is
    assert result["authMethods"] == []
    assert result["agentCapabilities"]["loadSession"] is True
    # Only what a client may send is announced: no images, no audio, no embedded resources.
    assert result["agentCapabilities"]["promptCapabilities"] == {
        "image": False,
        "audio": False,
        "embeddedContext": False,
    }
    assert acp.server.initialized is True


def test_the_client_capabilities_and_name_are_remembered(client):
    acp = client()
    acp.initialize()
    assert acp.server.client_capabilities == {"fs": {"readTextFile": True}}
    assert acp.server.client_info["name"] == "test-client"


@pytest.mark.parametrize("params", [{}, {"protocolVersion": "1"}, {"protocolVersion": True}])
def test_the_handshake_needs_an_integer_protocol_version(client, params):
    acp = client()
    error = acp.error("initialize", params)
    assert error["code"] == -32602 and "protocolVersion" in error["message"]
    assert acp.server.initialized is False


def test_a_client_speaking_another_version_gets_ours_back(client):
    """The versions may still agree on everything we use, so the handshake is answered, not
    refused: the client decides what to do with a version it does not know."""
    acp = client()
    result = acp.call("initialize", {"protocolVersion": 7})
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert acp.server.initialized is True


# ── the wire ─────────────────────────────────────────────────────────────────────────────


def test_an_unknown_method_is_a_protocol_error_and_the_connection_survives(client):
    acp = client()
    error = acp.error("session/dance", {})
    assert error["code"] == -32601 and "session/dance" in error["message"]
    assert acp.initialize()["protocolVersion"] == PROTOCOL_VERSION  # still usable


def test_invalid_json_is_a_parse_error(client):
    acp = client()
    acp.server.handle_line("{not json")
    reply = acp.transport.wait_for(lambda message: "error" in message)
    assert reply["error"]["code"] == -32700
    assert reply["id"] is None
    acp.server.handle_line("   ")  # a blank line is not a message and says nothing
    assert len(acp.transport.messages) == 1


def test_a_notification_never_gets_a_reply(client):
    acp = client()
    acp.initialize()
    before = len(acp.transport.messages)
    acp.send("session/cancel", {"sessionId": "sess_none", "reason": "user"}, notify=True)
    # Nothing comes back, not even an error for an unknown session: a client that gets a
    # reply to a notification has no id to match it against.
    assert acp.transport.messages[before:] == []


def test_replies_are_plain_json_rpc_with_the_clients_own_id(client):
    acp = client()
    result = acp.call("initialize", {"protocolVersion": PROTOCOL_VERSION})
    reply = acp.transport.messages[-1]
    assert list(reply) == ["jsonrpc", "id", "result"]
    assert reply["jsonrpc"] == "2.0" and reply["id"] == 1
    assert "event" not in json.dumps(result)  # no envelope of our own around the result


def test_an_error_reply_carries_only_code_and_message(client):
    acp = client()
    error = acp.error("initialize", {})
    assert set(error) == {"code", "message"}


# ── sessions ─────────────────────────────────────────────────────────────────────────────


def test_session_new_hands_back_an_id_and_a_live_session(client):
    acp = client()
    session_id = acp.new_session("/tmp/project")
    assert session_id.startswith("sess_")
    session = acp.server.sessions[session_id]
    assert session.id == session_id
    assert session.chat.agent.cwd  # the agent was built for the session
    assert session.chat.platform == "acp"


def test_session_new_needs_the_handshake_first(client):
    acp = client()
    error = acp.error("session/new", {"cwd": "/tmp/project"})
    assert error["code"] == -32600 and "initialize" in error["message"]


@pytest.mark.parametrize("cwd", ["", "project", "./project", None, 7])
def test_session_new_needs_an_absolute_cwd(client, cwd):
    acp = client()
    acp.initialize()
    error = acp.error("session/new", {"cwd": cwd, "mcpServers": []})
    assert error["code"] in (-32602, -32600)
    assert acp.server.sessions == {}


def test_session_new_accepts_the_clients_mcp_servers_without_taking_them(client):
    """An editor sends the servers it has configured; c-lite has its own, so the list is
    ignored — announced in a warning, not in an error that would fail the session."""
    acp = client()
    acp.initialize()
    session_id = acp.call(
        "session/new",
        {"cwd": "/tmp/project", "mcpServers": [{"name": "fs", "command": "/bin/fs", "args": [], "env": []}]},
    )["sessionId"]
    assert acp.server.sessions[session_id].chat is not None


def test_the_method_table_is_the_protocol_we_implement():
    assert set(ACP_METHODS) == {"initialize", "session/new"}


# ── the real process over pipes ──────────────────────────────────────────────────────────


def _line(request_id: int, method: str, params: dict) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n"


def test_a_stray_print_never_reaches_the_wire(clite_home):
    """Stdout is the wire: what a tool prints goes to the log, never between two messages.

    Every line the transport wrote is parsed as JSON, so a stray ``print`` that reached the
    stream would fail the test rather than confuse an editor.
    """
    wire = io.StringIO()
    saved_stdout = sys.stdout

    class NoisyInput:
        """A stdin that prints while the server is running, as a tool would."""

        def __iter__(self):
            print("stray output from a tool")
            yield _line(1, "initialize", {"protocolVersion": PROTOCOL_VERSION})
            print("and another one")
            yield _line(2, "session/new", {"cwd": "/tmp/project", "mcpServers": []})

    sys.stdout = wire  # in the real process this is the pipe the editor reads
    try:
        assert serve_stdio(stdin=NoisyInput(), stdout=wire) == 0
        assert sys.stdout is wire  # the redirect did not outlive the server
    finally:
        sys.stdout = saved_stdout
    lines = [line for line in wire.getvalue().splitlines() if line.strip()]
    messages = [json.loads(line) for line in lines]  # every line is a protocol message
    assert sorted(message["id"] for message in messages) == [1, 2]  # both were answered
    assert "stray output" not in wire.getvalue()


def test_the_entry_point_talks_over_real_pipes(clite_home):
    """Spawn ``clite acp`` as an editor does and shake hands over stdin/stdout."""
    env = {**os.environ, "CLITE_HOME": str(clite_home), "PYTHONPATH": os.pathsep.join(sys.path)}
    process = subprocess.Popen(
        [sys.executable, "-m", "clite.acp.entry"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    def send(message: dict) -> None:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def read_until(predicate):
        while True:
            line = process.stdout.readline()
            assert line, f"the server exited early: {process.stderr.read()}"
            message = json.loads(line)  # every line on stdout is a protocol message
            if predicate(message):
                return message

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}})
        assert read_until(lambda m: m.get("id") == 1)["result"]["protocolVersion"] == 1
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": str(clite_home), "mcpServers": []},
            }
        )
        assert read_until(lambda m: m.get("id") == 2)["result"]["sessionId"].startswith("sess_")
    finally:
        process.stdin.close()
        assert process.wait(timeout=10) == 0
