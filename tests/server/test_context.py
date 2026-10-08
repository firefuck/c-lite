"""HTTP workers retain each request's profile and credential context."""

import asyncio
import json
import threading

from clite.core.constants import display_home, home_scope
from clite.core.env import get_secret, secret_scope
from clite.rpc import methods
from clite.rpc.server import RpcServer
from clite.server.app import create_app
from clite.state.db import get_session_db


async def http_get(app, path):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 1),
            "headers": [(b"host", b"localhost"), (b"authorization", b"Bearer context-test-token")],
        },
        receive,
        send,
    )
    return messages[0]["status"], json.loads(b"".join(m.get("body", b"") for m in messages[1:]))


def test_http_workers_keep_two_concurrent_profile_scopes(tmp_path, monkeypatch):
    original = methods.system_info
    observed = {}
    barrier = threading.Barrier(2)

    def observe(server, params):
        barrier.wait(timeout=5)
        result = original(server, params)
        observed[result.home] = get_secret("SCOPE_TEST_KEY")
        return result

    monkeypatch.setattr(methods, "system_info", observe)
    app = create_app("context-test-token")

    async def request(index):
        home = tmp_path / f"profile-{index}"
        home.mkdir()
        (home / "config.yaml").write_text(f"model:\n  provider: mock\n  default: profile-model-{index}\n")
        secret = f"synthetic-profile-{index}"
        with home_scope(home), secret_scope({"SCOPE_TEST_KEY": secret}):
            expected_home = display_home()
            status, body = await http_get(app, "/api/status")
            assert status == 200
            assert body["home"] == expected_home
            assert body["model"] == f"profile-model-{index}"
            assert observed[expected_home] == secret

    async def run():
        await asyncio.wait_for(asyncio.gather(request(1), request(2)), timeout=5)

    asyncio.run(run())


def test_http_session_routes_read_only_the_requests_profile_database(tmp_path):
    app = create_app("context-test-token")

    async def request(index):
        with home_scope(tmp_path / f"profile-{index}"):
            db = get_session_db()
            db.create_session(f"stored-{index}", source="tui")
            db.append_message(f"stored-{index}", {"role": "user", "content": f"private message {index}"})
            status, body = await http_get(app, "/api/sessions")
            assert status == 200
            assert [row["id"] for row in body["sessions"]] == [f"stored-{index}"]
            status, body = await http_get(app, f"/api/sessions/stored-{index}/messages")
            assert status == 200
            assert [row["text"] for row in body["messages"]] == [f"private message {index}"]
            status, _ = await http_get(app, f"/api/sessions/stored-{3 - index}/messages")
            assert status == 404

    async def run():
        await asyncio.wait_for(asyncio.gather(request(1), request(2)), timeout=5)

    asyncio.run(run())


def test_websocket_cleanup_keeps_the_connections_scope_off_the_event_loop(tmp_path, monkeypatch):
    original = RpcServer.close
    observed = {}
    barrier = threading.Barrier(2)

    def close(server):
        try:
            barrier.wait(timeout=5)
            observed[display_home()] = (get_secret("SCOPE_TEST_KEY"), threading.get_ident())
        finally:
            original(server)

    monkeypatch.setattr(RpcServer, "close", close)
    app = create_app("context-test-token")

    async def connection(index):
        with home_scope(tmp_path / f"profile-{index}"), secret_scope({"SCOPE_TEST_KEY": f"secret-{index}"}):
            expected_home = display_home()
            incoming = iter([{"type": "websocket.connect"}, {"type": "websocket.disconnect", "code": 1000}])
            outgoing = []

            async def receive():
                return next(incoming)

            async def send(message):
                outgoing.append(message)

            await app(
                {
                    "type": "websocket",
                    "asgi": {"version": "3.0"},
                    "scheme": "ws",
                    "path": "/api/ws",
                    "query_string": b"",
                    "subprotocols": [],
                    "headers": [(b"host", b"localhost"), (b"authorization", b"Bearer context-test-token")],
                },
                receive,
                send,
            )
            assert outgoing[0]["type"] == "websocket.accept"
            secret, thread_id = observed[expected_home]
            assert secret == f"secret-{index}"
            assert thread_id != threading.get_ident()

    async def run():
        await asyncio.wait_for(asyncio.gather(connection(1), connection(2)), timeout=5)

    asyncio.run(run())
