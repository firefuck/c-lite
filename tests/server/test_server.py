"""The headless backend: readiness contract, token auth, REST routes, JSON-RPC over WebSocket."""

from __future__ import annotations

import contextlib
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request

import pytest

websockets_client = pytest.importorskip("websockets.sync.client")

from clite import __version__  # noqa: E402
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
        return websockets_client.connect(
            f"ws://127.0.0.1:{self.port}/api/ws?token={token or self.token}", **kwargs
        )


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
        self.socket.send(
            json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        )
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
    assert backend.get("/api/health") == (200, {"ok": True, "version": __version__})
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
    assert "<title>C-lite</title>" in html and "/assets/app.js" in html
    with urllib.request.urlopen(backend.base + "/assets/app.js", timeout=5) as response:
        assert "approval.request" in response.read().decode()


def test_websocket_rejects_a_bad_token_and_a_foreign_origin(backend):
    from websockets.exceptions import ConnectionClosed, InvalidStatus

    refused = (
        {"token": "wrong"},
        {"origin": "https://evil.example"},
        {"origin": "null"},  # a sandboxed frame or a file:// page
        {"origin": f"http://127.0.0.1:{backend.port + 1}"},  # another local web app
        {"origin": "file://"},
    )
    for kwargs in refused:
        with pytest.raises((ConnectionClosed, InvalidStatus)), backend.connect(**kwargs) as socket:
            socket.recv(timeout=5)
    # The dashboard's own origin is fine, under either name for this machine.
    for origin in (backend.base, f"http://localhost:{backend.port}"):
        with backend.connect(origin=origin) as socket:
            assert json.loads(socket.recv(timeout=5))["params"]["type"] == "gateway.ready"


def test_a_loopback_server_ignores_requests_addressed_to_another_name(backend):
    """DNS rebinding: a site re-pointed at 127.0.0.1 reaches the port, but its requests still
    carry the site's own name. Even with the right token they get nothing."""
    from websockets.exceptions import ConnectionClosed, InvalidStatus

    rebound = {"Host": f"evil.example:{backend.port}"}
    assert backend.get("/api/status", token=backend.token, headers=rebound)[0] == 401
    assert backend.get("/api/status", token=backend.token)[0] == 200
    with (
        pytest.raises((ConnectionClosed, InvalidStatus)),
        backend.connect(additional_headers=rebound) as socket,
    ):
        socket.recv(timeout=5)


def test_origin_and_host_rules():
    from types import SimpleNamespace

    from clite.server.app import host_allowed, origin_allowed

    def connection(**headers):
        return SimpleNamespace(headers=headers)

    assert origin_allowed(connection(host="127.0.0.1:8000"))  # not a browser
    assert origin_allowed(connection(host="[::1]:8000", origin="http://[::1]:8000"))
    assert origin_allowed(connection(host="agent.lan:8000", origin="https://agent.lan:8000"))
    assert not origin_allowed(connection(host="agent.lan:8000", origin="https://other.lan:8000"))
    assert not origin_allowed(connection(host="127.0.0.1:8000", origin="http://127.0.0.1:9000"))
    assert not origin_allowed(connection(host="127.0.0.1:8000", origin="http://127.0.0.1:8000:garbage"))

    assert host_allowed(connection(host="localhost:8000"), "127.0.0.1")
    assert not host_allowed(connection(host="evil.example:8000"), "127.0.0.1")
    assert not host_allowed(connection(), "127.0.0.1")
    # Beyond loopback, the name must be one the user listed: "any name accepted" is gone.
    assert not host_allowed(connection(host="agent.lan:8000"), "0.0.0.0")
    assert host_allowed(connection(host="agent.lan:8000"), "0.0.0.0", ["agent.lan"])
    assert host_allowed(connection(host="0.0.0.0:8000"), "0.0.0.0", ["agent.lan"])  # the bind address
    assert host_allowed(connection(host="127.0.0.1:8000"), "0.0.0.0", ["agent.lan"])  # health checks
    assert not host_allowed(connection(host="other.lan:8000"), "0.0.0.0", ["agent.lan"])


def test_binding_beyond_loopback_needs_tls_or_a_clear_yes():
    from clite.server.run import bind_refusal

    assert bind_refusal("127.0.0.1") is None
    assert bind_refusal("localhost") is None
    refusal = bind_refusal("0.0.0.0")
    assert refusal is not None and "without TLS" in refusal and "--insecure" in refusal
    assert bind_refusal("0.0.0.0", tls_certfile="c.pem", tls_keyfile="k.pem") is None
    assert bind_refusal("0.0.0.0", allow_insecure=True) is None
    assert bind_refusal("0.0.0.0", tls_certfile="c.pem") is not None  # a cert without its key


def test_an_exposed_bind_refuses_to_start_without_tls(clite_home, capsys):
    from clite.server.run import serve

    assert serve("0.0.0.0", 0, token="t", out=io.StringIO()) == 2
    assert "without TLS" in capsys.readouterr().err


def test_the_asgi_server_is_told_the_message_limit(clite_home, monkeypatch):
    """The frame limit lives in the ASGI server, so an oversized message is refused before the
    app ever holds it as a string."""
    import uvicorn

    from clite.server import run as run_module

    captured: dict[str, object] = {}
    real_config = uvicorn.Config

    class Capture(real_config):  # type: ignore[misc, valid-type]
        def __init__(self, app, **kwargs):
            captured.update(kwargs)
            super().__init__(app, **kwargs)

    monkeypatch.setattr(uvicorn, "Config", Capture)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: None)
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\nserver:\n  max_message_bytes: 4096\n"
    )
    assert run_module.serve("127.0.0.1", 0, token="t", out=io.StringIO()) == 0
    assert captured["ws_max_size"] == 4096


def test_a_message_over_the_limit_is_refused(clite_home):
    from websockets.exceptions import ConnectionClosed

    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\nserver:\n  max_message_bytes: 4096\n"
    )
    instance, server, thread = start_backend(token="limit-token")
    try:
        with instance.connect(token="limit-token") as socket:
            assert json.loads(socket.recv(timeout=5))["params"]["type"] == "gateway.ready"
            # A normal message still works.
            socket.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}))
            assert json.loads(socket.recv(timeout=5))["result"]["pong"] is True
            # One over the cap closes the connection instead of being parsed.
            with pytest.raises(ConnectionClosed):
                socket.send(
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {"x": "y" * 8000}})
                )
                socket.recv(timeout=5)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_wrong_tokens_slow_that_address_down_only():
    from clite.server.limits import TokenThrottle, too_large

    throttle = TokenThrottle(max_failures=10, window_seconds=60, delay_seconds=0.5)
    # The tenth wrong token is the one that starts the wait; the nine before it are answered.
    assert [throttle.record_failure("10.0.0.1", now=0.0) for _ in range(9)][-1] == 0.0
    assert throttle.blocked_for("10.0.0.1", now=0.0) == 0.0
    assert throttle.record_failure("10.0.0.1", now=0.0) == 0.5
    assert throttle.blocked_for("10.0.0.1", now=0.2) == pytest.approx(0.3)
    # Another address is untouched by it.
    assert throttle.blocked_for("10.0.0.2", now=0.0) == 0.0
    assert throttle.record_failure("10.0.0.2", now=0.0) == 0.0
    # A success clears the count for that address.
    throttle.record_success("10.0.0.1")
    assert throttle.blocked_for("10.0.0.1", now=0.2) == 0.0
    # The wait grows while the guessing continues, and is capped.
    for _ in range(20):
        last = throttle.record_failure("10.0.0.3", now=0.0)
    assert last == 60.0

    assert too_large("x" * 10, 10) is False
    assert too_large("x" * 11, 10) is True
    assert too_large("x" * 11, 0) is False  # no cap configured


def test_wrong_tokens_from_one_address_are_delayed(clite_home):
    from clite.server.limits import TokenThrottle

    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    throttle = TokenThrottle(max_failures=3, window_seconds=60, delay_seconds=0.4)
    instance, server, thread = start_backend(token="throttle-token", throttle=throttle)
    try:
        started = time.monotonic()
        for _ in range(2):  # the first two are answered at once
            assert instance.get("/api/status", token="wrong")[0] == 401
        assert time.monotonic() - started < 0.4
        started = time.monotonic()
        assert instance.get("/api/status", token="wrong")[0] == 401  # the third waits
        assert time.monotonic() - started >= 0.4
        # The right token is never delayed.
        started = time.monotonic()
        assert instance.get("/api/status", token="throttle-token")[0] == 200
        assert time.monotonic() - started < 0.4
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_named_tokens_open_a_connection_and_revoking_cuts_it_off(clite_home):
    from websockets.exceptions import ConnectionClosed, InvalidStatus

    from clite.server.tokens import TokenError, get_token_store

    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    store = get_token_store()
    _record, secret = store.create("laptop", ttl_days=1)

    instance, server, thread = start_backend(token="session-token")
    try:
        # A named token works on both surfaces, and the file never holds the value.
        assert instance.get("/api/status", token=secret)[0] == 200
        assert secret not in (clite_home / "tokens.json").read_text()

        with instance.connect(token=secret) as socket:
            assert json.loads(socket.recv(timeout=5))["params"]["type"] == "gateway.ready"
            socket.send(json.dumps({"jsonrpc": "2.0", "id": 8, "method": "ping", "params": {}}))
            assert json.loads(socket.recv(timeout=5))["result"]["pong"] is True

            # Revoke it: the next request is refused, and the open socket is cut off.
            assert store.revoke("laptop") is True
            assert instance.get("/api/status", token=secret)[0] == 401
            with pytest.raises(ConnectionClosed):
                socket.send(json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}}))
                socket.recv(timeout=5)

        with pytest.raises((ConnectionClosed, InvalidStatus)), instance.connect(token=secret):
            pass

        # The one-off session token is unaffected by all of this.
        assert instance.get("/api/status", token="session-token")[0] == 200
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    # Creating the same name twice is refused; after a revoke the name is free again.
    _again, second = store.create("desk")
    with pytest.raises(TokenError):
        store.create("desk")
    assert store.verify(second) is not None
    assert store.verify(secret) is None  # the revoked one stays dead
    assert [entry.name for entry in store.list()] == ["desk"]


def test_an_expired_token_is_refused(clite_home):
    from clite.server.tokens import get_token_store

    store = get_token_store()
    record, secret = store.create("old", ttl_days=1, now=time.time() - 3 * 86_400)
    assert record.expired() is True
    assert store.verify(secret) is None
    assert [entry.name for entry in store.list()] == ["old"]


def test_connections_and_approvals_are_audited(clite_home):
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    instance, server, thread = start_backend(token="audit-token")
    try:
        assert instance.get("/api/status", token="wrong")[0] == 401
        with instance.connect(token="audit-token") as socket:
            assert json.loads(socket.recv(timeout=5))["params"]["type"] == "gateway.ready"
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    from clite.core.constants import get_logs_dir

    log = (get_logs_dir() / "audit.log").read_text()
    assert "token_rejected" in log
    assert "connected" in log and "token=session" in log
    assert "disconnected" in log
    assert "audit-token" not in log  # the value is never written, only the name


def test_the_audit_log_can_be_turned_off(clite_home):
    from clite.core.constants import get_logs_dir

    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\nserver:\n  audit_log: false\n"
    )
    instance, server, thread = start_backend(token="quiet-token")
    try:
        assert instance.get("/api/status", token="wrong")[0] == 401
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not (get_logs_dir() / "audit.log").exists()


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


def test_openai_routes_return_openai_objects_and_sse_when_enabled(clite_home):
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\nserver:\n  openai_api_enabled: true\n"
    )
    instance, server, thread = start_backend(token="test-token-123")
    try:

        def post(path, body, headers=None):
            request = urllib.request.Request(
                instance.base + path, data=json.dumps(body).encode(), method="POST"
            )
            request.add_header("Authorization", f"Bearer {instance.token}")
            request.add_header("Content-Type", "application/json")
            for key, value in (headers or {}).items():
                request.add_header(key, value)
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.read().decode()

        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(instance.base + "/v1/models", timeout=5)
        assert missing.value.code == 401
        models = instance.get("/v1/models", token=instance.token)
        assert models == (
            200,
            {"object": "list", "data": [{"id": "mock-1", "object": "model", "owned_by": "clite"}]},
        )
        normal = json.loads(
            post("/v1/chat/completions", {"model": "mock-1", "messages": [{"role": "user", "content": "hi"}]})
        )
        assert (
            normal["object"] == "chat.completion"
            and normal["choices"][0]["message"]["content"] == "You said: hi"
        )
        sse = post(
            "/v1/chat/completions",
            {"model": "mock-1", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert "data: [DONE]" in sse and '"object": "chat.completion.chunk"' in sse
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_disconnecting_keeps_the_session_for_a_while(clite_home):
    """A dropped socket no longer ends the conversation: the session is held for the grace
    period so a client that comes back can pick it up, and closed once that runs out."""
    from clite.rpc.replay import get_detached_sessions
    from clite.state import get_session_db

    with backend_connection(clite_home) as (instance, server, thread):
        with instance.connect() as socket:
            rpc = Rpc(socket)
            session = rpc.call("session.create")
            rpc.call("prompt.submit", {"session_id": session["session_id"], "text": "hi"})
            rpc.wait_event("turn.complete")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and get_detached_sessions().count() == 0:
            time.sleep(0.05)
        assert get_detached_sessions().count() == 1
        assert get_session_db().get_session(session["stored_session_id"])["end_reason"] is None
        # Past the grace, it ends like any other closed session.
        get_detached_sessions().reap(now=time.monotonic() + 10_000)
        assert get_session_db().get_session(session["stored_session_id"])["end_reason"] == "rpc_closed"


def test_a_socket_that_comes_back_gets_what_it_missed(clite_home):
    """The whole path over real sockets: a client drops mid-turn, reconnects, and is handed the
    events it missed — the turn was never interrupted."""
    from clite.providers.testing import ScriptedClient, text_response
    from clite.rpc.replay import get_event_log

    release = threading.Event()

    def slow(cancel, **kwargs):
        while not release.is_set():
            if cancel.wait(0.01):
                raise InterruptedError
        return text_response("done while you were away")

    with backend_connection(
        clite_home, client_factory=lambda: ScriptedClient([slow], default=text_response("ok"))
    ) as (instance, server, thread):
        with instance.connect() as socket:
            rpc = Rpc(socket)
            session = rpc.call("session.create")
            rpc.call("prompt.submit", {"session_id": session["session_id"], "text": "long job"})
            rpc.wait_event("turn.step")
            last_seq = max(event["seq"] for event in rpc.events)

        # The socket is gone; the turn is not.
        release.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            events, _complete = get_event_log().missed(session["session_id"], last_seq)
            if any(event["type"] == "turn.complete" for event in events):
                break
            time.sleep(0.02)
        else:
            pytest.fail("the turn did not finish after the socket closed")

        with instance.connect() as socket:
            rpc = Rpc(socket)
            attached = rpc.call("session.attach", {"session_id": session["session_id"], "last_seq": last_seq})
            assert attached["complete"] is True
            finished = next(e for e in attached["events"] if e["type"] == "turn.complete")
            assert finished["payload"]["final_response"] == "done while you were away"
            # The session answers on the new socket.
            assert (
                rpc.call("session.info", {"session_id": session["session_id"]})["stored_session_id"]
                == session["stored_session_id"]
            )


@contextlib.contextmanager
def backend_connection(clite_home, **kwargs):
    """A backend for one test, shut down even when the test fails."""
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n")
    instance, server, thread = start_backend(token="replay-token", **kwargs)
    try:
        yield instance, server, thread
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# ── plugin dashboard pages, on an origin of their own ────────────────────────────────────

PAGE_PLUGIN = """name: board
description: a plugin with a dashboard page
dashboard:
  title: Deploy board
  page: dashboard/index.html
"""


def write_page_plugin(clite_home, *, enabled=True, name="board"):
    from clite.plugins.manifest import parse_manifest  # noqa: F401  (keeps the shape obvious)

    directory = clite_home / "plugins" / name
    (directory / "dashboard").mkdir(parents=True)
    (directory / "plugin.yaml").write_text(PAGE_PLUGIN.replace("board", name))
    (directory / "__init__.py").write_text("def register(ctx):\n    pass\n")
    (directory / "dashboard" / "index.html").write_text("<!doctype html><h1>deploy board</h1>")
    (directory / "dashboard" / "app.js").write_text("console.log('board');")
    (directory / "notes.env").write_text("SOMETHING=private")
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\n"
        + (f"plugins:\n  enabled: [{name}]\n" if enabled else "")
    )
    return directory


def fetch(url, *, token=None):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.headers.get("content-type", ""), response.read().decode()


def fetch_status(url):
    try:
        return fetch(url)[0]
    except urllib.error.HTTPError as error:
        return error.code


def test_a_plugin_page_is_listed_and_served_from_its_own_origin(clite_home):
    write_page_plugin(clite_home)
    backend, server, thread = start_backend(token="test-token-123")
    try:
        assert backend.get("/api/plugin-pages")[0] == 401  # a list of what is installed needs the token
        status, body = backend.get("/api/plugin-pages", token=backend.token)
        assert status == 200
        (page,) = body["plugins"]
        assert (page["name"], page["title"]) == ("board", "Deploy board")
        url = page["url"]
        origin = url.split("/board/")[0]
        assert origin.startswith("http://127.0.0.1:")
        assert int(origin.rsplit(":", 1)[1]) != backend.port  # its own port, hence its own origin

        # Served there, without a token: it is the plugin's own file, not the backend's data.
        status, content_type, html = fetch(url)
        assert status == 200 and content_type.startswith("text/html") and "deploy board" in html
        assert fetch(f"{origin}/board/dashboard/app.js")[1].startswith("text/javascript")
        # The dashboard's own origin has no such route.
        assert fetch_status(f"{backend.base}/board/dashboard/index.html") == 404
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_a_plugin_without_a_load_has_no_page(clite_home):
    write_page_plugin(clite_home, enabled=False)
    backend, server, thread = start_backend(token="test-token-123")
    try:
        assert backend.get("/api/plugin-pages", token=backend.token) == (200, {"plugins": []})
        # No page, no listener: nothing of the plugin is reachable at all.
        assert fetch_status(f"{backend.base}/board/dashboard/index.html") == 404
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_the_page_listener_serves_web_assets_only(clite_home):
    write_page_plugin(clite_home)
    backend, server, thread = start_backend(token="test-token-123")
    try:
        url = backend.get("/api/plugin-pages", token=backend.token)[1]["plugins"][0]["url"]
        origin = url.split("/board/")[0]
        assert "deploy board" in fetch(f"{origin}/board/")[2]  # a bare /<plugin>/ is the entry page
        for path in (
            "/board/notes.env",  # a file in the plugin, but not a web asset
            "/board/plugin.yaml",
            "/board/dashboard/%2e%2e/%2e%2e/notes.env",  # tries to climb out
            "/somewhere-else/index.html",  # no such plugin
            "/assets/app.css",  # the dashboard's own files are not here
        ):
            assert fetch_status(origin + path) == 404, path
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_a_page_cannot_open_the_dashboard_socket(clite_home):
    write_page_plugin(clite_home)
    backend, server, thread = start_backend(token="test-token-123")
    try:
        url = backend.get("/api/plugin-pages", token=backend.token)[1]["plugins"][0]["url"]
        page_origin = url.split("/board/")[0]
        with pytest.raises(Exception) as refused:
            # The token is not enough: a page from another origin is not the dashboard.
            backend.connect(token=backend.token, origin=page_origin).__enter__()
        assert "4401" in str(refused.value) or "rejected" in str(refused.value).lower()
        # The dashboard's own origin still connects.
        backend.connect(token=backend.token, origin=backend.base).__enter__().close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert page_origin != backend.base


def test_the_dashboard_embeds_plugin_pages_without_same_origin():
    """The behavioural version of this needs a browser (see test_dashboard_browser.py); what can
    be checked here is the frame the dashboard builds, and it must not carry allow-same-origin."""
    from clite.server.app import STATIC_DIR

    script = (STATIC_DIR / "assets" / "app.js").read_text(encoding="utf-8")
    match = re.search(r'sandbox:\s*"([^"]+)"', script)
    assert match, "the dashboard does not set a sandbox on plugin pages"
    assert "allow-scripts" in match.group(1) and "allow-same-origin" not in match.group(1)
    assert re.search(r'referrerPolicy:\s*"no-referrer"', script)
