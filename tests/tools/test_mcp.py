"""The MCP stdio client, against a scripted server and (when installed) the real SDK."""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from clite.providers.testing import ScriptedClient, text_response, tool_call_response
from clite.tools.dispatch import handle_function_call, resolve_enabled_tools
from clite.tools.mcp import McpError, McpServer, connect_mcp_servers, shutdown_mcp_servers
from clite.tools.registry import registry

FAKE_SERVER = textwrap.dedent('''
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
''')


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
        assert json.loads(server.call_tool("add", {"a": 2, "b": 40})) == {"result": "42", "structured": {"sum": 42}}
        assert json.loads(server.call_tool("fail", {})) == {"error": "disk is full"}
        assert json.loads(server.call_tool("picture", {})) == {"result": "[image content omitted]"}
        assert "unknown tool" in json.loads(server.call_tool("nope", {}))["error"]
    finally:
        server.stop()
    assert not server.is_alive()


def test_servers_become_namespaced_tools_in_platform_toolsets(fake_server, clite_home):
    config = {"mcp_servers": {"calc": {**fake_server, "tools": {"exclude": ["picture"]}}, "off": {**fake_server, "enabled": False}}}
    connected = connect_mcp_servers(config)
    assert connected == {"calc": ["mcp_calc_add", "mcp_calc_fail", "mcp_calc_env"]}
    entry = registry.get("mcp_calc_add")
    assert (entry.toolset, entry.origin) == ("mcp-calc", "mcp:calc") and entry.description.startswith("[calc] Add two numbers")
    assert json.loads(handle_function_call("mcp_calc_add", {"a": "1", "b": 2}))["result"] == "3.0"  # "1" coerced by the schema

    assert "mcp_calc_add" in resolve_enabled_tools(["clite-cli"], [])
    assert "mcp_calc_add" not in resolve_enabled_tools(["clite-cli"], ["mcp-calc"])  # one server can be switched off
    assert "mcp_calc_add" not in resolve_enabled_tools(["file"], [])  # only platform toolsets carry MCP

    assert connect_mcp_servers(config) == connected  # idempotent: the running server is reused
    shutdown_mcp_servers()
    assert registry.get("mcp_calc_add") is None


def test_server_environment_excludes_secrets_unless_listed(fake_server, clite_home):
    from clite.core.env import load_env

    (clite_home / ".env").write_text("OPENROUTER_API_KEY=sk-or-should-not-leak-1234\n")
    load_env()
    connect_mcp_servers({"mcp_servers": {"envy": {**fake_server, "env": {"SERVER_SETTING": "explicit"}}}})
    assert json.loads(handle_function_call("mcp_envy_env", {"name": "OPENROUTER_API_KEY"}))["result"] == "(unset)"
    assert json.loads(handle_function_call("mcp_envy_env", {"name": "SERVER_SETTING"}))["result"] == "explicit"


def test_broken_servers_are_skipped_not_fatal(tmp_path, fake_server, clite_home):
    crash = tmp_path / "crash.py"
    crash.write_text("import sys; print('boom: missing dependency', file=sys.stderr); sys.exit(3)\n")
    silent = tmp_path / "silent.py"
    silent.write_text("import time; time.sleep(60)\n")
    connected = connect_mcp_servers({"mcp_servers": {
        "missing": {"command": "/no/such/binary"},
        "crash": {"command": sys.executable, "args": [str(crash)]},
        "http-only": {"url": "https://example.test/mcp"},
        "good": fake_server,
    }})
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
        f"    command: {sys.executable}\n    args: ['{fake_server['args'][0]}']\n")
    client = ScriptedClient([tool_call_response(("mcp_calc_add", {"a": 20, "b": 22})), text_response("It is 42.")])
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
    script.write_text(textwrap.dedent('''
        from mcp.server.mcpserver import MCPServer

        server = MCPServer("sdk-demo")

        @server.tool()
        def shout(text: str) -> str:
            """Return the text in upper case."""
            return text.upper()

        server.run()
    '''))
    client = McpServer("sdk", {"command": sys.executable, "args": [str(script)]})
    try:
        client.start()
        assert client.server_info["name"] == "sdk-demo"
        tool = next(tool for tool in client.tools if tool["name"] == "shout")
        assert tool["description"] == "Return the text in upper case." and "text" in tool["inputSchema"]["properties"]
        assert json.loads(client.call_tool("shout", {"text": "hello"}))["result"] == "HELLO"
    finally:
        client.stop()
