"""The gateway: authorization, session routing, commands, busy handling, approvals over chat."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from clite.core.config import load_config
from clite.gateway.event import CHAT_GROUP, SendResult, SessionSource
from clite.gateway.pairing import PairingStore
from clite.gateway.platforms.base import split_message
from clite.gateway.runner import GatewayRunner
from clite.gateway.session import build_session_key
from clite.plugins.hooks import get_hook_bus
from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.state import get_session_db

CONFIG = """
model: {{provider: mock, default: mock-1}}
gateway:
  platforms:
    local: {{enabled: true, allowed_users: [{allowed}]}}
{extra}
"""


@pytest.fixture
def gateway(clite_home):
    runners = []

    def factory(responses=None, *, allowed="owner", extra=""):
        (clite_home / "config.yaml").write_text(CONFIG.format(allowed=allowed, extra=extra))
        client = ScriptedClient(list(responses or []), default=text_response("ok"))
        runner = GatewayRunner(client_factory=lambda: client)
        assert runner.start(with_cron=False) == ["local"]
        runners.append(runner)
        return runner, runner.adapters["local"], client

    yield factory
    for runner in runners:
        runner.stop()


# ── session keys ─────────────────────────────────────────────────────────────────────────


def test_session_keys():
    dm = SessionSource("telegram", chat_id="42", user_id="42")
    group = SessionSource("telegram", chat_id="-100", user_id="7", chat_type=CHAT_GROUP)
    topic = SessionSource("telegram", chat_id="-100", user_id="7", chat_type=CHAT_GROUP, thread_id="9")
    assert build_session_key(dm) == "telegram:dm:42"
    assert build_session_key(group) == "telegram:group:-100:user:7"
    assert build_session_key(group, group_sessions_per_user=False) == "telegram:group:-100"
    assert build_session_key(topic) == "telegram:group:-100:thread:9:user:7"


def test_long_replies_are_split_on_natural_boundaries():
    text = ("paragraph one. " * 20).strip() + "\n\n" + ("paragraph two. " * 20).strip()
    chunks = split_message(text, 400)
    assert all(len(chunk) <= 400 for chunk in chunks) and len(chunks) == 2
    assert chunks[0].endswith("one.") and chunks[1].startswith("paragraph two.")
    assert split_message("x" * 1000, 300) == ["x" * 300, "x" * 300, "x" * 300, "x" * 100]
    assert split_message("short", 300) == ["short"]


# ── the basic exchange ───────────────────────────────────────────────────────────────────


def test_message_in_reply_out(gateway):
    runner, local, client = gateway([text_response("Hello from the agent.")])
    local.inject("hi there", user_id="owner")
    assert local.wait_for_messages(1) == ["Hello from the agent."]
    assert local.typing == ["owner"]
    request = client.calls[0]
    assert request["messages"][-1]["content"] == "hi there"
    assert "messaging gateway" in request["messages"][0]["content"]  # the platform hint for this surface
    row = get_session_db().list_sessions(sources=["local"])[0]
    assert row["session_key"] == "local:dm:owner" and row["user_id"] == "owner"


def test_continuous_typing_heartbeat_during_long_turn(gateway, monkeypatch):
    import clite.gateway.live_reply as live_reply

    monkeypatch.setattr(live_reply, "DEFAULT_TYPING_INTERVAL", 0.05)

    def slow_model(messages, **kwargs):
        deadline = time.monotonic() + 1.0
        while len(local.typing) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        return text_response("Done after multiple typing refreshes.")

    runner, local, client = gateway([slow_model])
    local.inject("take your time", user_id="owner")
    assert local.wait_for_messages(1) == ["Done after multiple typing refreshes."]
    # The typing keeper should have pulsed at least 3 times
    assert len(local.typing) >= 3
    assert all(t == "owner" for t in local.typing)
    count_after_reply = len(local.typing)
    time.sleep(0.12)
    # Once reply is sent, heartbeat must stop and send no further typing indicators
    assert len(local.typing) == count_after_reply


def test_continuous_typing_heartbeat_stops_on_exception(gateway, monkeypatch):
    import clite.gateway.live_reply as live_reply

    monkeypatch.setattr(live_reply, "DEFAULT_TYPING_INTERVAL", 0.05)

    def failing_submit(*args, **kwargs):
        deadline = time.monotonic() + 1.0
        while len(local.typing) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        raise RuntimeError("turn crashed")

    runner, local, client = gateway()
    # Replace session.chat.submit before turn runs
    original_submit = runner._submit

    def custom_submit(session, text, *, payload=None):
        session.chat.submit = failing_submit
        original_submit(session, text, payload=payload)

    runner._submit = custom_submit
    local.inject("will fail", user_id="owner")
    (reply,) = local.wait_for_messages(1)
    assert "Something went wrong: RuntimeError: turn crashed" in reply
    count_after_error = len(local.typing)
    time.sleep(0.12)
    assert len(local.typing) == count_after_error


def test_continuous_typing_heartbeat_stops_when_first_reply_is_sent(gateway, monkeypatch):
    import clite.gateway.live_reply as live_reply

    monkeypatch.setattr(live_reply, "DEFAULT_TYPING_INTERVAL", 0.05)
    typing_stopped_before_or_at_send = threading.Event()

    def check_send(text: str) -> None:
        pass

    runner, local, client = gateway([text_response("Hello!")])

    orig_send = local.send

    def instrumented_send(chat_id, text, **kwargs):
        # When first send is called, typing heartbeat must be stopped or stop event set
        typing_stopped_before_or_at_send.set()
        return orig_send(chat_id, text, **kwargs)

    local.send = instrumented_send  # type: ignore[method-assign]

    local.inject("fast reply", user_id="owner")
    assert local.wait_for_messages(1) == ["Hello!"]
    assert typing_stopped_before_or_at_send.is_set()
    count_after_reply = len(local.typing)
    time.sleep(0.12)
    assert len(local.typing) == count_after_reply


def test_each_chat_has_its_own_session_and_restarts_resume_it(gateway, clite_home):
    runner, local, client = gateway(allowed="alice, bob")
    local.inject("I am Alice", user_id="alice")
    local.inject("I am Bob", user_id="bob")
    local.wait_for_messages(2)
    assert len(runner.sessions) == 2
    alice_session = runner.sessions["local:dm:alice"].chat.session_id
    runner.stop()

    runner, local, client = gateway(allowed="alice, bob")
    local.inject("still me", user_id="alice")
    local.wait_for_messages(1)
    assert runner.sessions["local:dm:alice"].chat.session_id == alice_session
    assert [m["content"] for m in client.calls[-1]["messages"][1:]] == ["I am Alice", "ok", "still me"]


def test_group_members_get_separate_sessions(gateway):
    runner, local, _ = gateway(allowed="alice, bob")
    local.inject("hello", user_id="alice", chat_id="room", chat_type=CHAT_GROUP)
    local.inject("hello", user_id="bob", chat_id="room", chat_type=CHAT_GROUP)
    local.wait_for_messages(2)
    assert set(runner.sessions) == {"local:group:room:user:alice", "local:group:room:user:bob"}


def test_long_reply_is_sent_in_chunks(gateway):
    runner, local, _ = gateway([text_response("word " * 1000)])
    local.inject("write a lot", user_id="owner")
    messages = local.wait_for_messages(3)
    assert all(len(message) <= local.max_message_length for message in messages)


# ── authorization and pairing ────────────────────────────────────────────────────────────


def test_stranger_gets_a_pairing_code_and_is_let_in_once_approved(gateway):
    runner, local, client = gateway()
    local.inject("let me in", user_id="stranger")
    (reply,) = local.wait_for_messages(1)
    assert "clite gateway pair approve local" in reply and client.calls == []
    code = reply.split("pair approve local ")[1].split()[0]

    local.inject("hello?", user_id="stranger")  # asking again within the window is ignored
    time.sleep(0.1)
    assert len(local.outbox) == 1

    assert (
        runner.pairing.approve("local", code.lower())["user_id"] == "stranger"
    )  # codes are case-insensitive
    local.inject("now?", user_id="stranger")
    assert local.wait_for_messages(2)[1] == "ok"


def test_strangers_in_groups_are_ignored(gateway):
    runner, local, client = gateway()
    local.inject("hello bot", user_id="stranger", chat_id="room", chat_type=CHAT_GROUP)
    time.sleep(0.1)
    assert local.outbox == [] and client.calls == []


def test_allow_all_users_opens_the_door(gateway):
    runner, local, _ = gateway(extra="  allow_all_users: true")
    local.inject("hi", user_id="anyone")
    assert local.wait_for_messages(1) == ["ok"]


def test_pairing_store_limits(clite_home):
    store = PairingStore()
    now = 1_000_000.0
    first = store.request_code("telegram", "u1", "User One", now=now)
    assert first and len(first) == 8
    assert store.request_code("telegram", "u1", now=now + 60) is None  # one request per ten minutes
    assert store.request_code("telegram", "u2", now=now) and store.request_code("telegram", "u3", now=now)
    assert store.request_code("telegram", "u4", now=now) is None  # too many pending for this platform
    assert store.approve("telegram", first, now=now + 4000) is None  # expired
    assert store.list(now=now + 10)["pending"]["telegram"]

    fresh = store.request_code("telegram", "u1", now=now + 5000)
    for _ in range(4):
        assert (
            store.approve("telegram", "WRONGCODE", now=now + 5001) is None
        )  # (one failure was counted above)
    with pytest.raises(PermissionError):
        store.approve("telegram", fresh, now=now + 5002)  # locked after five wrong codes
    later = now + 5002 + 3600 + 1  # the lock has expired (and so has that code)
    newest = store.request_code("telegram", "u1", now=later)
    assert store.approve("telegram", newest, now=later + 1) == {"user_id": "u1", "user_name": ""}
    assert (
        store.is_approved("telegram", "u1")
        and store.revoke("telegram", "u1")
        and not store.is_approved("telegram", "u1")
    )


# ── commands and busy handling ───────────────────────────────────────────────────────────


def test_slash_commands_work_in_chat(gateway):
    runner, local, client = gateway()
    local.inject("/status", user_id="owner")
    local.wait_for_text("mock-1 via mock")
    local.inject("first message", user_id="owner")
    local.wait_for_messages(2)
    # Streaming sends the answer before the turn is fully unwound, so wait for the session to
    # go idle before sending a command that is not allowed while busy.
    deadline = time.monotonic() + 5
    while runner.sessions["local:dm:owner"].busy and time.monotonic() < deadline:
        time.sleep(0.02)
    old = runner.sessions["local:dm:owner"].chat.session_id

    local.inject("/new", user_id="owner")
    local.wait_for_text("Started a new session.")
    assert (
        runner.session_map.get("local:dm:owner") != old
    )  # a restart resumes the new session, not the old one
    local.inject("/quit", user_id="owner")
    local.wait_for_text("only available in the terminal")
    local.inject("/approve", user_id="owner")
    local.wait_for_text("Nothing is waiting for approval.")


def test_reset_and_restart_commands_in_chat(gateway):
    restarted = threading.Event()
    runner, local, client = gateway()
    runner.on_restart = restarted.set

    local.inject("/restart", user_id="owner")
    assert "Restarting gateway" in local.wait_for_messages(1)[0]
    assert restarted.is_set()


def test_reset_forces_session_reset_even_when_busy(gateway):
    release = threading.Event()

    def blocked(**kwargs):
        release.wait(5)
        raise InterruptedError

    runner, local, client = gateway([blocked])
    local.inject("long running turn", user_id="owner")
    while not client.calls:
        time.sleep(0.01)

    old_session_id = runner.sessions["local:dm:owner"].chat.session_id
    assert runner.sessions["local:dm:owner"].busy

    local.inject("/reset", user_id="owner")
    msgs = local.wait_for_messages(2)
    assert any("Stopping running turn and resetting session" in m for m in msgs)
    assert any("Started a new session." in m for m in msgs)

    new_session_id = runner.sessions["local:dm:owner"].chat.session_id
    assert new_session_id != old_session_id
    assert runner.session_map.get("local:dm:owner") == new_session_id
    release.set()


def test_a_message_during_a_turn_interrupts_it_by_default(gateway):
    def blocked(cancel, **kwargs):
        cancel.wait(5)
        raise InterruptedError

    runner, local, client = gateway([blocked, text_response("answer to the second message")])
    local.inject("long task", user_id="owner")
    while not client.calls:  # wait until the model call of the first turn is under way
        time.sleep(0.01)
    local.inject("/history", user_id="owner")  # a session command has to wait
    assert "has to wait" in local.wait_for_messages(1)[0]
    local.inject("actually, do this instead", user_id="owner")
    assert local.wait_for_messages(2)[1] == "answer to the second message"
    assert len(local.outbox) == 2  # the interrupted turn sent nothing


def test_a_burst_of_messages_is_answered_as_one(gateway):
    release = threading.Event()

    def slow(**kwargs):
        release.wait(5)
        raise InterruptedError

    runner, local, client = gateway([slow, text_response("answer to both")])
    local.inject("first", user_id="owner")
    while not client.calls:
        time.sleep(0.01)
    local.inject("also this", user_id="owner")
    local.inject("and this", user_id="owner")
    release.set()
    assert local.wait_for_messages(1) == ["answer to both"]
    assert client.calls[-1]["messages"][-1]["content"] == "also this\n\nand this"


def test_queue_mode_runs_messages_in_order(gateway):
    release = threading.Event()

    def slow(**kwargs):
        release.wait(5)
        return text_response("first answer")

    runner, local, _ = gateway(
        [slow, text_response("second answer")], extra="display:\n  busy_input_mode: queue"
    )
    local.inject("one", user_id="owner")
    time.sleep(0.1)
    local.inject("two", user_id="owner")
    release.set()
    assert local.wait_for_messages(2) == ["first answer", "second answer"]


# ── approvals and questions over chat ────────────────────────────────────────────────────


@pytest.mark.platforms("posix")
def test_dangerous_command_is_approved_by_replying(gateway, tmp_path):
    target = tmp_path / "old-build"
    target.mkdir()
    runner, local, _ = gateway(
        [tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Removed.")]
    )
    local.inject("clean the build dir", user_id="owner")
    prompt = local.wait_for_messages(1)[0]
    assert f"rm -rf {target}" in prompt and "/approve" in prompt and target.exists()
    local.inject("maybe?", user_id="owner")
    local.wait_for_text("Please answer")
    local.inject("/approve", user_id="owner")
    local.wait_for_text("Removed.")
    assert not target.exists()


def _with_buttons(adapter: Any) -> dict[str, list[Any]]:
    """Give the in-process adapter button controls, recording what the runner sends."""
    seen: dict[str, list[Any]] = {"pickers": [], "approvals": [], "edits": [], "answers": []}

    def send(kind: str):
        def sender(chat_id: str, text: str, keyboard: Any, *, thread_id: str | None = None) -> SendResult:
            seen[kind].append({"text": text, "keyboard": keyboard})
            return SendResult(True, message_id=f"{kind}-{len(seen[kind])}")

        return sender

    adapter.can_send_buttons = lambda: True
    adapter.send_model_picker = send("pickers")
    adapter.send_approval_prompt = send("approvals")
    adapter.edit_approval_prompt = lambda chat_id, message_id, text, keyboard: seen["edits"].append(text)
    adapter.answer_callback = lambda callback_id, text="": seen["answers"].append(text)
    return seen


def test_model_without_arguments_offers_a_picker_on_any_platform_with_buttons(gateway):
    runner, local, _ = gateway()
    seen = _with_buttons(local)
    local.inject("/model", user_id="owner")
    assert "Choose a provider" in seen["pickers"][0]["text"]
    labels = [button["text"] for row in seen["pickers"][0]["keyboard"] for button in row]
    assert "✓ mock" in labels and "Cancel" in labels
    assert local.outbox == []  # the buttons replaced the text answer


def test_model_without_arguments_answers_in_text_on_a_platform_without_buttons(gateway):
    runner, local, _ = gateway()
    local.inject("/model", user_id="owner")
    assert "mock-1" in local.wait_for_messages(1)[0]


@pytest.mark.platforms("posix")
def test_approval_buttons_are_offered_on_any_platform_with_buttons(gateway, tmp_path):
    target = tmp_path / "old-build"
    target.mkdir()
    runner, local, _ = gateway(
        [tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Removed.")]
    )
    seen = _with_buttons(local)
    local.inject("clean the build dir", user_id="owner")
    deadline = time.monotonic() + 5
    while not seen["approvals"] and time.monotonic() < deadline:
        time.sleep(0.01)
    prompt = seen["approvals"][0]
    assert f"rm -rf {target}" in prompt["text"] and local.outbox == []
    once = next(button for row in prompt["keyboard"] for button in row if button["text"] == "Approve once")

    owner = SessionSource("local", chat_id="owner", user_id="owner")
    runner.handle_approval_callback(owner, "press-1", once["callback_data"], "approvals-1")
    local.wait_for_text("Removed.")
    assert not target.exists()
    assert seen["answers"] == ["Approval recorded."] and seen["edits"] == ["Approval: once."]


@pytest.mark.platforms("posix")
def test_deny_and_silence_both_refuse(gateway, tmp_path):
    target = tmp_path / "keep"
    target.mkdir()
    call = tool_call_response(("terminal", {"command": f"rm -rf {target}"}))
    runner, local, _ = gateway(
        [call, text_response("Left it alone."), call, text_response("No answer, so I did not.")],
        extra="approvals:\n  timeout: 0.3",
    )
    local.inject("clean up", user_id="owner")
    local.wait_for_messages(1)
    local.inject("/deny", user_id="owner")
    local.wait_for_text("Left it alone.")
    local.inject("clean up again", user_id="owner")
    local.wait_for_text("No answer, so I did not.")  # nobody replied within the timeout
    assert target.exists()


@pytest.mark.platforms("posix")
def test_text_approval_accepts_trailing_punctuation_after_the_scope(gateway, tmp_path):
    target = tmp_path / "old-build"
    target.mkdir()
    runner, local, _ = gateway(
        [tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Removed.")]
    )
    local.inject("clean the build dir", user_id="owner")
    local.wait_for_messages(1)
    local.inject("/approve session,", user_id="owner")
    local.wait_for_text("Removed.")
    assert not target.exists()


def test_clarifying_question_is_answered_by_number_or_text(gateway):
    ask = tool_call_response(
        ("clarify", {"question": "Which environment?", "choices": ["staging", "production"]})
    )
    runner, local, _ = gateway([ask, text_response("Deploying to production.")])
    local.inject("deploy", user_id="owner")
    assert local.wait_for_messages(1)[0] == "Which environment?\n1. staging\n2. production"
    local.inject("2", user_id="owner")
    local.wait_for_text("Deploying to production.")
    answer = json.loads(runner.sessions["local:dm:owner"].chat.agent.messages[2]["content"])
    assert answer["answer"] == "production"


# ── hooks, cron delivery, errors ─────────────────────────────────────────────────────────


def test_plugins_can_drop_or_rewrite_incoming_messages(gateway):
    def gate(event):
        if "spam" in event.text:
            return {"action": "skip"}
        if event.text == "ping":
            return {"action": "rewrite", "text": "say pong"}
        return None

    runner, local, client = gateway()
    get_hook_bus().register("pre_gateway_dispatch", gate)
    local.inject("buy spam now", user_id="owner")
    local.inject("ping", user_id="owner")
    local.wait_for_messages(1)
    assert [call["messages"][-1]["content"] for call in client.calls] == ["say pong"]


def test_cron_output_is_delivered_to_its_origin(gateway):
    runner, local, _ = gateway()
    runner.deliver(
        {
            "id": "j1",
            "name": "morning digest",
            "deliver": "origin",
            "origin": {"platform": "local", "chat_id": "owner"},
        },
        "3 PRs need review.",
    )
    runner.deliver({"id": "j2", "name": "", "deliver": "local:ops-room"}, "Disk at 91%.")
    assert local.wait_for_messages(2) == ["[morning digest]\n3 PRs need review.", "[job j2]\nDisk at 91%."]
    assert local.outbox[1]["chat_id"] == "ops-room"
    with pytest.raises(RuntimeError):
        runner.deliver({"id": "j3", "deliver": "slack:general"}, "nobody home")


def test_a_platform_that_fails_to_start_does_not_stop_the_gateway(clite_home):
    (clite_home / "config.yaml").write_text(
        "model: {provider: mock, default: mock-1}\ngateway:\n  platforms:\n"
        "    telegram: {enabled: true}\n    local: {enabled: true}\n    imaginary: {enabled: true}\n    off: {enabled: false}\n"
    )
    runner = GatewayRunner()
    try:
        assert runner.start(with_cron=False) == ["local"]  # telegram has no token; imaginary has no adapter
    finally:
        runner.stop()


def test_a_broken_turn_is_reported_in_chat(gateway):
    from clite.providers.http import ProviderHTTPError

    runner, local, _ = gateway([ProviderHTTPError(400, '{"error": {"message": "bad request"}}', {}, "u")])
    local.inject("hi", user_id="owner")
    assert "bad request" in local.wait_for_messages(1)[0]


def test_idle_sessions_are_closed_and_resumed_from_storage(gateway):
    runner, local, client = gateway(extra="  agent_cache_ttl_seconds: 0.05")
    local.inject("remember me", user_id="owner")
    local.wait_for_messages(1)
    first = runner.sessions["local:dm:owner"]
    time.sleep(0.15)
    local.inject("am I remembered?", user_id="owner")
    local.wait_for_messages(2)
    assert runner.sessions["local:dm:owner"] is not first
    assert [m["content"] for m in client.calls[-1]["messages"][1:]] == [
        "remember me",
        "ok",
        "am I remembered?",
    ]


# ── telegram, against a fake Bot API ─────────────────────────────────────────────────────


class FakeTelegram:
    def __init__(self):
        self.updates, self.sent, self.calls = [], [], []
        self.command_menu_error: str | None = None
        self.markdown_error: str | None = None
        self.lock = threading.Lock()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                method = self.path.rsplit("/", 1)[-1]
                api.calls.append((method, body))
                if "/botgood-token/" not in self.path:
                    return self._reply({"ok": False, "description": "Unauthorized"}, 401)
                if method == "getMe":
                    return self._reply({"ok": True, "result": {"username": "clite_bot"}})
                if method == "setMyCommands" and api.command_menu_error:
                    return self._reply({"ok": False, "description": api.command_menu_error}, 400)
                if method == "getUpdates":
                    with api.lock:
                        pending = [u for u in api.updates if u["update_id"] >= body["offset"]]
                    if not pending:
                        time.sleep(0.05)
                    return self._reply({"ok": True, "result": pending})
                if method == "sendMessage":
                    api.sent.append(body)
                    if body.get("parse_mode") == "MarkdownV2" and api.markdown_error:
                        return self._reply({"ok": False, "description": api.markdown_error}, 400)
                    return self._reply({"ok": True, "result": {"message_id": len(api.sent)}})
                return self._reply({"ok": True, "result": True})

            def _reply(self, payload, status=200):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def push(self, text, *, user=111, chat=111, chat_type="private", **extra):
        with self.lock:
            self.updates.append(
                {
                    "update_id": len(self.updates) + 1,
                    "message": {
                        "message_id": len(self.updates) + 1,
                        "text": text,
                        "chat": {"id": chat, "type": chat_type},
                        "from": {"id": user, "first_name": "Ada", "is_bot": False},
                        **extra,
                    },
                }
            )

    def push_callback(self, data, *, user=111, chat=111, chat_type="private", message_id=1):
        with self.lock:
            self.updates.append(
                {
                    "update_id": len(self.updates) + 1,
                    "callback_query": {
                        "id": f"callback-{len(self.updates) + 1}",
                        "data": data,
                        "from": {"id": user, "first_name": "Ada", "is_bot": False},
                        "message": {
                            "message_id": message_id,
                            "chat": {"id": chat, "type": chat_type},
                            "from": {"username": "clite_bot", "is_bot": True},
                        },
                    },
                }
            )

    def wait_sent(self, count, timeout=5.0):
        deadline = time.monotonic() + timeout
        while len(self.sent) < count and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.sent


@pytest.fixture
def telegram(clite_home, monkeypatch):
    api = FakeTelegram()

    def echo(messages, **kwargs):
        return text_response(f"You said: {messages[-1]['content']}")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "good-token")
    (clite_home / "config.yaml").write_text(
        "model: {provider: demo, default: demo-1}\n"
        "providers:\n  demo: {base_url: 'http://demo.invalid/v1', models: [demo-1, demo-2, demo-3, demo-4, demo-5, demo-6, demo-7, demo-8, demo-9]}\n  alternate: {base_url: 'http://alternate.invalid/v1', models: [alternate-1, alternate-2]}\n"
        "gateway:\n  platforms:\n"
        f"    telegram: {{enabled: true, allowed_users: [111], base_url: '{api.url}', poll_timeout: 1}}\n"
    )
    runner = GatewayRunner(client_factory=lambda: ScriptedClient([echo]))
    assert runner.start(with_cron=False) == ["telegram"]
    yield api, runner
    runner.stop()
    api.httpd.shutdown()
    api.httpd.server_close()


def test_telegram_command_menu_enforces_bot_api_name_description_and_count_limits(monkeypatch):
    from clite.gateway.platforms.telegram import telegram_command_menu
    from clite.runtime.commands import CommandDef

    commands = [CommandDef("invalid-name", "must not be sent")] + [
        CommandDef(f"command_{index}", "x" * 300) for index in range(101)
    ]
    monkeypatch.setattr("clite.runtime.commands.commands_for", lambda surface: commands)

    menu = telegram_command_menu()

    assert len(menu) == 100
    assert all(command["command"].replace("_", "").isalnum() for command in menu)
    assert all(len(command["command"]) <= 32 for command in menu)
    assert all(len(command["description"]) == 256 for command in menu)


def test_telegram_registers_the_supported_slash_commands_in_the_native_menu(telegram):
    from clite.gateway.platforms.telegram import _TELEGRAM_COMMAND_NAME
    from clite.runtime.commands import commands_for

    api, _runner = telegram
    registrations = [body for method, body in api.calls if method == "setMyCommands"]
    assert len(registrations) == 1
    commands = registrations[0]["commands"]
    expected_names: list[str] = []
    seen: set[str] = set()
    for command in commands_for("telegram"):
        for name in (command.name, *command.aliases):
            name_lower = name.lower()
            if name_lower not in seen and _TELEGRAM_COMMAND_NAME.fullmatch(name_lower):
                seen.add(name_lower)
                expected_names.append(name_lower)
    assert [command["command"] for command in commands] == expected_names
    assert "reset" in [command["command"] for command in commands]
    assert "restart" in [command["command"] for command in commands]
    assert len(commands) <= 100
    assert all(1 <= len(command["command"]) <= 32 for command in commands)
    assert all(1 <= len(command["description"]) <= 256 for command in commands)


def test_telegram_starts_when_native_command_menu_registration_fails(clite_home, monkeypatch, caplog):
    api = FakeTelegram()
    api.command_menu_error = "Bot command menu rejected"
    try:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "good-token")
        (clite_home / "config.yaml").write_text(
            "model: {provider: mock, default: mock-1}\ngateway:\n  platforms:\n"
            f"    telegram: {{enabled: true, allowed_users: [111], base_url: '{api.url}', poll_timeout: 1}}\n"
        )
        with caplog.at_level("WARNING", logger="clite.gateway.telegram"):
            runner = GatewayRunner()
            assert runner.start(with_cron=False) == ["telegram"]
        try:
            assert any(method == "setMyCommands" for method, _body in api.calls)
            assert "command menu registration failed" in caplog.text
        finally:
            runner.stop()
    finally:
        api.httpd.shutdown()
        api.httpd.server_close()


def test_telegram_sends_model_markdown_as_safe_markdownv2_with_native_blockquotes(telegram):
    api, runner = telegram
    adapter = runner.adapters["telegram"]

    source = """Before *stars* and [docs](https://example.test/a_(b)).
> First quoted line: `literal_*_`.
> Second quoted line with **bold**.

```python
print("<literal>_*")
```
After!"""
    result = adapter.send("111", source)

    assert result.success is True
    payload = api.sent[-1]
    assert payload["parse_mode"] == "MarkdownV2"
    assert payload["text"] == (
        "Before _stars_ and [docs](https://example.test/a_(b\\))\\.\n"
        "> First quoted line: `literal_*_`\\.\n"
        "> Second quoted line with *bold*\\.\n\n"
        '```python\nprint("<literal>_*")\n```\n'
        "After\\!"
    )


def test_telegram_retries_unparseable_markdown_as_plain_text_without_dropping_the_reply(telegram):
    api, runner = telegram
    api.markdown_error = "Bad Request: can't parse entities"

    result = runner.adapters["telegram"].send("111", "unusual <<< text")

    assert result.success is True
    assert api.sent[-2]["parse_mode"] == "MarkdownV2"
    assert api.sent[-1]["text"] == "unusual <<< text"
    assert "parse_mode" not in api.sent[-1]


def test_telegram_round_trip(telegram):
    api, runner = telegram
    api.push("hello from telegram")
    api.wait_sent(1)
    # The answer streams: the message is sent as soon as the first chunk arrives and then edited
    # into its final form, so the test waits for the final text rather than the first send.
    expected = "You said: hello from telegram"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        texts = [
            body.get("text") for method, body in api.calls if method in ("sendMessage", "editMessageText")
        ]
        if expected in texts:
            break
        time.sleep(0.02)
    else:
        raise AssertionError(f"the answer never became {expected!r}: {texts}")
    assert api.sent[0]["reply_parameters"] == {"message_id": 1}
    assert ("sendChatAction", {"chat_id": "111", "action": "typing"}) in api.calls
    offsets = [body["offset"] for method, body in api.calls if method == "getUpdates"]
    assert offsets[0] == 0 and offsets[-1] == 2  # the update was acknowledged and is not fetched again


def test_telegram_streamed_reply_quotes_only_the_first_chunk_and_keeps_its_topic(telegram):
    api, runner = telegram
    runner.client_factory = lambda: ScriptedClient([text_response("x" * 4_100)])
    api.push("@clite_bot split this", chat=-100, chat_type="supergroup", message_thread_id=77)
    sent = api.wait_sent(2)

    assert [message["message_thread_id"] for message in sent] == [77, 77]
    assert sent[0]["reply_parameters"] == {"message_id": 1}
    assert "reply_parameters" not in sent[1]


def _wait_for_picker_edits(api, count):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        edits = [body for method, body in api.calls if method == "editMessageText"]
        if len(edits) >= count:
            return edits
        time.sleep(0.02)
    raise AssertionError(f"model picker did not produce {count} edit(s): {api.calls}")


def test_telegram_model_picker_selects_a_provider_then_switches_the_chat_model(telegram):
    api, runner = telegram
    api.push("/model")
    picker = api.wait_sent(1)[0]

    assert "Choose a provider" in picker["text"]
    buttons = [button for row in picker["reply_markup"]["inline_keyboard"] for button in row]
    provider = next(button for button in buttons if button["text"].removeprefix("✓ ") == "alternate")
    assert ":provider:" in provider["callback_data"]
    assert len(provider["callback_data"].encode()) <= 64

    api.push_callback(provider["callback_data"], message_id=1)
    provider_view = _wait_for_picker_edits(api, 1)[-1]
    assert "Provider: alternate" in provider_view["text"]
    assert "Choose a model" in provider_view["text"]
    model_buttons = [button for row in provider_view["reply_markup"]["inline_keyboard"] for button in row]
    selection = next(button for button in model_buttons if button["text"] == "alternate-2")

    api.push_callback(selection["callback_data"], message_id=1)
    edits = _wait_for_picker_edits(api, 2)

    assert runner.sessions["telegram:dm:111"].chat.agent.route.provider == "alternate"
    assert runner.sessions["telegram:dm:111"].chat.agent.route.model == "alternate-2"
    assert "Switched to alternate-2" in edits[-1]["text"]
    assert edits[-1]["reply_markup"] == {"inline_keyboard": []}
    assert any(method == "answerCallbackQuery" for method, _body in api.calls)


def test_telegram_model_picker_pages_back_and_cancels_after_provider_selection(telegram):
    api, _runner = telegram
    api.push("/model")
    picker = api.wait_sent(1)[0]
    buttons = [button for row in picker["reply_markup"]["inline_keyboard"] for button in row]
    provider = next(button for button in buttons if button["text"].removeprefix("✓ ") == "demo")

    api.push_callback(provider["callback_data"], message_id=1)
    model_view = _wait_for_picker_edits(api, 1)[-1]
    buttons = [button for row in model_view["reply_markup"]["inline_keyboard"] for button in row]
    next_page = next(button for button in buttons if button["callback_data"].endswith(":page:1"))

    api.push_callback(next_page["callback_data"], message_id=1)
    paged_view = _wait_for_picker_edits(api, 2)[-1]
    assert "Choose a model (2/2)" in paged_view["text"]
    assert any(
        button["text"] == "demo-9" for row in paged_view["reply_markup"]["inline_keyboard"] for button in row
    )

    buttons = [button for row in paged_view["reply_markup"]["inline_keyboard"] for button in row]
    back = next(button for button in buttons if button["callback_data"].endswith(":back:0"))
    api.push_callback(back["callback_data"], message_id=1)
    provider_view = _wait_for_picker_edits(api, 3)[-1]
    assert "Choose a provider" in provider_view["text"]

    buttons = [button for row in provider_view["reply_markup"]["inline_keyboard"] for button in row]
    cancel = next(button for button in buttons if button["text"] == "Cancel")
    api.push_callback(cancel["callback_data"], message_id=1)
    cancelled = _wait_for_picker_edits(api, 4)[-1]
    assert cancelled["text"] == "Model selection cancelled."
    assert cancelled["reply_markup"] == {"inline_keyboard": []}


def test_telegram_model_with_an_id_keeps_the_text_command_behavior(telegram):
    api, runner = telegram
    api.push("/model demo-2")
    sent = api.wait_sent(1)

    assert runner.sessions["telegram:dm:111"].chat.agent.route.model == "demo-2"
    assert sent[-1]["text"] == "Model: demo\\-2 via demo \\(this session only\\)"
    assert sent[-1]["parse_mode"] == "MarkdownV2"
    assert sent[-1]["reply_parameters"] == {"message_id": 1}
    assert "reply_markup" not in sent[-1]


def test_telegram_model_picker_does_not_let_an_unauthorized_user_switch_the_owner_session(telegram):
    api, runner = telegram
    api.push("/model")
    picker = api.wait_sent(1)[0]
    buttons = [button for row in picker["reply_markup"]["inline_keyboard"] for button in row]
    selection = next(button for button in buttons if ":provider:" in button["callback_data"])

    api.push_callback(selection["callback_data"], user=999, message_id=1)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        answers = [body for method, body in api.calls if method == "answerCallbackQuery"]
        if answers:
            break
        time.sleep(0.02)
    else:
        raise AssertionError(f"unauthorized callback was not answered: {api.calls}")

    assert runner.sessions["telegram:dm:111"].chat.agent.route.model == "demo-1"
    assert not [body for method, body in api.calls if method == "editMessageText"]
    assert "not authorized" in answers[-1]["text"].lower()


@pytest.mark.platforms("posix")
def test_telegram_approval_buttons_resolve_only_the_owner_pending_approval(telegram, tmp_path):
    api, runner = telegram
    target = tmp_path / "build"
    target.mkdir()
    runner.client_factory = lambda: ScriptedClient(
        [tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Removed.")]
    )

    api.push("clean the build")
    prompt = api.wait_sent(1)[-1]
    session = runner.sessions["telegram:dm:111"]
    pending = session.pending
    assert pending is not None and str(target) in prompt["text"]
    buttons = [button for row in prompt["reply_markup"]["inline_keyboard"] for button in row]
    assert [button["text"] for button in buttons] == [
        "Approve once",
        "Approve for session",
        "Always approve",
        "Deny",
    ]
    callback = buttons[0]["callback_data"]
    assert len(callback.encode()) <= 64
    initial_edits = len([body for method, body in api.calls if method == "editMessageText"])

    runner.config["gateway"]["allow_all_users"] = True
    api.push_callback(callback, user=999, message_id=1)
    deadline = time.monotonic() + 5
    while (
        len([body for method, body in api.calls if method == "answerCallbackQuery"]) < 1
        and time.monotonic() < deadline
    ):
        time.sleep(0.02)
    assert not pending.answered.is_set()
    assert len([body for method, body in api.calls if method == "editMessageText"]) == initial_edits
    rejected = [body for method, body in api.calls if method == "answerCallbackQuery"]
    assert "expired" in rejected[-1]["text"].lower()

    api.push_callback(callback, message_id=1)
    edits = _wait_for_picker_edits(api, initial_edits + 1)
    api.wait_sent(2)
    assert not target.exists()
    assert session.pending is None
    assert edits[-1]["reply_markup"] == {"inline_keyboard": []}
    answers = [body for method, body in api.calls if method == "answerCallbackQuery"]
    assert len(answers) >= 2


@pytest.mark.platforms("posix")
def test_telegram_text_approval_fallback_removes_the_inline_keyboard(telegram, tmp_path):
    api, runner = telegram
    target = tmp_path / "build"
    target.mkdir()
    runner.client_factory = lambda: ScriptedClient(
        [tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Removed.")]
    )

    api.push("clean the build")
    api.wait_sent(1)
    api.push("/approve session,")
    edits = _wait_for_picker_edits(api, 1)
    api.wait_sent(2)

    assert not target.exists()
    assert edits[-1]["reply_markup"] == {"inline_keyboard": []}


def test_telegram_group_rules(telegram):
    api, runner = telegram
    adapter = runner.adapters["telegram"]

    def event(text, **extra):
        return adapter.to_event(
            {
                "update_id": 1,
                "message": {
                    "message_id": 5,
                    "text": text,
                    "chat": {"id": -100, "type": "supergroup", "title": "Team"},
                    "from": {"id": 111, "first_name": "Ada", "last_name": "L"},
                    **extra,
                },
            }
        )

    assert event("just chatting with people") is None
    mentioned = event("@clite_bot what is the status?")
    assert mentioned.text == "what is the status?" and mentioned.source.chat_type == "group"
    assert mentioned.source.user_name == "Ada L" and mentioned.source.chat_name == "Team"
    assert mentioned.reply_to == "5"
    assert event("/status@clite_bot").text == "/status"
    assert event("/status@other_bot") is None
    assert event("yes do it", reply_to_message={"from": {"username": "clite_bot"}}).text == "yes do it"
    assert event("in a topic @clite_bot", message_thread_id=77).source.thread_id == "77"
    assert (
        adapter.to_event(
            {"update_id": 2, "message": {"chat": {"id": 1, "type": "private"}, "from": {"id": 1}}}
        )
        is None
    )


def test_telegram_needs_a_valid_token(clite_home, monkeypatch):
    api = FakeTelegram()
    try:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bad-token")
        (clite_home / "config.yaml").write_text(
            f"model: {{provider: mock, default: mock-1}}\ngateway:\n  platforms:\n    telegram: {{base_url: '{api.url}'}}\n"
        )
        runner = GatewayRunner()
        assert runner.start(with_cron=False) == []
        runner.stop()
    finally:
        api.httpd.shutdown()
        api.httpd.server_close()


def test_a_network_error_never_puts_the_bot_token_in_the_log(clite_home, monkeypatch, caplog):
    token = "123456789:secret-token-that-must-stay-hidden"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    # A base URL without a scheme makes urllib quote the full request URL, token included.
    (clite_home / "config.yaml").write_text(
        "model: {provider: mock, default: mock-1}\ngateway:\n  platforms:\n"
        "    telegram: {enabled: true, base_url: 'api-telegram-without-scheme'}\n"
    )
    with caplog.at_level("WARNING", logger="clite"):
        runner = GatewayRunner()
        assert runner.start(with_cron=False) == []
        runner.stop()
    assert "failed to start" in caplog.text
    assert "secret-token" not in caplog.text


def test_cron_output_reaches_a_named_chat_through_the_gateway(gateway):
    from clite.cron.jobs import get_job_store
    from clite.cron.scheduler import tick

    runner, local, _ = gateway()
    job = get_job_store().create(
        "check the disk", "every 1h", name="disk", deliver="local:ops-room", now=1_000
    )
    outcome = tick(
        1_000 + 3600, client=ScriptedClient([text_response("Disk at 91%.")]), deliver=runner.deliver
    )
    assert outcome[0]["job_id"] == job["id"] and outcome[0]["delivered"] is True
    assert local.wait_for_messages(1) == ["[disk]\nDisk at 91%."]
    assert local.outbox[0]["chat_id"] == "ops-room"


def test_session_reset_policy_idle_and_daily(gateway):
    runner, local, _ = gateway(
        responses=[
            text_response("reply 1"),
            text_response("reply 2"),
            text_response("reply 3"),
        ]
    )
    # 1. Test IDLE reset policy: 60 minutes
    runner.config["gateway"] = {
        "session_reset": {"mode": "idle", "idle_minutes": 60},
    }
    current_time = 1_000_000.0
    runner.now_fn = lambda: current_time

    # First turn at t=0
    local.inject("msg 1", user_id="owner")
    local.wait_for_messages(1)
    sess_id_1 = runner.session_map.get("local:dm:owner")
    assert sess_id_1 is not None

    # Second turn at t=59 minutes (not reached 60m): stays in same session
    current_time += 59 * 60.0
    local.inject("msg 2", user_id="owner")
    local.wait_for_messages(2)
    sess_id_2 = runner.session_map.get("local:dm:owner")
    assert sess_id_2 == sess_id_1

    # Third turn at t=60 minutes elapsed from last msg: resets and starts new session
    current_time += 60 * 60.0
    local.inject("msg 3", user_id="owner")
    msgs = local.wait_for_messages(4)  # 1 reset notice + 1 answer
    sess_id_3 = runner.session_map.get("local:dm:owner")
    assert sess_id_3 != sess_id_1
    assert any("[Starting a new conversation" in m for m in msgs)


def test_sethome_and_cron_delivery_to_home_channel(gateway):
    from clite.cron.jobs import get_job_store

    runner, local, _ = gateway()

    # 1. When no home channel is set: delivery fails with clear message
    job = get_job_store().create("report", "every 1h", name="report", deliver="local", now=1_000)
    with pytest.raises(RuntimeError, match="no home channel configured for 'local'"):
        runner.deliver(job, "Output text")

    # 2. Set home channel via /sethome
    local.inject("/sethome", user_id="owner", chat_id="channel-main")
    msgs = local.wait_for_messages(1)
    assert any("Set this chat as the home channel for local" in m for m in msgs)
    assert runner.home_channels.get("local") == "channel-main"

    # 3. Cron delivery now succeeds and routes to the home channel
    runner.deliver(job, "Hello home channel")
    assert any("[report]\nHello home channel" in m["text"] for m in local.outbox)
    assert any(m["chat_id"] == "channel-main" for m in local.outbox)


# ── send_message tool (F4-T8) ──────────────────────────────────────────────────────────────


def _agent_with_origin(origin: dict) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(session_meta={"origin": origin})


def test_send_message_reaches_the_origin_chat_and_the_home_channel(gateway):
    from clite.runtime.home_channel import HomeChannels
    from clite.tools.builtin.send_message import send_message_tool
    from clite.tools.context import ToolContext

    runner, local, _ = gateway()
    origin = {"platform": "local", "chat_id": "origin-chat"}
    ctx = ToolContext(agent=_agent_with_origin(origin))

    # 1. The chat the conversation came from is always allowed.
    out = json.loads(send_message_tool({"target": "local:origin-chat", "text": "hi origin"}, ctx))
    assert out["delivered"] is True and out["destination"] == "local:origin-chat"
    assert local.outbox[-1]["chat_id"] == "origin-chat"
    assert local.outbox[-1]["text"] == "hi origin"

    # 2. A platform's home channel is allowed, addressed by the bare platform name.
    HomeChannels().set("local", "home-chat")
    out = json.loads(send_message_tool({"target": "local", "text": "hi home"}, ctx))
    assert out["delivered"] is True and out["destination"] == "local:home-chat"
    assert local.outbox[-1]["chat_id"] == "home-chat"


def test_send_message_refuses_a_destination_outside_the_allowlist(gateway):
    from clite.tools.builtin.send_message import send_message_tool
    from clite.tools.context import ToolContext

    runner, local, _ = gateway()
    origin = {"platform": "local", "chat_id": "origin-chat"}
    ctx = ToolContext(agent=_agent_with_origin(origin))

    out = json.loads(send_message_tool({"target": "local:some-other-chat", "text": "spam"}, ctx))
    assert "error" in out
    assert "gateway.send_targets" in out["error"]  # the message names how to allow it
    assert local.outbox == []  # nothing was sent


def test_send_message_allows_an_explicitly_configured_target(gateway):
    from clite.tools.builtin.send_message import send_message_tool
    from clite.tools.context import ToolContext

    runner, local, _ = gateway(extra="  send_targets: ['local:ops-room']\n")
    runner.config = load_config()  # pick up the freshly written config
    ctx = ToolContext(agent=_agent_with_origin({"platform": "local", "chat_id": "origin-chat"}))

    out = json.loads(send_message_tool({"target": "local:ops-room", "text": "status"}, ctx))
    assert out["delivered"] is True and out["destination"] == "local:ops-room"
    assert local.outbox[-1]["chat_id"] == "ops-room"


def test_send_message_is_not_offered_without_a_running_gateway(clite_home):
    from clite.tools.dispatch import get_tool_definitions

    (clite_home / "config.yaml").write_text("model: {provider: mock, default: mock-1}\n")
    names = [definition["function"]["name"] for definition in get_tool_definitions()]
    assert "send_message" not in names


# ── streaming answers and tool progress (F4-T5) ────────────────────────────────────────────


class _FakeChat:
    """A chat that records what was sent and remembers each message's current text."""

    def __init__(self, *, allow_edit: bool = True, max_length: int = 4000) -> None:
        self.messages: dict[str, str] = {}  # message id -> current text, in send order
        self.send_count = 0
        self.edit_count = 0
        self.allow_edit = allow_edit
        self.max_length = max_length

    def send(self, text: str) -> str | None:
        self.send_count += 1
        message_id = f"m{self.send_count}"
        self.messages[message_id] = text
        return message_id

    def edit(self, message_id: str, text: str) -> bool:
        if not self.allow_edit or len(text) > self.max_length:
            return False
        self.edit_count += 1
        self.messages[message_id] = text
        return True

    @property
    def transcript(self) -> str:
        return "".join(self.messages.values())


def test_streamed_edits_are_rate_limited_and_end_with_the_whole_answer():
    from clite.gateway.stream import StreamSender

    chat = _FakeChat()
    clock = [0.0]
    sender = StreamSender(chat.send, chat.edit, max_length=100, min_interval=1.0, now=lambda: clock[0])

    for chunk in ("Hel", "lo ", "wor", "ld"):
        sender.push(chunk)  # all inside the same second: only the first shows
    assert chat.send_count == 1 and chat.edit_count == 0

    clock[0] = 2.0
    sender.push("!")
    assert chat.edit_count == 1
    assert sender.finish() == "Hello world!"
    assert chat.transcript == "Hello world!"
    assert chat.send_count == 1  # the whole answer stayed in one message


def test_an_answer_longer_than_the_limit_is_split_across_messages():
    from clite.gateway.stream import StreamSender

    chat = _FakeChat(max_length=5)
    sender = StreamSender(chat.send, chat.edit, max_length=5, min_interval=0.0)

    whole = "abcdefghijklm"  # 13 characters, so 5 + 5 + 3
    for character in whole:
        sender.push(character)
    sender.finish()

    assert all(len(text) <= 5 for text in chat.messages.values())
    assert chat.transcript == whole
    assert chat.send_count == 3  # three messages had to exist


def test_a_refused_edit_never_loses_the_answer():
    from clite.gateway.stream import StreamSender

    chat = _FakeChat(allow_edit=False)  # the platform rate-limits every edit
    clock = [0.0]
    sender = StreamSender(chat.send, chat.edit, max_length=1000, min_interval=0.0, now=lambda: clock[0])

    sender.push("Hello ")
    clock[0] = 1.0
    sender.push("world")
    sender.push("!")
    assert sender.finish() == "Hello world!"
    assert chat.transcript == "Hello world!"  # the tail was sent as its own message
    assert chat.edit_count == 0


def test_tool_progress_is_one_message_that_is_updated():
    from clite.gateway.stream import ProgressReporter

    chat = _FakeChat()
    reporter = ProgressReporter(chat.send, chat.edit)
    reporter.note("✓ read_file (0.1s)")
    reporter.note("✓ write_file (0.2s)")

    assert chat.send_count == 1  # one status message, not one per tool
    assert chat.messages["m1"] == "✓ read_file (0.1s)\n✓ write_file (0.2s)"
    assert reporter.lines == ["✓ read_file (0.1s)", "✓ write_file (0.2s)"]


def test_tool_progress_keeps_only_the_last_lines():
    from clite.gateway.stream import ProgressReporter

    chat = _FakeChat()
    reporter = ProgressReporter(chat.send, chat.edit, max_lines=2)
    for index in range(5):
        reporter.note(f"tool {index}")
    assert chat.messages["m1"] == "tool 3\ntool 4"


def test_a_tool_message_shows_the_tool_emoji_name_and_preview():
    import clite.tools.builtin.file_tools  # registers the emoji in the registry
    import clite.tools.builtin.terminal  # noqa: F401 - importing registers the emoji
    from clite.gateway.stream import tool_message

    assert tool_message("read_file", {"path": "/tmp/report.txt"}) == "📖 read_file\n/tmp/report.txt"
    assert tool_message("terminal", {"command": "systemctl status"}) == "💻 terminal: systemctl status"


def test_terminal_progress_is_one_redacted_line_capped_at_45_characters():
    import clite.tools.builtin.terminal  # noqa: F401 - registers the emoji in the registry
    from clite.core.redact import register_credential_value
    from clite.gateway.stream import tool_line, tool_message

    secret = "private-token"
    register_credential_value(secret)
    command = f"echo {secret} && systemctl status clite-gateway"
    line = tool_line("terminal", {"command": command}, "{}", 0.1)

    assert line == tool_message("terminal", {"command": command})
    assert "\n" not in line
    assert len(line) == 45
    assert "[REDACTED]" in line
    assert secret not in line


def test_non_terminal_tool_progress_keeps_its_existing_completion_line():
    from clite.gateway.stream import tool_line

    assert tool_line("read_file", {"path": "/tmp/report.txt"}, "{}", 0.1) == "✓ read_file (0.1s)"


def test_a_tool_without_a_registry_emoji_falls_back_to_the_name_alone():
    from clite.gateway.stream import tool_message

    assert tool_message("mystery_tool", {"query": "status"}) == "mystery_tool\nstatus"


def test_a_long_terminal_preview_is_one_line_truncated_with_an_ellipsis():
    import clite.tools.builtin.terminal  # noqa: F401 - registers the emoji in the registry
    from clite.gateway.stream import TERMINAL_PROGRESS_PREVIEW_WIDTH, tool_message

    line = tool_message("terminal", {"command": "systemctl restart clite-gateway && " * 40})

    assert "\n" not in line
    assert len(line) <= TERMINAL_PROGRESS_PREVIEW_WIDTH
    assert line.endswith("…")
    assert line.startswith("💻 terminal: systemctl restart")


def test_message_progress_sends_one_chat_message_per_tool_call(gateway):
    runner, local, _ = gateway(
        [
            tool_call_response(("read_file", {"path": "/tmp/report.txt"})),
            text_response("Read it."),
        ],
        extra="display:\n  tool_progress: message\n",
    )
    local.inject("check the report", user_id="owner")
    assert local.wait_for_messages(2) == ["📖 read_file\n/tmp/report.txt", "Read it."]


def test_two_tool_calls_become_two_separate_progress_messages(gateway):
    runner, local, _ = gateway(
        [
            tool_call_response(("read_file", {"path": "a.txt"})),
            tool_call_response(("terminal", {"command": "echo progress-check"})),
            text_response("done."),
        ],
        extra="display:\n  tool_progress: message\n",
    )
    local.inject("two things", user_id="owner")
    assert local.wait_for_messages(3) == [
        "📖 read_file\na.txt",
        "💻 terminal: echo progress-check",
        "done.",
    ]


def test_default_terminal_progress_shows_a_single_command_preview(gateway):
    runner, local, _ = gateway(
        [
            tool_call_response(("terminal", {"command": "systemctl status clite-gateway"})),
            text_response("done."),
        ]
    )

    local.inject("check the gateway", user_id="owner")

    assert local.wait_for_messages(2) == ["💻 terminal: systemctl status clite-gateway", "done."]


def test_tool_progress_off_still_sends_no_progress_messages(gateway):
    # 'off' must be quoted: bare YAML off parses as a boolean and the session falls back
    # to the default level instead of the requested one.
    runner, local, _ = gateway(
        [tool_call_response(("read_file", {"path": "a.txt"})), text_response("done.")],
        extra='display:\n  tool_progress: "off"\n',
    )
    local.inject("quietly", user_id="owner")
    assert local.wait_for_messages(1) == ["done."]


def test_a_platform_that_refuses_edits_still_delivers_the_whole_answer(gateway):
    runner, local, client = gateway([text_response("the whole answer comes through")])
    local.fail_edits = True  # every edit is rejected, as a rate-limited platform would
    local.inject("question", user_id="owner")
    local.wait_for_text("the whole answer comes through")


# ── inbound and outbound attachments (F4-T4) ───────────────────────────────────────────────

_PNG = b"\x89PNG\r\n\x1a\n" + b"pretend-image-bytes"


def _image(name: str = "photo.png", data: bytes = _PNG) -> Any:
    from clite.gateway.media import IMAGE, Attachment

    return Attachment(kind=IMAGE, name=name, size=len(data), data=data)


def test_an_image_from_chat_reaches_the_model_request_as_content(gateway):
    runner, local, client = gateway([text_response("nice picture")])
    local.inject("what is this?", user_id="owner", attachments=[_image()])
    local.wait_for_messages(1)

    request = client.calls[0]["messages"][-1]
    assert request["role"] == "user"
    parts = request["content"]
    assert parts[0] == {"type": "text", "text": "what is this?"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_document_from_chat_is_announced_as_a_readable_path(gateway, tmp_path):
    from clite.gateway.media import DOCUMENT, Attachment

    runner, local, client = gateway([text_response("read it")])
    document = Attachment(kind=DOCUMENT, name="notes.txt", size=11, data=b"hello there")
    local.inject("see the notes", user_id="owner", attachments=[document])
    local.wait_for_messages(1)

    sent = client.calls[0]["messages"][-1]["content"]
    assert "see the notes" in sent
    assert "notes.txt" in sent  # the model is told what arrived...
    # Windows path separators, so compare in the path's own terms.
    assert "/gateway/media/" in sent or "gateway\\media\\" in sent  # ...and where to read it


def test_a_file_over_the_limit_is_refused_without_being_stored(gateway, clite_home):
    from clite.gateway import media

    runner, local, client = gateway([text_response("ok")], extra="attachments:\n  max_bytes: 64\n")
    local.inject("here is a big one", user_id="owner", attachments=[_image(data=_PNG * 100)])
    local.wait_for_text("I could not take that file")
    assert not media.media_dir("local:dm:owner").exists()  # nothing was written


def test_media_is_cleaned_up_when_the_session_closes(gateway):
    from clite.gateway import media

    runner, local, client = gateway([text_response("got it")])
    local.inject("look", user_id="owner", attachments=[_image()])
    local.wait_for_messages(1)
    directory = media.media_dir("local:dm:owner")
    assert directory.is_dir() and list(directory.iterdir())

    runner.stop()  # closing the session takes its files with it
    assert not directory.exists()


def test_an_attachment_is_downloaded_through_the_adapter_when_it_carries_no_bytes(gateway):
    from clite.gateway.media import IMAGE, Attachment

    runner, local, client = gateway([text_response("got the picture")])
    adapter = runner.adapters["local"]
    adapter.downloads = []

    original = adapter.send  # the adapter gains a fetch hook the way a real one has one

    def fetch(attachment: Attachment, *, max_bytes: int) -> bytes:
        adapter.downloads.append((attachment.file_id, max_bytes))
        return _PNG

    adapter.fetch_attachment = fetch  # type: ignore[attr-defined]
    assert original is not None
    local.inject(
        "here",
        user_id="owner",
        attachments=[Attachment(kind=IMAGE, name="photo.jpg", size=len(_PNG), file_id="f-1")],
    )
    local.wait_for_messages(1)
    assert adapter.downloads == [("f-1", 5_000_000)]
    request = client.calls[0]["messages"][-1]
    assert request["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_send_file_sends_a_workspace_file_and_refuses_credentials(gateway, tmp_path, clite_home):
    from types import SimpleNamespace

    from clite.tools.builtin.send_file import send_file_tool
    from clite.tools.context import ToolContext

    runner, local, client = gateway(extra="  send_targets: ['local:ops-room']\n", allowed="owner")
    runner.config = load_config()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("all good")

    origin = {"platform": "local", "chat_id": "ops-room"}
    ctx = ToolContext(
        cwd=str(workspace),
        agent=SimpleNamespace(session_meta={"origin": origin, "session_key": "local:dm:owner"}),
    )

    out = json.loads(send_file_tool({"path": str(report), "caption": "the report"}, ctx))
    assert out["delivered"] is True
    assert local.files[-1]["path"] == str(report)
    assert local.files[-1]["caption"] == "the report"

    # The agent's own .env is refused even though it is a real file.
    credentials = clite_home / ".env"
    credentials.write_text("SECRET=1")
    refused = json.loads(send_file_tool({"path": str(credentials)}, ctx))
    assert "error" in refused and "credentials" in refused["error"]

    # A file outside the working directory and the media directory is refused too.
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("nope")
    refused = json.loads(send_file_tool({"path": str(outside)}, ctx))
    assert "error" in refused and "outside the directories" in refused["error"]


# ── voice messages and spoken replies (F6-T7) ──────────────────────────────────────────────

_VOICE = b"OggS" + b"\x00" * 40


def _voice(name: str = "voice.ogg", data: bytes = _VOICE) -> Any:
    from clite.gateway.media import AUDIO, Attachment

    return Attachment(kind=AUDIO, name=name, size=len(data), data=data)


def _register_transcriber(words: str = "remind me to water the plants"):
    """A fake speech-to-text backend, so the test never reaches a vendor."""
    from clite.tools.speech import TranscriptionProvider, register_transcription_provider

    class _Fake(TranscriptionProvider):
        name = "fake-stt"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def transcribe(self, path, *, model: str = "", language: str = "") -> str:
            self.calls.append(str(path))
            return words

    provider = _Fake()
    register_transcription_provider("fake-stt", lambda: provider)
    return provider


def test_a_voice_message_becomes_a_turn_with_the_transcript(gateway):
    from clite.tools.speech import reset_speech_registries

    provider = _register_transcriber()
    try:
        runner, local, client = gateway([text_response("Watering noted.")])
        local.inject("", user_id="owner", attachments=[_voice()])
        assert local.wait_for_messages(1) == ["Watering noted."]

        sent = client.calls[0]["messages"][-1]["content"]
        assert "remind me to water the plants" in sent  # the turn sees words, not a path
        assert "/gateway/media/" not in sent  # the recording itself is not handed to the model
        assert provider.calls and provider.calls[0].endswith(".ogg")
    finally:
        reset_speech_registries()


def test_a_caption_and_a_voice_message_arrive_together(gateway):
    from clite.tools.speech import reset_speech_registries

    _register_transcriber("what does this button do")
    try:
        runner, local, client = gateway([text_response("ok")])
        local.inject("listen to this ", user_id="owner", attachments=[_voice()])
        local.wait_for_messages(1)
        sent = client.calls[0]["messages"][-1]["content"]
        assert "listen to this" in sent and "what does this button do" in sent
    finally:
        reset_speech_registries()


def test_a_voice_message_without_a_provider_still_gets_an_answer(gateway):
    from clite.tools.speech import reset_speech_registries

    reset_speech_registries()
    runner, local, client = gateway([text_response("I cannot hear that yet.")])
    local.inject("", user_id="owner", attachments=[_voice()])
    assert local.wait_for_messages(1) == ["I cannot hear that yet."]

    sent = client.calls[0]["messages"][-1]["content"]
    assert "No speech-to-text provider is configured" in sent
    assert "/gateway/media/" in sent  # the model is told where the recording is


def test_a_recording_over_the_duration_limit_is_not_sent_for_transcription(gateway, clite_home):
    import wave
    from io import BytesIO

    from clite.tools.speech import reset_speech_registries

    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000 * 3)  # three seconds
    provider = _register_transcriber()
    try:
        runner, local, client = gateway(
            [text_response("That was long.")], extra="speech:\n  max_seconds: 1\n"
        )
        local.inject("", user_id="owner", attachments=[_voice("voice.wav", buffer.getvalue())])
        local.wait_for_messages(1)

        assert provider.calls == [], "an over-long recording must not be paid for"
        sent = client.calls[0]["messages"][-1]["content"]
        assert "longer than the 1 second limit" in sent
    finally:
        reset_speech_registries()


def test_a_recording_over_the_byte_limit_is_not_sent_for_transcription(gateway, clite_home):
    from clite.tools.speech import reset_speech_registries

    provider = _register_transcriber()
    try:
        runner, local, client = gateway(
            [text_response("That was heavy.")], extra="speech:\n  max_bytes: 10\n"
        )
        local.inject("", user_id="owner", attachments=[_voice()])
        local.wait_for_messages(1)

        assert provider.calls == [], "a recording over the ceiling must not be paid for"
        sent = client.calls[0]["messages"][-1]["content"]
        assert "larger than the 10 byte limit" in sent
        assert "/gateway/media/" in sent  # the model is still told where it is
    finally:
        reset_speech_registries()


def test_a_transcriber_that_answers_nothing_usable_is_reported(gateway):
    """A provider that returns ``None`` rather than raising is as broken, and as survivable."""
    from clite.tools.speech import TranscriptionProvider, register_transcription_provider

    class _Silent(TranscriptionProvider):
        name = "silent-stt"

        def transcribe(self, path, *, model: str = "", language: str = ""):
            return None

    register_transcription_provider("silent-stt", _Silent)
    try:
        runner, local, client = gateway([text_response("I noticed.")])
        local.inject("", user_id="owner", attachments=[_voice()])
        assert local.wait_for_messages(1) == ["I noticed."]
        sent = client.calls[0]["messages"][-1]["content"]
        assert "could not be transcribed" in sent and "AttributeError" in sent
    finally:
        from clite.tools.speech import reset_speech_registries

        reset_speech_registries()


def test_a_failing_transcriber_is_reported_and_the_turn_still_runs(gateway):
    from clite.tools.speech import TranscriptionProvider, register_transcription_provider

    class _Broken(TranscriptionProvider):
        name = "broken-stt"

        def transcribe(self, path, *, model: str = "", language: str = "") -> str:
            raise RuntimeError("the vendor is down")

    register_transcription_provider("broken-stt", _Broken)
    try:
        runner, local, client = gateway([text_response("I still answered.")])
        local.inject("", user_id="owner", attachments=[_voice()])
        assert local.wait_for_messages(1) == ["I still answered."]
        sent = client.calls[0]["messages"][-1]["content"]
        assert "could not be transcribed" in sent and "the vendor is down" in sent
    finally:
        from clite.tools.speech import reset_speech_registries

        reset_speech_registries()


def test_the_answer_to_a_voice_message_is_spoken_where_the_platform_asks_for_it(gateway):
    from clite.tools.speech import (
        SpeechProvider,
        register_speech_provider,
        reset_speech_registries,
    )

    class _FakeSpeech(SpeechProvider):
        name = "fake-tts"
        output_format = "mp3"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def synthesize(self, text, path, *, voice="", model="", speed=0.0):
            self.calls.append(text)
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 16)
            return Path(path)

    speech = _FakeSpeech()
    register_speech_provider("fake-tts", lambda: speech)
    _register_transcriber()
    try:
        runner, local, client = gateway(
            [text_response("Watering noted.")], extra="speech:\n  reply_with_voice: [local]\n"
        )
        local.inject("", user_id="owner", attachments=[_voice()])
        local.wait_for_messages(1)

        (sent,) = local.wait_for_files(1)
        assert sent["chat_id"] == "owner"
        assert sent["path"].endswith(".mp3")
        assert Path(sent["path"]).read_bytes().startswith(b"\xff\xfb")
        assert speech.calls == ["Watering noted."]  # the same words the chat shows
    finally:
        reset_speech_registries()


def test_a_speech_provider_that_fails_leaves_no_file_and_the_turn_intact(gateway, clite_home):
    from clite.tools.speech import (
        SpeechProvider,
        register_speech_provider,
        reset_speech_registries,
    )

    class _Broken(SpeechProvider):
        name = "broken-tts"
        output_format = "mp3"

        def synthesize(self, text, path, *, voice="", model="", speed=0.0):
            Path(path).write_bytes(b"\xff\xfb half an answer")  # then the vendor gives up
            raise RuntimeError("the vendor is down")

    register_speech_provider("broken-tts", _Broken)
    _register_transcriber()
    try:
        runner, local, client = gateway(
            [text_response("Watering noted.")], extra="speech:\n  reply_with_voice: [local]\n"
        )
        local.inject("", user_id="owner", attachments=[_voice()])
        assert local.wait_for_messages(1) == ["Watering noted."]  # the text answer still landed
        assert local.files == []
        assert list((clite_home / "gateway" / "media").rglob("reply-*")) == []
    finally:
        reset_speech_registries()


def test_a_reply_too_long_to_speak_is_left_as_text(gateway, clite_home):
    from clite.tools.speech import (
        SpeechProvider,
        register_speech_provider,
        reset_speech_registries,
    )

    calls: list[str] = []

    class _FakeSpeech(SpeechProvider):
        name = "fake-tts"

        def synthesize(self, text, path, *, voice="", model="", speed=0.0):
            # Recorded, not raised: speak_reply swallows exceptions on purpose, so a raised
            # canary would prove nothing about whether this provider was reached.
            calls.append(text)
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 16)
            return Path(path)

    register_speech_provider("fake-tts", _FakeSpeech)
    _register_transcriber()
    try:
        runner, local, client = gateway(
            [text_response("A much longer answer than that.")],
            extra="speech:\n  reply_with_voice: [local]\n  max_chars: 5\n",
        )
        local.inject("", user_id="owner", attachments=[_voice()])
        local.wait_for_messages(1)

        assert calls == [], "half an answer read aloud is worse than one read"
        assert local.files == []
        assert list((clite_home / "gateway" / "media").rglob("reply-*")) == []
    finally:
        reset_speech_registries()


def test_a_refused_upload_is_logged_and_the_spoken_file_dropped(gateway, clite_home, caplog):
    """``send_file`` reports a refusal instead of raising, so the new caller has to look."""
    from clite.gateway.event import SendResult
    from clite.tools.speech import (
        SpeechProvider,
        register_speech_provider,
        reset_speech_registries,
    )

    class _FakeSpeech(SpeechProvider):
        name = "fake-tts"
        output_format = "mp3"

        def synthesize(self, text, path, *, voice="", model="", speed=0.0):
            Path(path).write_bytes(b"\xff\xfb" + b"\x00" * 16)
            return Path(path)

    register_speech_provider("fake-tts", _FakeSpeech)
    _register_transcriber()
    refused: list[str] = []

    def refuse(chat_id: str, path: str, **kwargs: Any) -> SendResult:
        refused.append(path)
        return SendResult(False, error="this platform has no upload path")

    try:
        runner, local, client = gateway(
            [text_response("Watering noted.")], extra="speech:\n  reply_with_voice: [local]\n"
        )
        local.send_file = refuse  # type: ignore[method-assign]
        with caplog.at_level("WARNING", logger="clite.gateway"):
            local.inject("", user_id="owner", attachments=[_voice()])
            assert local.wait_for_messages(1) == ["Watering noted."]
            # The refusal arrives after the words do, and the file is dropped right after it.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (not refused or Path(refused[0]).exists()):
                time.sleep(0.01)

        assert refused and refused[0].endswith(".mp3")
        assert not Path(refused[0]).exists(), "a file nobody can play is not left behind"
        assert "no upload path" in caplog.text
    finally:
        reset_speech_registries()


def test_a_text_message_is_never_answered_with_audio(gateway):
    from clite.tools.speech import (
        SpeechProvider,
        register_speech_provider,
        reset_speech_registries,
    )

    calls: list[str] = []

    class _FakeSpeech(SpeechProvider):
        name = "fake-tts"

        def synthesize(self, text, path, *, voice="", model="", speed=0.0):
            calls.append(text)
            raise AssertionError("unreachable: a text message must not be spoken back")

    register_speech_provider("fake-tts", _FakeSpeech)
    try:
        runner, local, client = gateway(
            [text_response("As you like.")], extra="speech:\n  reply_with_voice: [local]\n"
        )
        local.inject("just type it", user_id="owner")
        local.wait_for_messages(1)
        assert calls == []  # the provider was never reached, so nothing was spoken
        assert local.files == []
    finally:
        reset_speech_registries()


def test_text_to_speech_is_offered_to_a_chat_agent_only_when_it_can_speak(gateway):
    from clite.tools.dispatch import get_tool_definitions
    from clite.tools.registry import registry
    from clite.tools.speech import (
        SpeechProvider,
        register_speech_provider,
        reset_speech_registries,
    )

    class _FakeSpeech(SpeechProvider):
        name = "fake-tts"

        def synthesize(self, text, path, *, voice="", model="", speed=0.0):
            raise AssertionError("not called here")

    reset_speech_registries()
    runner, local, client = gateway()
    names = [definition["function"]["name"] for definition in get_tool_definitions(["clite-gateway"])]
    assert "send_file" in names  # the rest of the messaging toolset is offered
    assert "text_to_speech" not in names

    register_speech_provider("fake-tts", _FakeSpeech)
    try:
        registry.reset_check_cache()  # the availability answer is cached for 30 seconds
        names = [definition["function"]["name"] for definition in get_tool_definitions(["clite-gateway"])]
        assert "text_to_speech" in names
    finally:
        reset_speech_registries()
