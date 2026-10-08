"""The MCP stdio client, against a scripted server and (when installed) the real SDK."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.tools.dispatch import handle_function_call, resolve_enabled_tools
from clite.tools.mcp import McpError, McpServer, connect_mcp_servers, shutdown_mcp_servers
from clite.tools.registry import registry


def _free_port() -> int:
    """An ephemeral port the OS just handed out (close, then let the server bind it)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


FAKE_SERVER = textwrap.dedent("""
    import json, os, sys

    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n")
        sys.stdout.flush()

    TOOLS = [
        {"name": "add", "description": "Add two numbers", "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
        {"name": "fail", "description": "Always fails", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "env", "description": "Read an environment variable", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}}},
        {"name": "picture", "description": "Returns an image", "inputSchema": {"type": "object", "properties": {}}},
    ]
    print("server starting", file=sys.stderr, flush=True)
    for line in sys.stdin:
        message = json.loads(line)
        method, request_id = message.get("method"), message.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": message["params"]["protocolVersion"],
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1.0"}}})
        elif method == "notifications/initialized":
            send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": "ready"}})
            send({"jsonrpc": "2.0", "id": "server-ping-1", "method": "ping"})
        elif method == "tools/list":
            if not message["params"].get("cursor"):
                send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS[:2], "nextCursor": "page2"}})
            else:
                send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS[2:]}})
        elif method == "tools/call":
            name, args = message["params"]["name"], message["params"].get("arguments") or {}
            if name == "add":
                total = args["a"] + args["b"]
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": str(total)}],
                      "structuredContent": {"sum": total}}})
            elif name == "fail":
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": "disk is full"}], "isError": True}})
            elif name == "env":
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": os.environ.get(args["name"], "(unset)")}]}})
            elif name == "picture":
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "image", "data": "AAAA", "mimeType": "image/png"}]}})
            else:
                send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown tool"}})
        elif request_id is not None and method:
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}})
""")


@pytest.fixture
def fake_server(tmp_path):
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(FAKE_SERVER)
    return {"command": sys.executable, "args": [str(script)]}


def test_handshake_pagination_and_tool_calls(fake_server):
    server = McpServer("calc", fake_server)
    try:
        server.start()
        assert server.server_info == {"name": "fake", "version": "1.0"}
        assert [tool["name"] for tool in server.tools] == ["add", "fail", "env", "picture"]  # both pages
        assert json.loads(server.call_tool("add", {"a": 2, "b": 40})) == {
            "result": "42",
            "structured": {"sum": 42},
        }
        assert json.loads(server.call_tool("fail", {})) == {"error": "disk is full"}
        assert json.loads(server.call_tool("picture", {})) == {"result": "[image content omitted]"}
        assert "unknown tool" in json.loads(server.call_tool("nope", {}))["error"]
    finally:
        server.stop()
    assert not server.is_alive()


def test_servers_become_namespaced_tools_in_platform_toolsets(fake_server, clite_home):
    config = {
        "mcp_servers": {
            "calc": {**fake_server, "tools": {"exclude": ["picture"]}},
            "off": {**fake_server, "enabled": False},
        }
    }
    connected = connect_mcp_servers(config)
    assert connected == {"calc": ["mcp_calc_add", "mcp_calc_fail", "mcp_calc_env"]}
    entry = registry.get("mcp_calc_add")
    assert (entry.toolset, entry.origin) == ("mcp-calc", "mcp:calc") and entry.description.startswith(
        "[calc] Add two numbers"
    )
    assert (
        json.loads(handle_function_call("mcp_calc_add", {"a": "1", "b": 2}))["result"] == "3.0"
    )  # "1" coerced by the schema

    assert "mcp_calc_add" in resolve_enabled_tools(["clite-cli"], [])
    assert "mcp_calc_add" not in resolve_enabled_tools(
        ["clite-cli"], ["mcp-calc"]
    )  # one server can be switched off
    assert "mcp_calc_add" not in resolve_enabled_tools(["file"], [])  # only platform toolsets carry MCP

    assert connect_mcp_servers(config) == connected  # idempotent: the running server is reused
    shutdown_mcp_servers()
    assert registry.get("mcp_calc_add") is None


def test_server_environment_excludes_secrets_unless_listed(fake_server, clite_home):
    from clite.core.env import load_env

    (clite_home / ".env").write_text("OPENROUTER_API_KEY=sk-or-should-not-leak-1234\n")
    load_env()
    connect_mcp_servers({"mcp_servers": {"envy": {**fake_server, "env": {"SERVER_SETTING": "explicit"}}}})
    assert (
        json.loads(handle_function_call("mcp_envy_env", {"name": "OPENROUTER_API_KEY"}))["result"]
        == "(unset)"
    )
    assert (
        json.loads(handle_function_call("mcp_envy_env", {"name": "SERVER_SETTING"}))["result"] == "explicit"
    )


def test_startup_failure_waits_for_stderr_before_reporting(tmp_path, monkeypatch):
    import threading

    script = tmp_path / "crash.py"
    script.write_text("import sys; print('startup diagnostic', file=sys.stderr); sys.exit(3)")
    server = McpServer("crash", {"command": sys.executable, "args": [str(script)]})
    release = threading.Event()
    read_stderr, send, hint = server._read_stderr, server._send, server._stderr_hint

    def delayed_stderr():
        assert release.wait(10)
        read_stderr()

    def after_exit(message):
        server.process.wait(timeout=10)
        send(message)

    def release_diagnostic():
        release.set()
        return hint()

    monkeypatch.setattr(server, "_read_stderr", delayed_stderr)
    monkeypatch.setattr(server, "_send", after_exit)
    monkeypatch.setattr(server, "_stderr_hint", release_diagnostic)
    try:
        with pytest.raises(McpError, match="startup diagnostic"):
            server.start()
    finally:
        release.set()
        server.stop()


def test_broken_servers_are_skipped_not_fatal(tmp_path, fake_server, clite_home):
    crash = tmp_path / "crash.py"
    crash.write_text("import sys; print('boom: missing dependency', file=sys.stderr); sys.exit(3)\n")
    silent = tmp_path / "silent.py"
    silent.write_text("import time; time.sleep(60)\n")
    connected = connect_mcp_servers(
        {
            "mcp_servers": {
                "missing": {"command": "/no/such/binary"},
                "crash": {"command": sys.executable, "args": [str(crash)]},
                "http-only": {"url": "https://example.test/mcp"},
                "good": fake_server,
            }
        }
    )
    assert list(connected) == ["good"]

    server = McpServer("crash", {"command": sys.executable, "args": [str(crash)]})
    with pytest.raises(McpError, match="boom: missing dependency"):
        server.start()  # the server's stderr is in the error, which is what the user needs to see
    server.stop()

    slow = McpServer("silent", {"command": sys.executable, "args": [str(silent)], "timeout": 0.2})
    slow.process = None
    with pytest.raises(McpError):
        slow.request("tools/list")  # not running at all


def test_a_dead_server_reports_instead_of_hanging(fake_server):
    server = McpServer("calc", fake_server)
    server.start()
    server.process.kill()
    server.process.wait()
    assert "error" in json.loads(server.call_tool("add", {"a": 1, "b": 1}))
    server.stop()


def test_agent_uses_mcp_tools_end_to_end(fake_server, clite_home):
    from clite.runtime import build_agent

    (clite_home / "config.yaml").write_text(
        "model: {provider: mock, default: mock-1}\nmcp_servers:\n  calc:\n"
        f"    command: {sys.executable}\n    args: ['{fake_server['args'][0]}']\n"
    )
    client = ScriptedClient(
        [tool_call_response(("mcp_calc_add", {"a": 20, "b": 22})), text_response("It is 42.")]
    )
    agent = build_agent(client=client, auto_title=False)
    try:
        assert "mcp_calc_add" in agent.tool_names
        assert agent.run_conversation("what is 20 + 22?").final_response == "It is 42."
        assert json.loads(agent.messages[2]["content"])["result"] == "42"
    finally:
        agent.close()


def test_compatible_with_the_official_sdk_server(tmp_path):
    """The same client against a server built with the MCP SDK, when it is installed."""
    pytest.importorskip("mcp.server.mcpserver")
    script = tmp_path / "sdk_server.py"
    script.write_text(
        textwrap.dedent('''
        from mcp.server.mcpserver import MCPServer

        server = MCPServer("sdk-demo")

        @server.tool()
        def shout(text: str) -> str:
            """Return the text in upper case."""
            return text.upper()

        server.run()
    ''')
    )
    client = McpServer("sdk", {"command": sys.executable, "args": [str(script)]})
    try:
        client.start()
        assert client.server_info["name"] == "sdk-demo"
        tool = next(tool for tool in client.tools if tool["name"] == "shout")
        assert (
            tool["description"] == "Return the text in upper case."
            and "text" in tool["inputSchema"]["properties"]
        )
        assert json.loads(client.call_tool("shout", {"text": "hello"}))["result"] == "HELLO"
    finally:
        client.stop()


# ── Streamable HTTP, against the real SDK server ─────────────────────────────────────────


HTTP_SDK_SERVER = textwrap.dedent('''
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("http-demo", version="1.0")

    @server.tool()
    def shout(text: str) -> str:
        """Return the text in upper case."""
        return text.upper()

    @server.resource("note://greeting")
    def greeting() -> str:
        """A greeting resource."""
        return "hello from resource"

    @server.prompt()
    def summarize(text: str) -> str:
        """Summarize the given text."""
        return f"Please summarize: {text}"

    server.run(transport="streamable-http", host="127.0.0.1", port=PORT)
''')


def _spawn_http_sdk_server(tmp_path, port, *, token=None):
    """Start the SDK's Streamable HTTP server in a subprocess; return its URL.

    A tiny Starlette app wraps the MCP app when ``token`` is set so the auth-header path can be
    exercised against a server that really checks the header.
    """
    pytest.importorskip("mcp.server.mcpserver")
    pytest.importorskip("uvicorn")
    if token:
        script = tmp_path / "http_auth_server.py"
        script.write_text(
            textwrap.dedent(f'''
            from mcp.server.mcpserver import MCPServer
            import uvicorn
            from starlette.middleware.base import BaseHTTPMiddleware
            from starlette.responses import PlainTextResponse

            server = MCPServer("http-auth", version="1.0")

            @server.tool()
            def shout(text: str) -> str:
                """Return the text in upper case."""
                return text.upper()

            app = server.streamable_http_app()

            class Auth(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    if request.headers.get("authorization", "") != "Bearer {token}":
                        return PlainTextResponse("unauthorized", status_code=401)
                    return await call_next(request)

            app.add_middleware(Auth)
            uvicorn.run(app, host="127.0.0.1", port={port}, log_level="error")
        ''')
        )
    else:
        script = tmp_path / "http_server.py"
        script.write_text(HTTP_SDK_SERVER.replace("PORT", str(port)))

    process = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"the HTTP server exited early:\n{process.stdout.read() if process.stdout else ''}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        raise AssertionError("the HTTP server never started listening")
    return process, url


@pytest.fixture
def http_sdk_server(tmp_path):
    """A real SDK Streamable HTTP server, skipped when the SDK is not installed."""
    port = _free_port()
    process, url = _spawn_http_sdk_server(tmp_path, port)
    try:
        yield url
    finally:
        process.kill()
        process.wait(timeout=10)


def test_http_transport_speaks_to_a_real_sdk_server(http_sdk_server):
    client = McpServer("http", {"url": http_sdk_server})
    try:
        client.start()
        assert client.is_http and client.server_info["name"] == "http-demo"
        assert [tool["name"] for tool in client.tools] == ["shout"]
        assert json.loads(client.call_tool("shout", {"text": "hi"}))["result"] == "HI"
        # Resources and prompts arrive as tools and slash commands.
        assert client.resources and client.resources[0]["uri"] == "note://greeting"
        assert [prompt.command for prompt in client.prompts] == ["mcp-http-summarize"]
        assert (
            json.loads(client.read_resource("note://greeting"))["contents"][0]["text"]
            == "hello from resource"
        )
        assert "Please summarize: deep" in client.read_prompt("summarize", {"text": "deep"})
        assert client.is_alive()
    finally:
        client.stop()


def test_a_resource_server_gets_list_and_read_tools(http_sdk_server, clite_home):
    connected = connect_mcp_servers({"mcp_servers": {"notes": {"url": http_sdk_server}}})
    assert "mcp_notes_read_resource" in connected["notes"]
    assert "mcp_notes_list_resources" in connected["notes"]
    listing = json.loads(handle_function_call("mcp_notes_list_resources", {}))
    assert listing["resources"][0]["uri"] == "note://greeting"
    read = json.loads(handle_function_call("mcp_notes_read_resource", {"uri": "note://greeting"}))
    assert read["contents"][0]["text"] == "hello from resource"
    shutdown_mcp_servers()


def test_auth_headers_come_from_dotenv(tmp_path, clite_home):
    from clite.core.env import load_env

    (clite_home / ".env").write_text("REMOTE_MCP_TOKEN=secret-token\n")
    load_env()
    port = _free_port()
    process, url = _spawn_http_sdk_server(tmp_path, port, token="secret-token")
    try:
        client = McpServer("auth", {"url": url, "headers": {"Authorization": "Bearer ${REMOTE_MCP_TOKEN}"}})
        try:
            client.start()
            assert json.loads(client.call_tool("shout", {"text": "ok"}))["result"] == "OK"
        finally:
            client.stop()
    finally:
        process.kill()
        process.wait(timeout=10)


def test_a_missing_dotenv_header_variable_is_a_clear_error(clite_home):
    from clite.tools.mcp.http import build_headers

    with pytest.raises(McpError, match="REMOTE_MCP_TOKEN"):
        build_headers({"headers": {"Authorization": "Bearer ${REMOTE_MCP_TOKEN}"}}, "auth")


# ── tool list changes do not touch the running session (A1) ───────────────────────────────


MUTABLE_SERVER = textwrap.dedent("""
    import json, os, sys

    CONTROL = sys.argv[1]

    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n")
        sys.stdout.flush()

    def tool_names():
        names = ["add"]
        if os.path.exists(CONTROL):
            names.append("extra")
        return names

    def schema(name):
        return {"name": name, "description": f"{name} tool", "inputSchema": {"type": "object", "properties": {}}}

    for line in sys.stdin:
        message = json.loads(line)
        method, request_id = message.get("method"), message.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": message["params"]["protocolVersion"],
                  "capabilities": {"tools": {"listChanged": True}}, "serverInfo": {"name": "mutable", "version": "1.0"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": [schema(name) for name in tool_names()]}})
        elif method == "tools/call":
            name = message["params"]["name"]
            if name == "add":
                if message["params"].get("arguments", {}).get("grow"):
                    open(CONTROL, "w").close()
                    # Announce the new tool list mid-session.
                    send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": "grown"}]}})
            else:
                send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": name}]}})
        elif request_id is not None and method:
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}})
""")


def test_a_tool_list_change_does_not_alter_the_running_session(tmp_path, clite_home):
    """A1: the tools a session was built with stay fixed; the change waits for the next session."""
    control = tmp_path / "grow.flag"
    spec = {"command": sys.executable, "args": [str(tmp_path / "mutable.py"), str(control)]}
    (tmp_path / "mutable.py").write_text(MUTABLE_SERVER)
    config = {"model": {"provider": "mock", "default": "mock-1"}, "mcp_servers": {"grow": spec}}
    connected = connect_mcp_servers(config)
    assert connected["grow"] == ["mcp_grow_add"]

    client = ScriptedClient([tool_call_response(("mcp_grow_add", {"grow": True})), text_response("ok")])
    from clite.runtime import build_agent

    agent = build_agent(client=client, config=config, toolsets=["mcp-grow"])
    try:
        assert agent.tool_names == frozenset({"mcp_grow_add"})
        agent.run_conversation("grow")
        # The server announced a new tool while this session ran: the session's tools are unchanged.
        assert agent.tool_names == frozenset({"mcp_grow_add"})
        assert "mcp_grow_extra" not in agent.tool_names
    finally:
        agent.close()

    # The very same connected server now offers the extra tool: the next session picks it up.
    refreshed = connect_mcp_servers(config)
    assert refreshed["grow"] == ["mcp_grow_add", "mcp_grow_extra"]
    shutdown_mcp_servers()


def test_a_dead_server_is_retried_with_a_growing_delay(clite_home):
    """A server that fails to start is not dialed again immediately; the delay grows."""
    config = {"mcp_servers": {"broken": {"command": "/no/such/binary"}}}
    assert connect_mcp_servers(config) == {}
    from clite.tools.mcp.client import _SERVERS

    server = next(iter(_SERVERS.values()))
    assert server.retry_seconds_left() > 0 and not server.ready_for_retry()
    assert connect_mcp_servers(config) == {}  # inside the backoff window: not retried
    # Each further failure waits longer, until it hits the cap.
    delays = [server.mark_failure() for _ in range(5)]
    assert delays == sorted(delays) and delays[1] > delays[0]
    assert min(max(delays), 600) == delays[-1]  # bounded, not unbounded growth
    shutdown_mcp_servers()


# ── clite mcp add | list | remove | test ──────────────────────────────────────────────────


def _run_cli(capsys, *argv):
    from clite.cli.main import main

    code = main([str(arg) for arg in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_add_writes_the_config_through_the_atomic_writer(clite_home, capsys, monkeypatch):
    (clite_home / "config.yaml").write_text("# keep me\nmodel:\n  provider: mock\n  default: mock-1\n")
    import clite.cli.subcommands.mcp as mcp_module
    from clite.core.config import atomic_config_update as real

    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(mcp_module, "atomic_config_update", counting)
    code, out, _ = _run_cli(capsys, "mcp", "add", "files", "--command", "npx", "--args", "-y /notes")
    assert code == 0 and "Added MCP server 'files'" in out
    assert calls["n"] == 1
    text = (clite_home / "config.yaml").read_text()
    assert text.startswith("# keep me")  # the comment survives the write
    from clite.core.config import load_config

    assert load_config()["mcp_servers"]["files"]["args"] == ["-y", "/notes"]


def test_cli_test_reports_the_tools_it_found(tmp_path, clite_home, capsys):
    script = tmp_path / "srv.py"
    script.write_text(
        textwrap.dedent("""
        import json, sys
        for line in sys.stdin:
            m = json.loads(line)
            if m.get("method") == "initialize":
                print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": m["params"]["protocolVersion"],
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "tiny", "version": "1"}}}), flush=True)
            elif m.get("method") == "tools/list":
                print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"tools": [
                    {"name": "ping", "description": "ping", "inputSchema": {"type": "object", "properties": {}}}]}}), flush=True)
    """)
    )
    (clite_home / "config.yaml").write_text(
        "model: {provider: mock, default: mock-1}\n"
        f"mcp_servers:\n  tiny:\n    command: {sys.executable}\n    args: ['{script}']\n"
    )
    code, out, _ = _run_cli(capsys, "mcp", "test", "tiny")
    assert code == 0
    assert "connected (stdio)" in out and "tools (1): ping" in out
    shutdown_mcp_servers()


def test_cli_remove_deletes_only_the_named_server(clite_home, capsys):
    (clite_home / "config.yaml").write_text(
        "model: {provider: mock, default: mock-1}\nmcp_servers:\n  a: {command: x}\n  b: {command: y}\n"
    )
    code, out, _ = _run_cli(capsys, "mcp", "remove", "a")
    assert code == 0 and "Removed MCP server 'a'" in out
    from clite.core.config import load_config

    assert list(load_config()["mcp_servers"]) == ["b"]


def test_cli_add_rejects_a_spec_with_both_command_and_url(clite_home, capsys):
    (clite_home / "config.yaml").write_text("model: {provider: mock, default: mock-1}\n")
    code, _, err = _run_cli(capsys, "mcp", "add", "x", "--command", "npx", "--url", "http://x/mcp")
    assert code == 1 and "exactly one of --command" in err


def test_mcp_prompts_appear_as_slash_commands(http_sdk_server, clite_home):
    from clite.runtime.commands import command_catalog

    connect_mcp_servers({"mcp_servers": {"notes": {"url": http_sdk_server}}})
    entries = {entry["name"]: entry for entry in command_catalog("cli")}
    assert entries["mcp-notes-summarize"]["category"] == "MCP"
    assert entries["mcp-notes-summarize"]["args_hint"] == "text"
    shutdown_mcp_servers()


def test_an_mcp_prompt_runs_as_a_slash_command(http_sdk_server, clite_home):
    """A server prompt becomes a slash command that submits its messages as a user turn."""
    from clite.runtime.session import ACTION_SUBMIT, ChatSession

    connect_mcp_servers({"mcp_servers": {"notes": {"url": http_sdk_server}}})
    session = ChatSession.__new__(ChatSession)  # only the prompt dispatch is under test here
    from clite.runtime.slash import run_mcp_prompt

    result = run_mcp_prompt(session, "mcp-notes-summarize", "the quarterly report")
    assert result.action == ACTION_SUBMIT and result.data == {"mcp_prompt": "mcp-notes-summarize"}
    assert "Please summarize: the quarterly report" in result.text
    # An unknown prompt name is reported, not submitted as a turn.
    unknown = run_mcp_prompt(session, "mcp-notes-nope", "")
    assert unknown.action is None and "Unknown MCP prompt" in unknown.text
    shutdown_mcp_servers()


def test_slash_mcp_reports_no_servers_when_none_are_connected(clite_home):
    from clite.runtime.slash import SLASH_HANDLERS

    class _Session:
        pass

    assert "No MCP servers are connected" in SLASH_HANDLERS["mcp"](_Session(), "").text
