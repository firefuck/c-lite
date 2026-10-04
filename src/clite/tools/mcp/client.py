"""A small MCP client over stdio. Standard library only.

MCP over stdio is JSON-RPC 2.0, one message per line: ``initialize``, then ``tools/list``,
then ``tools/call`` as the model asks. This file speaks exactly that subset. It does not use
the MCP SDK: the protocol is simple, and depending on the SDK would tie the agent to the
SDK's release schedule for something a hundred lines cover.

Each configured server becomes a toolset named ``mcp-<server>``, with tools named
``mcp_<server>_<tool>``. Platform toolsets include every ``mcp-*`` toolset automatically.

Config::

    mcp_servers:
      files:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/notes"]
        env: {SOME_KEY: value}        # extra environment for the server process
        timeout: 60                   # seconds per tool call
        tools: {include: [read_file], exclude: []}
        enabled: true

Not covered yet (see the roadmap): the HTTP transport, resources, prompts, sampling.
"""

from __future__ import annotations

import atexit
import json
import logging
import re
import subprocess
import threading
from typing import Any

from clite import __version__
from clite.core.constants import home_key
from clite.tools.environments.local import build_child_env
from clite.tools.registry import PARALLEL_NEVER, registry, tool_error, tool_result

logger = logging.getLogger("clite.tools.mcp")

PROTOCOL_VERSION = "2025-06-18"
STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0
_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


class McpError(Exception):
    pass


def safe_name(text: str) -> str:
    return _NAME_RE.sub("_", text)


class McpServer:
    """One server process and the request/response plumbing around it."""

    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name = name
        self.spec = spec
        self.timeout = float(spec.get("timeout") or DEFAULT_CALL_TIMEOUT_SECONDS)
        self.process: subprocess.Popen | None = None
        self.tools: list[dict[str, Any]] = []
        self.registered: list[str] = []  # names under which the tools are exposed to the model
        self.server_info: dict[str, Any] = {}
        self._next_id = 0
        self._pending: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stderr_tail: list[str] = []

    # ── process and wire ─────────────────────────────────────────────────────────────────

    def start(self) -> None:
        command = self.spec.get("command")
        if not command:
            raise McpError(f"mcp server {self.name!r} has no command (only stdio servers are supported so far)")
        env = build_child_env({str(k): str(v) for k, v in (self.spec.get("env") or {}).items()})
        try:
            self.process = subprocess.Popen(  # noqa: S603 - the user configured this command
                [str(command), *[str(arg) for arg in self.spec.get("args") or []]], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                env=env, cwd=self.spec.get("cwd") or None)
        except OSError as exc:
            raise McpError(f"could not start mcp server {self.name!r}: {exc}") from exc
        threading.Thread(target=self._read_stdout, name=f"clite-mcp-{self.name}", daemon=True).start()
        threading.Thread(target=self._read_stderr, name=f"clite-mcp-{self.name}-err", daemon=True).start()

        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "clite", "version": __version__},
        }, timeout=STARTUP_TIMEOUT_SECONDS)
        self.server_info = result.get("serverInfo") or {}
        self.notify("notifications/initialized")
        self.tools = self._list_tools()

    def _list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor = None
        for _ in range(50):  # a server that never stops paginating must not hang startup
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=STARTUP_TIMEOUT_SECONDS)
            tools.extend(tool for tool in result.get("tools") or [] if isinstance(tool, dict) and tool.get("name"))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            raise McpError(f"mcp server {self.name!r} is not running" + self._stderr_hint())
        with self._write_lock:
            try:
                process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except OSError as exc:
                raise McpError(f"mcp server {self.name!r} closed its input: {exc}") from exc

    def _stderr_hint(self) -> str:
        return f" (stderr: {' | '.join(self._stderr_tail[-3:])})" if self._stderr_tail else ""

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            message["params"] = params
        self._send(message)

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            waiter = {"event": threading.Event(), "message": None}
            self._pending[request_id] = waiter
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            if not waiter["event"].wait(timeout or self.timeout):
                raise McpError(f"mcp server {self.name!r} did not answer {method} within {timeout or self.timeout:.0f}s")
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        message = waiter["message"]
        if message is None:
            raise McpError(f"mcp server {self.name!r} exited" + self._stderr_hint())
        if "error" in message:
            error = message["error"] or {}
            raise McpError(f"{error.get('message', 'error')} (code {error.get('code')})")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("mcp server %s wrote a non-JSON line: %s", self.name, line[:200])
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message:
                self._handle_server_message(message)
                continue
            with self._lock:
                waiter = self._pending.get(message.get("id"))
            if waiter is not None:
                waiter["message"] = message
                waiter["event"].set()
        # The server is gone: wake everything still waiting.
        with self._lock:
            waiters = list(self._pending.values())
        for waiter in waiters:
            waiter["event"].set()

    def _handle_server_message(self, message: dict[str, Any]) -> None:
        """Requests and notifications coming from the server."""
        if "id" not in message:
            return  # a notification (log, progress, list_changed): nothing to answer
        try:
            if message.get("method") == "ping":
                self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            else:  # sampling, roots, elicitation: capabilities we did not announce
                self._send({"jsonrpc": "2.0", "id": message["id"],
                            "error": {"code": -32601, "message": f"{message.get('method')} is not supported by this client"}})
        except McpError:
            pass

    def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        for line in self.process.stderr:
            self._stderr_tail = [*self._stderr_tail[-19:], line.rstrip()]

    # ── tools ────────────────────────────────────────────────────────────────────────────

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        try:
            result = self.request("tools/call", {"name": tool_name, "arguments": arguments})
        except McpError as exc:
            return tool_error(str(exc))
        parts = []
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, dict):
                parts.append(f"[{block.get('type', 'unknown')} content omitted]")
        text = "\n".join(parts)
        if result.get("isError"):
            return tool_error(text or "the tool reported an error")
        payload: dict[str, Any] = {"result": text}
        if isinstance(result.get("structuredContent"), dict):
            payload["structured"] = result["structuredContent"]
        return tool_result(payload)

    def register_tools(self) -> list[str]:
        """Expose this server's tools to the model. Returns the registered names."""
        selection = self.spec.get("tools") or {}
        include, exclude = set(selection.get("include") or []), set(selection.get("exclude") or [])
        toolset, origin = f"mcp-{self.name}", f"mcp:{self.name}"
        registered = []
        for tool in self.tools:
            name = str(tool["name"])
            if (include and name not in include) or name in exclude:
                continue
            exposed = f"mcp_{safe_name(self.name)}_{safe_name(name)}"
            schema = {
                "name": exposed,
                "description": f"[{self.name}] {tool.get('description') or name}"[:1024],
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            }
            registry.register(exposed, toolset, schema, lambda args, _name=name: self.call_tool(_name, args),
                              origin=origin, parallel=PARALLEL_NEVER, override=True, check_fn=self.is_alive)
            registered.append(exposed)
        self.registered = registered
        return registered

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        registry.deregister_origin(f"mcp:{self.name}")
        process = self.process
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        self.process = None


_SERVERS: dict[tuple[str, str], McpServer] = {}
_SERVERS_LOCK = threading.Lock()


def connect_mcp_servers(config: dict[str, Any]) -> dict[str, list[str]]:
    """Start every enabled server in ``mcp_servers`` that is not already running.

    Returns ``{server name: [tool names]}``. A server that fails to start is logged and
    skipped: one broken integration must not stop the agent.
    """
    connected: dict[str, list[str]] = {}
    home = home_key()
    for name, spec in (config.get("mcp_servers") or {}).items():
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            continue
        key = (home, str(name))
        with _SERVERS_LOCK:
            existing = _SERVERS.get(key)
        if existing is not None and existing.is_alive() and existing.spec == spec:
            connected[str(name)] = list(existing.registered)
            continue
        if existing is not None:
            existing.stop()
        server = McpServer(str(name), spec)
        try:
            server.start()
            connected[str(name)] = server.register_tools()
        except McpError as exc:
            logger.warning("mcp server %s is unavailable: %s", name, exc)
            server.stop()
            continue
        with _SERVERS_LOCK:
            _SERVERS[key] = server
    return connected


def shutdown_mcp_servers() -> None:
    with _SERVERS_LOCK:
        servers = list(_SERVERS.values())
        _SERVERS.clear()
    for server in servers:
        server.stop()


atexit.register(shutdown_mcp_servers)
