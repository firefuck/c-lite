"""The headless backend: readiness contract, token auth, REST routes, JSON-RPC over WebSocket."""

from __future__ import annotations

import io
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

websockets_client = pytest.importorskip("websockets.sync.client")

from clite.core.brand import BACKEND_READY_SENTINEL  # noqa: E402
from clite.server.run import dashboard_url, serve  # noqa: E402


class Backend:
    def __init__(self, port, token, out):
        self.port, self.token, self.out = port, token, out
        self.base = f"http://127.0.0.1:{port}"

    def get(self, path, *, token=None, headers=None):
        request = urllib.request.Request(self.base + path, headers=headers or {})
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def connect(self, token=None, **kwargs):
        return websockets_client.connect(f"ws://127.0.0.1:{self.port}/api/ws?token={token or self.token}", **kwargs)


def start_backend(**kwargs):
    ready = threading.Event()
    box = {}
    out = io.StringIO()

    def on_ready(port, token, server):
        box.update(port=port, token=token, server=server)
        ready.set()

    thread = threading.Thread(target=serve, kwargs={"out": out, "on_ready": on_ready, **kwargs}, daemon=True)
    thread.start()
    assert ready.wait(10), "the backend did not start"
    backend = Backend(box["port"], box["token"], out)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:  # the socket is bound; wait until the app answers
        try:
            if backend.get("/api/health")[0] == 200:
                break
        except OSError:
            time.sleep(0.05)
    return backend, box["server"], thread


@pytest.fixture
def backend(clite_home):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    instance, server, thread = start_backend(token="test-token-123")
    yield instance
    server.should_exit = True
    thread.join(timeout=10)


class Rpc:
    def __init__(self, socket):
        self.socket, self.next_id, self.events = socket, 0, []

    def call(self, method, params=None):
        self.next_id += 1
        self.socket.send(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv(timeout=10))
            if message.get("method") == "event":
                self.events.append(message["params"])
            elif message.get("id") == self.next_id:
                assert "error" not in message, message
                return message["result"]

    def wait_event(self, event_type):
        while True:
            for event in self.events:
                if event["type"] == event_type:
                    return event
            message = json.loads(self.socket.recv(timeout=10))
            if message.get("method") == "event":
                self.events.append(message["params"])


def test_ready_line_reports_the_bound_port(backend):
    lines = backend.out.getvalue().splitlines()
    assert lines == [f"{BACKEND_READY_SENTINEL} port={backend.port}"]
    assert backend.port > 0


def test_token_is_taken_from_the_environment(clite_home, monkeypatch, capsys):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    monkeypatch.setenv("CLITE_SESSION_TOKEN", "token-from-parent")
    instance, server, thread = start_backend()
    try:
        assert instance.token == "token-from-parent"
        assert instance.get("/api/status", token="token-from-parent")[0] == 200
        assert "token-from-parent" not in capsys.readouterr().err  # the parent knows it; never print it
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_dashboard_url_keeps_the_token_in_the_fragment():
    assert dashboard_url("0.0.0.0", 8123, "abc") == "http://127.0.0.1:8123/#token=abc"


def test_health_is_public_and_everything_else_needs_the_token(backend):
    assert backend.get("/api/health") == (200, {"ok": True, "version": "0.1.0"})
    assert backend.get("/api/status")[0] == 401
    assert backend.get("/api/status", token="wrong")[0] == 401
    status, body = backend.get("/api/status", token=backend.token)
    assert status == 200 and body["configured"] is True and body["model"] == "mock-1"
    assert backend.get("/api/status", headers={"X-Clite-Token": backend.token})[0] == 200
    assert backend.get(f"/api/status?token={backend.token}")[0] == 200
    assert backend.get("/api/sessions")[0] == 401


def test_static_dashboard_is_served_without_the_token(backend):
    with urllib.request.urlopen(backend.base + "/", timeout=5) as response:
        html = response.read().decode()
    assert "<title>C-lite</title>" in html and "/static/app.js" in html
    with urllib.request.urlopen(backend.base + "/static/rpc.js", timeout=5) as response:
        assert "class RpcClient" in response.read().decode()


def test_websocket_rejects_a_bad_token_and_a_foreign_origin(backend):
    from websockets.exceptions import ConnectionClosed, InvalidStatus

    for kwargs in ({"token": "wrong"}, {"origin": "https://evil.example"}):
        with pytest.raises((ConnectionClosed, InvalidStatus)), backend.connect(**kwargs) as socket:
            socket.recv(timeout=5)
    with backend.connect(origin=backend.base) as socket:  # the dashboard's own origin is fine
        assert json.loads(socket.recv(timeout=5))["params"]["type"] == "gateway.ready"


def test_a_full_turn_over_websocket_then_rest(backend):
    with backend.connect() as socket:
        rpc = Rpc(socket)
        assert rpc.wait_event("gateway.ready")["payload"]["protocol_version"] == 1
        session = rpc.call("session.create")
        assert session["platform"] == "desktop"
        rpc.call("prompt.submit", {"session_id": session["session_id"], "text": "hello over the socket"})
        done = rpc.wait_event("turn.complete")
        assert done["payload"]["final_response"] == "You said: hello over the socket"
        deltas = "".join(e["payload"]["text"] for e in rpc.events if e["type"] == "message.delta")
        assert deltas == "You said: hello over the socket"
        stored = session["stored_session_id"]

    status, body = backend.get("/api/sessions", token=backend.token)
    assert status == 200 and [s["id"] for s in body["sessions"]] == [stored]
    status, body = backend.get(f"/api/sessions/{stored}/messages", token=backend.token)
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert backend.get("/api/sessions/nope/messages", token=backend.token)[0] == 404
    assert backend.get("/api/sessions?limit=abc", token=backend.token)[0] == 400


def test_disconnecting_ends_the_connections_sessions(backend):
    from clite.state import get_session_db

    with backend.connect() as socket:
        rpc = Rpc(socket)
        session = rpc.call("session.create")
        rpc.call("prompt.submit", {"session_id": session["session_id"], "text": "hi"})
        rpc.wait_event("turn.complete")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if get_session_db().get_session(session["stored_session_id"])["end_reason"] == "rpc_closed":
            break
        time.sleep(0.05)
    assert get_session_db().get_session(session["stored_session_id"])["end_reason"] == "rpc_closed"
