"""The gateway: authorization, session routing, commands, busy handling, approvals over chat."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clite.gateway.event import CHAT_GROUP, SessionSource
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

    assert runner.pairing.approve("local", code.lower())["user_id"] == "stranger"  # codes are case-insensitive
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
        assert store.approve("telegram", "WRONGCODE", now=now + 5001) is None  # (one failure was counted above)
    with pytest.raises(PermissionError):
        store.approve("telegram", fresh, now=now + 5002)  # locked after five wrong codes
    later = now + 5002 + 3600 + 1  # the lock has expired (and so has that code)
    newest = store.request_code("telegram", "u1", now=later)
    assert store.approve("telegram", newest, now=later + 1) == {"user_id": "u1", "user_name": ""}
    assert store.is_approved("telegram", "u1") and store.revoke("telegram", "u1") and not store.is_approved("telegram", "u1")


# ── commands and busy handling ───────────────────────────────────────────────────────────


def test_slash_commands_work_in_chat(gateway):
    runner, local, client = gateway()
    local.inject("/status", user_id="owner")
    assert "mock-1 via mock" in local.wait_for_messages(1)[0]
    local.inject("first message", user_id="owner")
    local.wait_for_messages(2)
    old = runner.sessions["local:dm:owner"].chat.session_id

    local.inject("/new", user_id="owner")
    assert local.wait_for_messages(3)[2] == "Started a new session."
    assert runner.session_map.get("local:dm:owner") != old  # a restart resumes the new session, not the old one
    local.inject("/quit", user_id="owner")
    assert "only available in the terminal" in local.wait_for_messages(4)[3]
    local.inject("/approve", user_id="owner")
    assert local.wait_for_messages(5)[4] == "Nothing is waiting for approval."


def test_a_message_during_a_turn_interrupts_it_by_default(gateway):
    def blocked(cancel, **kwargs):
        cancel.wait(5)
        raise InterruptedError

    runner, local, client = gateway([blocked, text_response("answer to the second message")])
    local.inject("long task", user_id="owner")
    while not client.calls:  # wait until the model call of the first turn is under way
        time.sleep(0.01)
    local.inject("/new", user_id="owner")  # a session command has to wait
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

    runner, local, _ = gateway([slow, text_response("second answer")], extra="display:\n  busy_input_mode: queue")
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
    runner, local, _ = gateway([tool_call_response(("terminal", {"command": f"rm -rf {target}"})), text_response("Removed.")])
    local.inject("clean the build dir", user_id="owner")
    prompt = local.wait_for_messages(1)[0]
    assert f"rm -rf {target}" in prompt and "/approve" in prompt and target.exists()
    local.inject("maybe?", user_id="owner")
    assert "Please answer" in local.wait_for_messages(2)[1]
    local.inject("/approve", user_id="owner")
    assert local.wait_for_messages(3)[2] == "Removed."
    assert not target.exists()


@pytest.mark.platforms("posix")
def test_deny_and_silence_both_refuse(gateway, tmp_path):
    target = tmp_path / "keep"
    target.mkdir()
    call = tool_call_response(("terminal", {"command": f"rm -rf {target}"}))
    runner, local, _ = gateway([call, text_response("Left it alone."), call, text_response("No answer, so I did not.")],
                               extra="approvals:\n  timeout: 0.3")
    local.inject("clean up", user_id="owner")
    local.wait_for_messages(1)
    local.inject("/deny", user_id="owner")
    assert local.wait_for_messages(2)[1] == "Left it alone."
    local.inject("clean up again", user_id="owner")
    assert local.wait_for_messages(4)[3] == "No answer, so I did not."  # nobody replied within the timeout
    assert target.exists()


def test_clarifying_question_is_answered_by_number_or_text(gateway):
    ask = tool_call_response(("clarify", {"question": "Which environment?", "choices": ["staging", "production"]}))
    runner, local, _ = gateway([ask, text_response("Deploying to production.")])
    local.inject("deploy", user_id="owner")
    assert local.wait_for_messages(1)[0] == "Which environment?\n1. staging\n2. production"
    local.inject("2", user_id="owner")
    assert local.wait_for_messages(2)[1] == "Deploying to production."
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
    runner.deliver({"id": "j1", "name": "morning digest", "deliver": "origin",
                    "origin": {"platform": "local", "chat_id": "owner"}}, "3 PRs need review.")
    runner.deliver({"id": "j2", "name": "", "deliver": "local:ops-room"}, "Disk at 91%.")
    assert local.wait_for_messages(2) == ["[morning digest]\n3 PRs need review.", "[job j2]\nDisk at 91%."]
    assert local.outbox[1]["chat_id"] == "ops-room"
    with pytest.raises(RuntimeError):
        runner.deliver({"id": "j3", "deliver": "slack:general"}, "nobody home")


def test_a_platform_that_fails_to_start_does_not_stop_the_gateway(clite_home):
    (clite_home / "config.yaml").write_text(
        "model: {provider: mock, default: mock-1}\ngateway:\n  platforms:\n"
        "    telegram: {enabled: true}\n    local: {enabled: true}\n    imaginary: {enabled: true}\n    off: {enabled: false}\n")
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
    assert [m["content"] for m in client.calls[-1]["messages"][1:]] == ["remember me", "ok", "am I remembered?"]


# ── telegram, against a fake Bot API ─────────────────────────────────────────────────────


class FakeTelegram:
    def __init__(self):
        self.updates, self.sent, self.calls = [], [], []
        self.lock = threading.Lock()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                method = self.path.rsplit("/", 1)[-1]
                api.calls.append((method, body))
                if "/botgood-token/" not in self.path:
                    return self._reply({"ok": False, "description": "Unauthorized"}, 401)
                if method == "getMe":
                    return self._reply({"ok": True, "result": {"username": "clite_bot"}})
                if method == "getUpdates":
                    with api.lock:
                        pending = [u for u in api.updates if u["update_id"] >= body["offset"]]
                    if not pending:
                        time.sleep(0.05)
                    return self._reply({"ok": True, "result": pending})
                if method == "sendMessage":
                    api.sent.append(body)
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
            self.updates.append({"update_id": len(self.updates) + 1, "message": {
                "message_id": len(self.updates) + 1, "text": text, "chat": {"id": chat, "type": chat_type},
                "from": {"id": user, "first_name": "Ada", "is_bot": False}, **extra}})

    def wait_sent(self, count, timeout=5.0):
        deadline = time.monotonic() + timeout
        while len(self.sent) < count and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.sent


@pytest.fixture
def telegram(clite_home, monkeypatch):
    api = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "good-token")
    (clite_home / "config.yaml").write_text(
        "model: {provider: mock, default: mock-1}\ngateway:\n  platforms:\n"
        f"    telegram: {{enabled: true, allowed_users: [111], base_url: '{api.url}', poll_timeout: 1}}\n")
    runner = GatewayRunner()
    assert runner.start(with_cron=False) == ["telegram"]
    yield api, runner
    runner.stop()
    api.httpd.shutdown()
    api.httpd.server_close()


def test_telegram_round_trip(telegram):
    api, runner = telegram
    api.push("hello from telegram")
    sent = api.wait_sent(1)
    assert sent[0] == {"chat_id": "111", "text": "You said: hello from telegram"}
    assert ("sendChatAction", {"chat_id": "111", "action": "typing"}) in api.calls
    offsets = [body["offset"] for method, body in api.calls if method == "getUpdates"]
    assert offsets[0] == 0 and offsets[-1] == 2  # the update was acknowledged and is not fetched again


def test_telegram_group_rules(telegram):
    api, runner = telegram
    adapter = runner.adapters["telegram"]

    def event(text, **extra):
        return adapter.to_event({"update_id": 1, "message": {
            "message_id": 5, "text": text, "chat": {"id": -100, "type": "supergroup", "title": "Team"},
            "from": {"id": 111, "first_name": "Ada", "last_name": "L"}, **extra}})

    assert event("just chatting with people") is None
    mentioned = event("@clite_bot what is the status?")
    assert mentioned.text == "what is the status?" and mentioned.source.chat_type == "group"
    assert mentioned.source.user_name == "Ada L" and mentioned.source.chat_name == "Team"
    assert event("/status@clite_bot").text == "/status"
    assert event("/status@other_bot") is None
    assert event("yes do it", reply_to_message={"from": {"username": "clite_bot"}}).text == "yes do it"
    assert event("in a topic @clite_bot", message_thread_id=77).source.thread_id == "77"
    assert adapter.to_event({"update_id": 2, "message": {"chat": {"id": 1, "type": "private"}, "from": {"id": 1}}}) is None


def test_telegram_needs_a_valid_token(clite_home, monkeypatch):
    api = FakeTelegram()
    try:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bad-token")
        (clite_home / "config.yaml").write_text(
            f"model: {{provider: mock, default: mock-1}}\ngateway:\n  platforms:\n    telegram: {{base_url: '{api.url}'}}\n")
        runner = GatewayRunner()
        assert runner.start(with_cron=False) == []
        runner.stop()
    finally:
        api.httpd.shutdown()
        api.httpd.server_close()
