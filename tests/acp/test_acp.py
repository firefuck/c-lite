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
import threading
import time
from typing import Any

import pytest

from clite.acp.entry import serve_stdio
from clite.acp.server import ACP_METHODS, PROTOCOL_VERSION, AcpError, AcpServer
from clite.acp.session import (
    PERMISSION_OPTIONS,
    RESULT_PREVIEW_CHARS,
    command_list,
    permission_choice,
    plan_entries,
    stop_reason,
    tool_kind,
)
from clite.agent import TurnResult
from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.rpc.transport import MemoryTransport

MOCK = "model:\n  provider: mock\n  default: mock-1\n"

# ``/tmp/project`` is not an absolute path on Windows, and ``session/new`` requires one, so the
# tests build a path the host platform agrees is absolute.
PROJECT = os.path.abspath("/tmp/project")

# A client that says nothing to a permission request is not the same as one that answers
# "cancelled", so "no answer" needs a value of its own.
NO_ANSWER = object()


def _prompt(session_id: str, text: str) -> dict:
    return {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]}


class Client:
    """A minimal ACP client over the in-memory transport."""

    def __init__(self, responses=None) -> None:
        self.transport = MemoryTransport()
        self.scripted = ScriptedClient(list(responses or []), default=text_response("ok"))
        self.server = AcpServer(self.transport, client_factory=lambda: self.scripted)
        self._next = 0
        self.answered: set[str] = set()  # the permission requests we have replied to

    @property
    def permissions(self) -> list[dict]:
        """The params of every permission request sent to us, answered or not."""
        return [
            message["params"]
            for message in self.transport.messages
            if message.get("method") == "session/request_permission"
        ]

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

    def wait_update(self, name: str, timeout: float = 5.0) -> dict:
        """Block until an update of that kind arrives and hand back its params."""
        message = self.transport.wait_for(
            lambda message: message.get("method") == "session/update"
            and message["params"]["update"]["sessionUpdate"] == name,
            timeout,
        )
        return message["params"]

    def answer_text(self) -> str:
        """Everything the agent said as message text, joined."""
        return "".join(
            update["update"]["content"]["text"] for update in self.updates("agent_message_chunk")
        )

    def initialize(self) -> dict:
        return self.call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {"fs": {"readTextFile": True}},
                "clientInfo": {"name": "test-client", "title": "Test Client", "version": "0.0.1"},
            },
        )

    def new_session(self, cwd: str = PROJECT) -> str:
        if not self.server.initialized:
            self.initialize()
        return self.call("session/new", {"cwd": cwd, "mcpServers": []})["sessionId"]

    def prompt(self, session_id: str, text: str = "hello", *, answer: Any = NO_ANSWER) -> dict:
        """Run a prompt and return the reply, answering a permission request on the way.

        ``answer`` is the option id the client picks, a raw outcome object, or ``NO_ANSWER``
        to keep quiet and let the request time out.
        """
        request_id = self.send("session/prompt", _prompt(session_id, text))
        if answer is not NO_ANSWER:
            self.answer_permission(answer)
        return self.reply_to(request_id)

    def answer_permission(self, answer: str | dict) -> dict:
        """Wait for the permission request the running turn sends, and answer it.

        The turn runs on a server worker while this thread reads the wire, which is how a real
        editor behaves: the question arrives in the middle of the request it belongs to.
        """
        request = self.transport.wait_for(
            lambda message: message.get("method") == "session/request_permission"
            and message.get("id") not in self.answered
        )
        self.answered.add(request["id"])
        outcome = answer if isinstance(answer, dict) else {"outcome": "selected", "optionId": answer}
        self.server.handle_message({"jsonrpc": "2.0", "id": request["id"], "result": {"outcome": outcome}})
        return request

    def cancel(self, session_id: str) -> None:
        self.send("session/cancel", {"sessionId": session_id}, notify=True)

    def wait_busy(self, session_id: str, timeout: float = 5.0) -> None:
        """Block until the turn has reached the model, so a cancel cannot race its start."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.scripted.calls:
                return
            time.sleep(0.01)
        raise AssertionError("the turn never reached the model")


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
    session_id = acp.new_session(PROJECT)
    session = acp.server.sessions[session_id]
    assert session.id == session_id
    # The id is the stored conversation's own, so the client can hand it back to session/load
    # in a later process. An id invented for the connection could not be looked up again.
    assert session_id == session.chat.session_id
    assert session.chat.agent.cwd  # the agent was built for the session
    assert session.chat.platform == "acp"


def test_session_new_needs_the_handshake_first(client):
    acp = client()
    error = acp.error("session/new", {"cwd": PROJECT})
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
        {"cwd": PROJECT, "mcpServers": [{"name": "fs", "command": "/bin/fs", "args": [], "env": []}]},
    )["sessionId"]
    assert acp.server.sessions[session_id].chat is not None


def test_the_method_table_is_the_protocol_we_implement():
    assert set(ACP_METHODS) == {"initialize", "session/new", "session/load", "session/prompt", "session/cancel"}
    # Cancel is read on the thread that reads the socket, not on the pool: it has to be acted
    # on while the prompt it cancels is still occupying a worker.
    assert ACP_METHODS["session/cancel"].inline is True


# ── commands ─────────────────────────────────────────────────────────────────────────────


def test_the_command_list_keeps_only_what_a_client_can_show():
    """The catalog is the terminal's; an editor gets the name, the description and the hint."""
    catalog = [
        {
            "name": "web",
            "description": "Search the web",
            "category": "Info",
            "aliases": ["w"],
            "args_hint": "query",
            "subcommands": [],
            "kind": "builtin",
        },
        {
            "name": "help",
            "description": "List commands",
            "category": "Info",
            "aliases": ["?"],
            "args_hint": "",
            "subcommands": [],
            "kind": "builtin",
        },
    ]
    assert command_list(catalog) == [
        {"name": "web", "description": "Search the web", "input": {"hint": "query"}},
        {"name": "help", "description": "List commands"},  # nothing to type after it
    ]


def test_session_new_tells_the_client_which_commands_it_can_type(client):
    acp = client()
    acp.initialize()
    request_id = acp.send("session/new", {"cwd": PROJECT})
    reply = acp.reply_to(request_id)
    params = acp.wait_update("available_commands_update")
    assert params["sessionId"] == reply["result"]["sessionId"]

    commands = {entry["name"]: entry for entry in params["update"]["availableCommands"]}
    assert {"help", "status", "model"} <= set(commands)
    assert all(entry["description"] for entry in commands.values())
    assert commands["insights"]["input"] == {"hint": "[days]"}
    assert "input" not in commands["help"]

    # The session id is in the reply the client is waiting for; the list follows it, so an
    # editor that keeps state per session never sees a command list for a session it has not
    # been told about.
    reply_at = next(
        index for index, message in enumerate(acp.transport.messages) if message.get("id") == request_id
    )
    update_at = next(
        index
        for index, message in enumerate(acp.transport.messages)
        if message.get("method") == "session/update"
    )
    assert reply_at < update_at


def test_a_command_the_terminal_keeps_to_itself_is_not_offered(client):
    """``quit`` and the rest read the terminal or move its state; an editor has no such thing."""
    acp = client()
    acp.new_session()
    names = {entry["name"] for entry in acp.wait_update("available_commands_update")["update"]["availableCommands"]}
    assert {"quit", "skin", "logs", "copy"}.isdisjoint(names)


def test_a_slash_command_is_answered_by_the_command_and_not_by_the_model(client):
    acp = client()
    session_id = acp.new_session()
    assert acp.prompt(session_id, "/status")["result"] == {"stopReason": "end_turn"}
    assert "Session:" in acp.answer_text()
    assert acp.scripted.calls == []  # the model was never asked


def test_an_unknown_command_is_answered_with_a_refusal_and_not_by_the_model(client):
    acp = client()
    session_id = acp.new_session()
    assert acp.prompt(session_id, "/nope")["result"] == {"stopReason": "end_turn"}
    assert "Unknown command: /nope" in acp.answer_text()
    assert acp.scripted.calls == []


def test_a_terminal_only_command_typed_at_an_editor_is_refused(client):
    acp = client()
    session_id = acp.new_session()
    acp.prompt(session_id, "/quit")
    assert "only available in the terminal" in acp.answer_text()
    assert acp.scripted.calls == []
    assert acp.server.sessions  # the session is still there: nothing quit


def test_a_message_that_only_looks_like_a_command_goes_to_the_model(client):
    acp = client([text_response("yes, / is the root directory")])
    session_id = acp.new_session()
    assert acp.prompt(session_id, "/ is the root directory, right?")["result"] == {
        "stopReason": "end_turn"
    }
    assert len(acp.scripted.calls) == 1  # "/ " is text, not a command


# ── loading a session ────────────────────────────────────────────────────────────────────


def _a_stored_conversation(client, clite_home) -> str:
    """One real turn, kept in the store, as a conversation an editor could come back to."""
    (clite_home / "notes.txt").write_text("hello from the file\n")
    writer = client(
        [tool_call_response(("read_file", {"path": "notes.txt"})), text_response("it says hello")]
    )
    session_id = writer.new_session(str(clite_home))
    writer.prompt(session_id, "read the notes")
    return session_id


def test_session_load_replays_the_stored_conversation(client, clite_home):
    stored = _a_stored_conversation(client, clite_home)

    acp = client()  # a new connection: the editor coming back to yesterday's conversation
    acp.initialize()
    request_id = acp.send("session/load", {"sessionId": stored, "cwd": str(clite_home)})
    reply = acp.reply_to(request_id)
    acp.wait_update("available_commands_update")

    kinds = [update["update"]["sessionUpdate"] for update in acp.updates()]
    assert kinds[:4] == ["user_message_chunk", "tool_call", "tool_call_update", "agent_message_chunk"]
    assert kinds[-1] == "available_commands_update"  # the list still follows the reply

    user = acp.updates("user_message_chunk")[0]
    assert user["sessionId"] == stored  # the id the store knows, not one of ours
    assert user["update"]["content"]["text"] == "read the notes"

    start = acp.updates("tool_call")[0]["update"]
    assert start["toolCallId"] == "call_0_read_file"
    assert start["kind"] == "read" and start["title"] == "notes.txt"
    assert start["rawInput"] == {"path": "notes.txt"}

    done = acp.updates("tool_call_update")[0]["update"]
    assert done["toolCallId"] == start["toolCallId"]
    assert done["status"] == "completed"
    assert "hello from the file" in done["content"][0]["content"]["text"]

    assert acp.updates("agent_message_chunk")[0]["update"]["content"]["text"] == "it says hello"
    assert reply["result"] == {}  # the replay is the message; the result is the end of it

    # The whole conversation goes out before the reply, and the command list after it.
    update_at = [
        index
        for index, message in enumerate(acp.transport.messages)
        if message.get("method") == "session/update"
    ]
    reply_at = next(
        index for index, message in enumerate(acp.transport.messages) if message.get("id") == request_id
    )
    assert max(update_at[:-1]) < reply_at < update_at[-1]


def test_a_replayed_result_is_clipped_like_a_live_one(client, clite_home):
    """A replay is not a way around the limit that keeps a huge file off the wire."""
    (clite_home / "big.txt").write_text("x" * 4000 + "\n")
    writer = client(
        [tool_call_response(("read_file", {"path": "big.txt"})), text_response("that is a lot")]
    )
    stored = writer.new_session(str(clite_home))
    writer.prompt(stored, "read the big file")

    acp = client()
    acp.initialize()
    acp.call("session/load", {"sessionId": stored, "cwd": str(clite_home)})
    text = acp.updates("tool_call_update")[0]["update"]["content"][0]["content"]["text"]
    assert len(text) == RESULT_PREVIEW_CHARS


def test_a_replay_leaves_out_what_the_agent_wrote_for_itself(client):
    acp = client()
    session_id = acp.new_session()
    session = acp.server.sessions[session_id]
    session.chat.agent.messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "[keep going]", "display_kind": "internal"},
        {
            "role": "assistant",
            "content": None,  # a turn that only called a tool says nothing of its own
            "tool_calls": [{"id": "call_1", "function": {"name": "terminal", "arguments": "not json"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "terminal", "content": '{"error": "boom"}'},
    ]
    session.replay()

    kinds = [update["update"]["sessionUpdate"] for update in acp.updates()]
    assert kinds == ["user_message_chunk", "tool_call", "tool_call_update"]
    assert acp.updates("user_message_chunk")[0]["update"]["content"]["text"] == "hello"
    # The request the agent wrote itself is not shown as something the user said.
    call = acp.updates("tool_call")[0]["update"]
    assert call["rawInput"] == {}  # arguments that were not JSON, not a call that is lost
    assert acp.updates("tool_call_update")[0]["update"]["status"] == "failed"


def test_a_loaded_session_carries_on_the_conversation(client, clite_home):
    stored = _a_stored_conversation(client, clite_home)

    acp = client([text_response("yes, still here")])
    acp.initialize()
    acp.call("session/load", {"sessionId": stored, "cwd": str(clite_home)})
    assert acp.prompt(stored, "are you still there?")["result"] == {"stopReason": "end_turn"}
    # The model was given the old conversation, not a fresh one with just the new message.
    sent = acp.scripted.calls[0]["messages"]
    assert any(message.get("content") == "read the notes" for message in sent)


def test_session_load_needs_a_session_that_exists(client, clite_home):
    acp = client()
    acp.initialize()
    error = acp.error("session/load", {"sessionId": "20260101_000000_deadbeef", "cwd": str(clite_home)})
    assert error["code"] == 4001 and "20260101_000000_deadbeef" in error["message"]
    assert acp.server.sessions == {}


def test_loading_a_session_that_is_already_open_is_refused(client, clite_home):
    stored = _a_stored_conversation(client, clite_home)
    acp = client()
    acp.initialize()
    assert acp.call("session/load", {"sessionId": stored, "cwd": str(clite_home)}) == {}
    error = acp.error("session/load", {"sessionId": stored, "cwd": str(clite_home)})
    assert error["code"] == -32600 and "already open" in error["message"]


def test_session_load_needs_the_handshake_first(client, clite_home):
    acp = client()
    error = acp.error("session/load", {"sessionId": "whatever", "cwd": str(clite_home)})
    assert error["code"] == -32600 and "initialize" in error["message"]


@pytest.mark.parametrize("cwd", ["", "project", "./project", None, 7])
def test_session_load_needs_an_absolute_cwd(client, cwd):
    acp = client()
    acp.initialize()
    error = acp.error("session/load", {"sessionId": "anything", "cwd": cwd})
    assert error["code"] in (-32602, -32600)
    assert acp.server.sessions == {}


# ── a turn ───────────────────────────────────────────────────────────────────────────────


def test_a_prompt_answers_with_the_end_of_a_turn_and_streams_the_text_first(client):
    acp = client([text_response("the answer", reasoning="thinking it over")])
    session_id = acp.new_session()
    assert acp.prompt(session_id, "a question")["result"] == {"stopReason": "end_turn"}
    chunks = [update["update"] for update in acp.updates("agent_message_chunk")]
    assert chunks == [{"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "the answer"}}]
    thoughts = [update["update"] for update in acp.updates("agent_thought_chunk")]
    assert [thought["content"]["text"] for thought in thoughts] == ["thinking it over"]
    # Every update belongs to the session the prompt named.
    assert {update["sessionId"] for update in acp.updates()} == {session_id}


def test_a_prompt_needs_a_session_that_exists(client):
    acp = client()
    acp.initialize()
    error = acp.error("session/prompt", _prompt("sess_missing", "hello"))
    assert error["code"] == 4001


def test_a_second_prompt_while_one_runs_is_session_busy(client):
    def blocked(cancel, **kwargs):
        cancel.wait(5)
        raise InterruptedError

    acp = client([blocked, text_response("done")])
    session_id = acp.new_session()
    first = acp.send("session/prompt", _prompt(session_id, "long task"))
    acp.wait_busy(session_id)
    error = acp.error("session/prompt", _prompt(session_id, "another"))
    assert error["code"] == 4002
    acp.cancel(session_id)
    assert acp.reply_to(first)["result"] == {"stopReason": "cancelled"}


def test_cancel_stops_the_running_turn_and_is_never_answered(client):
    def blocked(cancel, **kwargs):
        cancel.wait(5)
        raise InterruptedError

    acp = client([blocked])
    session_id = acp.new_session()
    request_id = acp.send("session/prompt", _prompt(session_id, "long task"))
    acp.wait_busy(session_id)
    before = len(acp.transport.messages)
    acp.cancel(session_id)
    reply = acp.reply_to(request_id)
    assert reply["result"] == {"stopReason": "cancelled"}
    # Cancelling is a notification: nothing comes back on its own account. The only message
    # after it is the prompt's own reply.
    assert [message for message in acp.transport.messages[before:] if message is not reply] == []


def test_cancelling_a_session_that_is_gone_is_not_an_error(client):
    """A client may cancel after its turn already ended, or name a session that was closed.

    There is nothing the editor could do with an error here, so there is none — whether the
    cancel arrives as the notification it should be or, as some clients send it, as a request.
    """
    acp = client()
    acp.initialize()
    assert acp.call("session/cancel", {"sessionId": "sess_never_existed"}) == {}
    acp.cancel("sess_never_existed")
    assert acp.initialize()["protocolVersion"] == PROTOCOL_VERSION  # still usable


@pytest.mark.parametrize(
    "blocks",
    [
        [],
        "hello",
        [{"type": "image", "data": "..."}],
        [{"type": "resource_link", "uri": "file:///etc/hosts"}],
        [{"type": "audio", "data": "..."}],
        # A block that carries text *and* is not text: the type decides, not the presence of
        # a string the agent could fall back on.
        [{"type": "resource_link", "uri": "file:///etc/hosts", "text": "looks like a prompt"}],
        [{"type": "text"}],
        ["not a block"],
    ],
)
def test_a_prompt_that_is_not_text_is_refused(client, blocks):
    """The handshake announced text-only prompts, so anything else is the client's bug."""
    acp = client()
    session_id = acp.new_session()
    error = acp.error("session/prompt", {"sessionId": session_id, "prompt": blocks})
    assert error["code"] == -32602 and "prompt" in error["message"]


def test_a_prompt_needs_a_session_id(client):
    acp = client()
    acp.initialize()
    error = acp.error("session/prompt", {"prompt": [{"type": "text", "text": "hello"}]})
    assert error["code"] == -32602


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (TurnResult(final_response="hi", completed=True, exit_reason="completed"), "end_turn"),
        (TurnResult(final_response="", completed=False, interrupted=True, exit_reason="interrupted"), "cancelled"),
        (TurnResult(final_response="no", completed=False, exit_reason="refusal"), "refusal"),
        (TurnResult(final_response="", completed=False, exit_reason="budget_exhausted"), "max_turn_requests"),
    ],
)
def test_the_stop_reason_comes_from_the_turn_the_agent_reported(result, expected):
    assert stop_reason(result) == expected


def test_a_turn_that_ended_without_an_answer_is_an_error_not_a_stop_reason():
    """An empty reply shown as ``end_turn`` would look like the agent had nothing to say."""
    with pytest.raises(AcpError) as raised:
        stop_reason(TurnResult(final_response="", completed=False, error="boom", exit_reason="api_error:server"))
    assert raised.value.code == 4003 and "boom" in raised.value.message


# ── tool calls and permissions ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("read_file", "read"),
        ("vision_analyze", "read"),
        ("search_files", "search"),
        ("session_search", "search"),
        ("web_fetch", "fetch"),
        ("web_search", "fetch"),
        ("write_file", "edit"),
        ("patch", "edit"),
        ("terminal", "execute"),
        ("execute_code", "execute"),
        # A tool the protocol has no word for is still shown, as "other".
        ("todo", "other"),
        ("a_tool_added_next_week", "other"),
    ],
)
def test_a_tool_call_kind_says_what_the_tool_does(name, kind):
    assert tool_kind(name) == kind


def test_a_tool_call_streams_before_its_result(client, clite_home):
    (clite_home / "notes.txt").write_text("hello from the tool\n")
    acp = client(
        [
            tool_call_response(("read_file", {"path": "notes.txt"})),
            text_response("the file says hello"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    assert acp.prompt(session_id, "read the file")["result"] == {"stopReason": "end_turn"}

    start = next(update["update"] for update in acp.updates("tool_call"))
    assert start["toolCallId"] == "call_0_read_file"
    assert start["title"] == "notes.txt"  # what the editor shows next to the kind's verb
    assert start["kind"] == "read"
    assert start["status"] == "in_progress"
    assert start["rawInput"] == {"path": "notes.txt"}
    assert start["locations"] == [{"path": "notes.txt"}]  # an editor can open the file

    done = next(update["update"] for update in acp.updates("tool_call_update"))
    assert done["toolCallId"] == start["toolCallId"]
    assert done["status"] == "completed"
    assert "hello from the tool" in done["content"][0]["content"]["text"]

    # The call is announced before it finishes, and both before the turn's reply.
    order = [
        message["params"]["update"]["sessionUpdate"]
        for message in acp.transport.messages
        if message.get("method") == "session/update"
    ]
    assert order.index("tool_call") < order.index("tool_call_update")


def test_a_tool_call_that_fails_is_reported_as_failed(client, clite_home):
    acp = client(
        [
            tool_call_response(("read_file", {"path": str(clite_home / "missing.txt")})),
            text_response("it is gone"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    assert acp.prompt(session_id, "read it")["result"] == {"stopReason": "end_turn"}
    done = next(update["update"] for update in acp.updates("tool_call_update"))
    assert done["status"] == "failed"
    assert "not found" in done["content"][0]["content"]["text"].lower()


# ── the plan ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("todos", "entries"),
    [
        ([], []),
        (
            [{"id": "1", "content": "read the spec", "status": "in_progress"}],
            [{"content": "read the spec", "priority": "medium", "status": "in_progress"}],
        ),
        (
            [{"content": "one", "status": "pending"}, {"content": "two", "status": "completed"}],
            [
                {"content": "one", "priority": "medium", "status": "pending"},
                {"content": "two", "priority": "medium", "status": "completed"},
            ],
        ),
        # ACP knows three statuses; a task we dropped is not one of them, and showing it as
        # completed would say the work was done.
        ([{"content": "dropped", "status": "cancelled"}], []),
        # A status from nowhere (an old file, a hand-written list) gets the same treatment.
        ([{"content": "someday", "status": "later"}], []),
        # Nothing in the task list is a priority, so everything is the middle one.
        ([{"content": "one", "status": "pending", "priority": "high"}], [{"content": "one", "priority": "medium", "status": "pending"}]),
    ],
)
def test_the_plan_is_the_task_list_in_the_protocols_own_words(todos, entries):
    assert plan_entries(todos) == entries


def test_the_todo_tool_turns_the_task_list_into_the_sessions_plan(client, clite_home):
    acp = client(
        [
            tool_call_response(
                (
                    "todo",
                    {
                        "todos": [
                            {"id": "1", "content": "read the spec", "status": "completed"},
                            {"id": "2", "content": "write the code", "status": "in_progress"},
                            {"id": "3", "content": "drop this", "status": "cancelled"},
                        ]
                    },
                )
            ),
            text_response("I have a plan"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    assert acp.prompt(session_id, "plan this")["result"] == {"stopReason": "end_turn"}

    plans = acp.updates("plan")
    assert len(plans) == 1
    assert plans[0]["sessionId"] == session_id
    assert plans[0]["update"]["entries"] == [
        {"content": "read the spec", "priority": "medium", "status": "completed"},
        {"content": "write the code", "priority": "medium", "status": "in_progress"},
    ]

    # The plan follows the call that changed it, and both come before the turn's reply.
    order = [
        message["params"]["update"]["sessionUpdate"]
        for message in acp.transport.messages
        if message.get("method") == "session/update"
    ]
    assert order.index("tool_call_update") < order.index("plan")


def test_the_plan_is_sent_whole_every_time(client, clite_home):
    """The client replaces its plan with what it is sent, so a partial list would drop items."""
    acp = client(
        [
            tool_call_response(
                (
                    "todo",
                    {
                        "todos": [
                            {"id": "1", "content": "one", "status": "pending"},
                            {"id": "2", "content": "two", "status": "pending"},
                        ]
                    },
                )
            ),
            tool_call_response(
                ("todo", {"todos": [{"id": "2", "content": "two", "status": "completed"}], "merge": True})
            ),
            text_response("done"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    assert acp.prompt(session_id, "plan this")["result"] == {"stopReason": "end_turn"}

    plans = acp.updates("plan")
    assert len(plans) == 2
    # The second call only mentions task 2, but the plan still carries task 1.
    assert plans[1]["update"]["entries"] == [
        {"content": "one", "priority": "medium", "status": "pending"},
        {"content": "two", "priority": "medium", "status": "completed"},
    ]


def test_only_the_todo_tool_puts_a_plan_on_the_wire(client, clite_home):
    (clite_home / "notes.txt").write_text("hi\n")
    acp = client([tool_call_response(("read_file", {"path": "notes.txt"})), text_response("read")])
    session_id = acp.new_session(str(clite_home))
    acp.prompt(session_id, "read it")
    assert acp.updates("plan") == []


def _dangerous_command(target) -> str:
    """A command the approval gate flags, and that is harmless enough to really run."""
    return f"chmod 777 {target}"


@pytest.mark.platforms("posix")
def test_a_dangerous_command_asks_the_client_and_runs_only_when_allowed(client, clite_home):
    target = clite_home / "approve.txt"
    target.write_text("x\n")
    target.chmod(0o644)
    acp = client(
        [
            tool_call_response(("terminal", {"command": _dangerous_command(target)})),
            text_response("done"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    assert acp.prompt(session_id, "loosen the file", answer="allow_once")["result"] == {
        "stopReason": "end_turn"
    }

    assert len(acp.permissions) == 1
    request = acp.permissions[0]
    assert request["sessionId"] == session_id
    assert request["toolCall"]["toolCallId"] == "call_0_terminal"
    assert request["toolCall"]["kind"] == "execute"
    assert request["toolCall"]["rawInput"] == {"command": _dangerous_command(target)}
    assert request["toolCall"]["title"].startswith("chmod 777 ")  # the preview line, clipped
    assert "sessionUpdate" not in request["toolCall"]  # a ToolCallUpdate, not an update event
    assert [option["kind"] for option in request["options"]] == [
        "allow_once",
        "allow_once",
        "allow_always",
        "reject_once",
    ]
    assert [option["optionId"] for option in request["options"]] == [
        option["optionId"] for option in PERMISSION_OPTIONS
    ]

    done = next(update["update"] for update in acp.updates("tool_call_update"))
    assert done["status"] == "completed"
    assert oct(target.stat().st_mode & 0o777) == "0o777"


@pytest.mark.platforms("posix")
def test_a_rejected_command_never_runs(client, clite_home):
    target = clite_home / "keep.txt"
    target.write_text("x\n")
    target.chmod(0o644)
    acp = client(
        [
            tool_call_response(("terminal", {"command": _dangerous_command(target)})),
            text_response("I did not run it"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    acp.prompt(session_id, "loosen the file", answer="reject_once")
    done = next(update["update"] for update in acp.updates("tool_call_update"))
    assert done["status"] == "failed"
    assert "denied" in done["content"][0]["content"]["text"]
    assert oct(target.stat().st_mode & 0o777) == "0o644"  # untouched


@pytest.mark.platforms("posix")
@pytest.mark.parametrize("answer", [{"outcome": "cancelled"}, "an_option_we_never_offered"])
def test_an_answer_that_is_not_one_of_our_options_is_a_refusal(client, clite_home, answer):
    target = clite_home / "keep.txt"
    target.write_text("x\n")
    target.chmod(0o644)
    acp = client(
        [
            tool_call_response(("terminal", {"command": _dangerous_command(target)})),
            text_response("all right"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    acp.prompt(session_id, "loosen the file", answer=answer)
    done = next(update["update"] for update in acp.updates("tool_call_update"))
    assert done["status"] == "failed"
    assert oct(target.stat().st_mode & 0o777) == "0o644"


@pytest.mark.platforms("posix")
def test_a_client_that_never_answers_is_taken_as_a_no(client, clite_home):
    """A permission request is a question, and a question left hanging is not a yes."""
    target = clite_home / "keep.txt"
    target.write_text("x\n")
    target.chmod(0o644)
    (clite_home / "config.yaml").write_text(MOCK + "approvals:\n  timeout: 0.2\n")
    acp = client(
        [
            tool_call_response(("terminal", {"command": _dangerous_command(target)})),
            text_response("I did not run it"),
        ]
    )
    session_id = acp.new_session(str(clite_home))
    # Our client never answers, so the prompt comes back only after the request times out.
    assert acp.prompt(session_id, "loosen the file")["result"] == {"stopReason": "end_turn"}
    assert len(acp.permissions) == 1
    done = next(update["update"] for update in acp.updates("tool_call_update"))
    assert done["status"] == "failed"
    assert oct(target.stat().st_mode & 0o777) == "0o644"


def test_approval_outside_a_tool_call_still_has_a_call_to_point_at(client, clite_home):
    """The protocol wants the request to name a tool call; a question about nothing is not one."""
    acp = client()
    session = acp.server.new_session(cwd=str(clite_home))
    asked: list[dict] = []

    def answer() -> None:
        request = acp.transport.wait_for(
            lambda message: message.get("method") == "session/request_permission"
        )
        asked.append(request["params"]["toolCall"])
        acp.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
            }
        )

    waiter = threading.Thread(target=answer)
    waiter.start()
    choice = session.chat.callbacks.approve(
        command="chmod 777 /tmp/x", description="make it world-writable", pattern_keys=["chmod_world_writable"]
    )
    waiter.join(timeout=5)
    assert choice == "once"
    assert asked[0]["toolCallId"].startswith("approval-")
    assert asked[0]["kind"] == "execute" and asked[0]["rawInput"] == {"command": "chmod 777 /tmp/x"}


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (None, "deny"),  # no answer: timeout, a dead connection, a client that said nothing
        ({}, "deny"),
        ({"outcome": {"outcome": "cancelled"}}, "deny"),
        ({"outcome": {"outcome": "selected", "optionId": "allow_once"}}, "once"),
        ({"outcome": {"outcome": "selected", "optionId": "allow_session"}}, "session"),
        ({"outcome": {"outcome": "selected", "optionId": "allow_always"}}, "always"),
        ({"outcome": {"outcome": "selected", "optionId": "reject_once"}}, "deny"),
        ({"outcome": {"outcome": "selected", "optionId": "surprise_me"}}, "deny"),
        ({"outcome": {"outcome": "selected", "optionId": 7}}, "deny"),  # not even an option id
        ("yes please", "deny"),  # not even an object
    ],
)
def test_the_answer_to_a_permission_request_becomes_an_approval_choice(reply, expected):
    assert permission_choice(reply) == expected


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
            yield _line(2, "session/new", {"cwd": PROJECT, "mcpServers": []})

    sys.stdout = wire  # in the real process this is the pipe the editor reads
    try:
        assert serve_stdio(stdin=NoisyInput(), stdout=wire) == 0
        assert sys.stdout is wire  # the redirect did not outlive the server
    finally:
        sys.stdout = saved_stdout
    lines = [line for line in wire.getvalue().splitlines() if line.strip()]
    messages = [json.loads(line) for line in lines]  # every line is a protocol message
    replies = [message["id"] for message in messages if "id" in message]
    assert sorted(replies) == [1, 2]  # both requests were answered
    assert "stray output" not in wire.getvalue()


@pytest.mark.platforms("posix")
def test_a_turn_with_a_tool_call_and_a_permission_request_over_real_pipes(clite_home):
    """The whole way, with nothing scripted at the Python level.

    A real ``clite acp`` process, the offline ``mock`` provider (driven by the directive in the
    prompt), a real approval gate asking us over the pipe, and a real ``chmod`` running. The
    client here is the editor: it reads what arrives and answers the question it is asked.
    """
    (clite_home / "config.yaml").write_text(MOCK + "approvals:\n  mode: manual\n  timeout: 10\n")
    target = clite_home.parent / "approved.txt"  # outside the agent's home, as a project file is
    target.write_text("x\n")
    target.chmod(0o644)
    command = f"chmod 777 {target}"
    env = {**os.environ, "CLITE_HOME": str(clite_home), "PYTHONPATH": os.pathsep.join(sys.path)}
    process = subprocess.Popen(
        [sys.executable, "-m", "clite.acp.entry"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    seen: list[dict] = []

    def send(message: dict) -> None:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def read_until(predicate):
        """Read protocol messages, answering a permission request the way an editor would."""
        while True:
            line = process.stdout.readline()
            assert line, f"the server exited early: {process.stderr.read()}"
            message = json.loads(line)  # every line on stdout is a protocol message
            seen.append(message)
            if message.get("method") == "session/request_permission":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
                    }
                )
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
        session_id = read_until(lambda m: m.get("id") == 2)["result"]["sessionId"]
        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": _prompt(session_id, f"!terminal {json.dumps({'command': command})}"),
            }
        )
        # The permission request arrives between here and the reply; read_until answers it.
        assert read_until(lambda m: m.get("id") == 3)["result"] == {"stopReason": "end_turn"}
    finally:
        process.stdin.close()
        assert process.wait(timeout=30) == 0

    requests = [message for message in seen if message.get("method") == "session/request_permission"]
    assert len(requests) == 1  # asked once, not again for the tool result that followed
    assert requests[0]["params"]["toolCall"]["rawInput"] == {"command": command}
    assert requests[0]["params"]["toolCall"]["kind"] == "execute"
    updates = [
        message["params"]["update"] for message in seen if message.get("method") == "session/update"
    ]
    names = [update["sessionUpdate"] for update in updates]
    assert names.index("tool_call") < names.index("tool_call_update")
    assert updates[names.index("tool_call_update")]["status"] == "completed"
    assert oct(target.stat().st_mode & 0o777) == "0o777"  # the command really ran


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
        session_id = read_until(lambda m: m.get("id") == 2)["result"]["sessionId"]
        assert session_id  # the store's own id, handed back by session/new
    finally:
        process.stdin.close()
        assert process.wait(timeout=30) == 0
