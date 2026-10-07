"""MCP client: tools, resources and prompts served by external processes or HTTP endpoints.

MCP is JSON-RPC 2.0. Two transports carry it here:

* **stdio** — one server process, one message per line on its stdin/stdout (``_StdioTransport``);
* **Streamable HTTP** — JSON-RPC in POSTs to one URL, with an ``Mcp-Session-Id`` header
  (``clite.tools.mcp.http.HttpTransport``).

The protocol subset this client speaks is ``initialize``, ``tools/list``, ``tools/call``,
``resources/list``, ``resources/read``, ``prompts/list`` and ``prompts/get``. It does not use
the MCP SDK: the protocol is simple, and depending on the SDK would tie the agent to its
release schedule for something a few hundred lines cover.

Each configured server becomes a toolset named ``mcp-<server>``, with tools named
``mcp_<server>_<tool>``. When a server declares resource capabilities it also gets
``mcp_<server>_list_resources`` and ``mcp_<server>_read_resource``. Its prompts become slash
commands named ``mcp-<server>-<prompt>`` (built in ``clite.runtime.commands``). Platform
toolsets include every ``mcp-*`` toolset automatically.

A server that announces a new tool list mid-session does **not** change the running session's
tools: the tool list a session was built with is what it keeps (invariant A1). The change is
remembered and takes effect when the next session connects.

Config::

    mcp_servers:
      files:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/notes"]
        env: {SOME_KEY: value}        # extra environment for the server process
        timeout: 60                   # seconds per tool call
        tools: {include: [read_file], exclude: []}
        enabled: true
      remote:
        url: https://mcp.example.com/mcp
        headers: {Authorization: "Bearer ${REMOTE_MCP_TOKEN}"}   # ${NAME} read from .env
        timeout: 60
        enabled: true

Not covered yet (see the roadmap): sampling, and OAuth for HTTP servers.
"""

from __future__ import annotations

import atexit
import json
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from clite import __version__
from clite.core.constants import home_key
from clite.tools.environments.local import build_child_env
from clite.tools.mcp.http import DEFAULT_HTTP_TIMEOUT_SECONDS, HttpTransport, McpError
from clite.tools.registry import PARALLEL_NEVER, PARALLEL_SAFE, registry, tool_error, tool_result

logger = logging.getLogger("clite.tools.mcp")

PROTOCOL_VERSION = "2025-06-18"
STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0
# A dead server is revived on the next connect; repeated failures back off so a server that is
# down for the afternoon is not re-dialed on every turn.
RECONNECT_BASE_DELAY_SECONDS = 5.0
RECONNECT_MAX_DELAY_SECONDS = 300.0
_NAME_RE = re.compile(r"[^A-Za-z0-9_]")
_SLASH_RE = re.compile(r"[^a-z0-9-]")

__all__ = [
    "McpError",
    "McpPrompt",
    "McpServer",
    "connect_mcp_servers",
    "mcp_prompt_commands",
    "read_mcp_prompt",
    "render_mcp_prompt",
    "shutdown_mcp_servers",
]


def safe_name(text: str) -> str:
    return _NAME_RE.sub("_", text)


def prompt_slug(server: str, prompt: str) -> str:
    """The slash command name for a server prompt: ``mcp-<server>-<prompt>``, lowercased."""
    raw = f"mcp-{server}-{prompt}".lower()
    return _SLASH_RE.sub("-", raw).strip("-")


@dataclass(frozen=True)
class McpPrompt:
    """One prompt a server offers, plus the server it came from."""

    server: str
    name: str
    description: str
    arguments: tuple[dict[str, Any], ...] = ()

    @property
    def command(self) -> str:
        return prompt_slug(self.server, self.name)

    def usage(self) -> str:
        required = [str(arg.get("name")) for arg in self.arguments if arg.get("required")]
        optional = [f"[{arg.get('name')}]" for arg in self.arguments if not arg.get("required")]
        return " ".join([*required, *optional])


@dataclass
class _Waiter:
    """A request in flight: the event its sender waits on and the reply once it arrives."""

    event: threading.Event = field(default_factory=threading.Event)
    message: dict[str, Any] | None = None


class _StdioTransport:
    """One server process and the line-delimited JSON-RPC around it."""

    def __init__(self, server: McpServer) -> None:
        self.server = server
        self.process: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._stderr_tail: list[str] = []
        self._stderr_reader: threading.Thread | None = None

    def start(self) -> None:
        server = self.server
        command = server.spec.get("command")
        if not command:
            raise McpError(f"mcp server {server.name!r} has no command and no url")
        env = build_child_env({str(k): str(v) for k, v in (server.spec.get("env") or {}).items()})
        try:
            self.process = subprocess.Popen(  # noqa: S603 - the user configured this command
                [str(command), *[str(arg) for arg in server.spec.get("args") or []]], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                env=env, cwd=server.spec.get("cwd") or None)
        except OSError as exc:
            raise McpError(f"could not start mcp server {server.name!r}: {exc}") from exc
        server.process = self.process  # the old attribute name, kept for callers that watch it
        threading.Thread(target=self._read_stdout, name=f"clite-mcp-{server.name}", daemon=True).start()
        self._stderr_reader = threading.Thread(target=server._read_stderr, name=f"clite-mcp-{server.name}-err", daemon=True)
        self._stderr_reader.start()

    def send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            raise McpError(f"mcp server {self.server.name!r} is not running" + self.server._stderr_hint())
        with self._write_lock:
            try:
                process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except OSError as exc:
                raise McpError(f"mcp server {self.server.name!r} closed its input: {exc}"
                               + self.server._stderr_hint()) from exc

    def stderr_hint(self) -> str:
        # stdout EOF/process exit can precede the stderr reader getting its last timeslice.
        if self._stderr_reader is not None:
            self._stderr_reader.join(timeout=1)
        return f" (stderr: {' | '.join(self._stderr_tail[-3:])})" if self._stderr_tail else ""

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("mcp server %s wrote a non-JSON line: %s", self.server.name, line[:200])
                continue
            if isinstance(message, dict):
                self.server._handle_incoming(message)
        # The server is gone: wake everything still waiting.
        self.server._fail_pending()

    def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        for line in self.process.stderr:
            self._stderr_tail = [*self._stderr_tail[-19:], line.rstrip()]

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        if self._stderr_reader is not None:
            self._stderr_reader.join(timeout=1)
        self.process = None
        self.server.process = None


class McpServer:
    """One MCP server (a process or an HTTP endpoint) and the request/response plumbing around it."""

    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name = name
        self.spec = spec
        self.timeout = float(spec.get("timeout") or (DEFAULT_HTTP_TIMEOUT_SECONDS if spec.get("url") else DEFAULT_CALL_TIMEOUT_SECONDS))
        self.process: subprocess.Popen | None = None  # set for stdio transports, for callers that watch it
        self.tools: list[dict[str, Any]] = []
        self.resources: list[dict[str, Any]] = []
        self.prompts: list[McpPrompt] = []
        self.capabilities: dict[str, Any] = {}
        self.registered: list[str] = []  # names under which the tools are exposed to the model
        self.server_info: dict[str, Any] = {}
        self._next_id = 0
        self._pending: dict[int, _Waiter] = {}
        self._lock = threading.Lock()
        # Set when the server announces a new tool list. The running session keeps the tools it
        # was built with (A1); the next connect re-reads them.
        self.tools_changed = False
        self._transport: _StdioTransport | HttpTransport | None = None
        self._failures = 0
        self._retry_after = 0.0  # monotonic deadline before this server is dialed again

    # ── process and wire ─────────────────────────────────────────────────────────────────

    @property
    def is_http(self) -> bool:
        return bool(self.spec.get("url")) and not self.spec.get("command")

    def start(self) -> None:
        self._transport = HttpTransport(self.name, self.spec) if self.is_http else _StdioTransport(self)
        self._transport.start()
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "clite", "version": __version__},
        }, timeout=STARTUP_TIMEOUT_SECONDS)
        self.server_info = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}
        if isinstance(self._transport, HttpTransport):
            self._transport.protocol_version = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        self.notify("notifications/initialized")
        self.tools = self._list_paginated("tools/list", "tools")
        self.tools_changed = False
        if self._supports("resources"):
            self.resources = self._list_paginated("resources/list", "resources")
        if self._supports("prompts"):
            self.prompts = [self._to_prompt(entry) for entry in self._list_paginated("prompts/list", "prompts")
                            if isinstance(entry, dict) and entry.get("name")]

    def _supports(self, capability: str) -> bool:
        return isinstance(self.capabilities.get(capability), dict)

    def _to_prompt(self, entry: dict[str, Any]) -> McpPrompt:
        arguments = tuple(arg for arg in entry.get("arguments") or [] if isinstance(arg, dict))
        return McpPrompt(self.name, str(entry["name"]), str(entry.get("description") or ""), arguments)

    def _list_paginated(self, method: str, key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = None
        for _ in range(50):  # a server that never stops paginating must not hang startup
            result = self.request(method, {"cursor": cursor} if cursor else {}, timeout=STARTUP_TIMEOUT_SECONDS)
            items.extend(item for item in result.get(key) or [] if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return items

    def _send(self, message: dict[str, Any]) -> None:
        transport = self._transport
        if isinstance(transport, _StdioTransport):
            transport.send(message)
            return
        if isinstance(transport, HttpTransport):
            reply = transport.send(message)
            if reply is not None:
                self._handle_incoming(reply)
            return
        raise McpError(f"mcp server {self.name!r} is not connected")

    def _stderr_hint(self) -> str:
        transport = self._transport
        return transport.stderr_hint() if isinstance(transport, _StdioTransport) else ""

    def _read_stderr(self) -> None:
        # Kept on the server (not only the transport) so a caller can drain stderr itself; the
        # stdio transport spawns the drain thread through this method.
        transport = self._transport
        if isinstance(transport, _StdioTransport):
            transport._read_stderr()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            message["params"] = params
        self._send(message)

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            waiter = self._pending[request_id] = _Waiter()
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            if not waiter.event.wait(timeout or self.timeout):
                raise McpError(f"mcp server {self.name!r} did not answer {method} within {timeout or self.timeout:.0f}s")
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        message = waiter.message
        if message is None:
            raise McpError(f"mcp server {self.name!r} exited" + self._stderr_hint())
        if "error" in message:
            error = message["error"] or {}
            raise McpError(f"{error.get('message', 'error')} (code {error.get('code')})")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def _fail_pending(self) -> None:
        with self._lock:
            waiters = list(self._pending.values())
        for waiter in waiters:
            waiter.event.set()

    def _handle_incoming(self, message: dict[str, Any]) -> None:
        """A message from the server: a reply, a request, or a notification."""
        if "method" in message:
            self._handle_server_message(message)
            return
        with self._lock:
            reply_to = message.get("id")
            waiter = self._pending.get(reply_to) if isinstance(reply_to, int) else None
        if waiter is not None:
            waiter.message = message
            waiter.event.set()

    def _handle_server_message(self, message: dict[str, Any]) -> None:
        """Requests and notifications coming from the server."""
        method = str(message.get("method") or "")
        if "id" not in message:
            if method == "notifications/tools/list_changed":
                # A1: the running session keeps the tools it was built with. Remember the change
                # for the next session; never touch the live tool definitions.
                self.tools_changed = True
                logger.info("mcp server %s changed its tool list; it applies to the next session", self.name)
            elif method == "notifications/resources/list_changed":
                self.resources = []  # the next session re-reads them along with the tools
            return
        try:
            if method == "ping":
                self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            else:  # sampling, roots, elicitation: capabilities we did not announce
                self._send({"jsonrpc": "2.0", "id": message["id"],
                            "error": {"code": -32601, "message": f"{method} is not supported by this client"}})
        except McpError:
            pass

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

    def list_resources(self) -> str:
        """The server's resources as a tool result, re-read live so it is never stale."""
        try:
            resources = self._list_paginated("resources/list", "resources")
        except McpError as exc:
            return tool_error(str(exc))
        self.resources = resources
        if not resources:
            return tool_result({"resources": [], "note": "this server exposes no resources"})
        return tool_result({"resources": [
            {"uri": entry.get("uri"), "name": entry.get("name") or entry.get("uri"),
             "description": entry.get("description") or "", "mimeType": entry.get("mimeType") or ""}
            for entry in resources
        ]})

    def read_resource(self, uri: str) -> str:
        """Read one resource by ``uri``; text contents are returned, binary is noted by type."""
        if not uri:
            return tool_error(f"uri is required; call mcp_{safe_name(self.name)}_list_resources to see the available URIs")
        try:
            result = self.request("resources/read", {"uri": uri})
        except McpError as exc:
            return tool_error(f"could not read {uri}: {exc}")
        contents = []
        for block in result.get("contents") or []:
            if not isinstance(block, dict):
                continue
            if isinstance(block.get("text"), str):
                contents.append({"uri": block.get("uri") or uri, "mimeType": block.get("mimeType") or "", "text": block["text"]})
            else:
                contents.append({"uri": block.get("uri") or uri, "mimeType": block.get("mimeType") or "",
                                 "note": "non-text content omitted"})
        if not contents:
            return tool_result({"uri": uri, "contents": [], "note": "the resource is empty"})
        return tool_result({"uri": uri, "contents": contents})

    def register_tools(self) -> list[str]:
        """Expose this server's tools to the model. Returns the registered names.

        Only called when a session is built or refreshed, never from a notification: the tool
        list a session was created with stays fixed (A1).
        """
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
        if self._supports("resources"):
            registered += self._register_resource_tools(toolset, origin)
        self.registered = registered
        return registered

    def _register_resource_tools(self, toolset: str, origin: str) -> list[str]:
        """``mcp_<server>_list_resources`` and ``mcp_<server>_read_resource`` for resource servers."""
        prefix = f"mcp_{safe_name(self.name)}"
        list_name, read_name = f"{prefix}_list_resources", f"{prefix}_read_resource"
        registry.register(
            list_name, toolset,
            {"name": list_name,
             "description": f"[{self.name}] List the resources this server exposes (URIs you can read "
                            f"with {read_name})"[:1024],
             "parameters": {"type": "object", "properties": {}}},
            lambda args: self.list_resources(), origin=origin, parallel=PARALLEL_SAFE,
            override=True, check_fn=self.is_alive)
        registry.register(
            read_name, toolset,
            {"name": read_name,
             "description": f"[{self.name}] Read one resource by URI (from {list_name})"[:1024],
             "parameters": {"type": "object", "properties": {"uri": {"type": "string",
                                                                     "description": "The resource URI to read"}},
                            "required": ["uri"]}},
            lambda args: self.read_resource(str(args.get("uri") or "")), origin=origin, parallel=PARALLEL_SAFE,
            override=True, check_fn=self.is_alive, path_args=())
        return [list_name, read_name]

    def is_alive(self) -> bool:
        if self._retry_after and time.monotonic() < self._retry_after:
            return False
        transport = self._transport
        return transport is not None and transport.is_alive()

    def read_prompt(self, prompt: str, arguments: dict[str, Any]) -> str:
        """Fetch a prompt's messages as text. Errors become text, never an exception."""
        args = {key: value for key, value in arguments.items() if value not in (None, "")}
        try:
            result = self.request("prompts/get", {"name": prompt, "arguments": args})
        except McpError as exc:
            return f"Could not load prompt {prompt!r} from {self.name}: {exc}"
        return render_prompt_messages(result)

    # ── lifecycle ────────────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        registry.deregister_origin(f"mcp:{self.name}")
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:  # noqa: BLE001 - shutting down must not raise
                pass
        self._transport = None
        self.process = None

    def mark_failure(self) -> float:
        """Record a failure and back off before the next attempt. Returns the delay in seconds."""
        self._failures += 1
        delay = self.backoff_seconds()
        self._retry_after = time.monotonic() + delay
        return delay

    def backoff_seconds(self) -> float:
        """The delay before the next attempt: base * 2^(failures-1), capped (exponential)."""
        return min(RECONNECT_BASE_DELAY_SECONDS * (2 ** (self._failures - 1)), RECONNECT_MAX_DELAY_SECONDS)

    def clear_failure(self) -> None:
        self._failures = 0
        self._retry_after = 0.0

    def ready_for_retry(self) -> bool:
        """True when the backoff window has passed and the server may be dialed again."""
        return not self._retry_after or time.monotonic() >= self._retry_after

    def retry_seconds_left(self) -> float:
        return max(self._retry_after - time.monotonic(), 0.0)


def render_prompt_messages(result: dict[str, Any]) -> str:
    """Turn a ``prompts/get`` result into one text block for the user message."""
    parts: list[str] = []
    description = str(result.get("description") or "").strip()
    if description:
        parts.append(description)
    for message in result.get("messages") or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        text = content.get("text") if isinstance(content, dict) else content
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts) or "(the prompt produced no messages)"


_SERVERS: dict[tuple[str, str], McpServer] = {}
_SERVERS_LOCK = threading.Lock()


def connect_mcp_servers(config: dict[str, Any]) -> dict[str, list[str]]:
    """Start every enabled server in ``mcp_servers`` that is not already running.

    Returns ``{server name: [tool names]}``. A server that fails to start is logged, backed
    off, and skipped: one broken integration must not stop the agent. A server whose tool list
    changed since the last session is re-read here, so the change takes effect for the new
    session (A1).
    """
    connected: dict[str, list[str]] = {}
    home = home_key()
    for name, spec in (config.get("mcp_servers") or {}).items():
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            continue
        key = (home, str(name))
        with _SERVERS_LOCK:
            existing = _SERVERS.get(key)
        if existing is not None and existing.spec != spec:
            existing.stop()  # the server was reconfigured; the old one is meaningless now
            existing = None
        if existing is not None and not existing.is_alive():
            if existing.ready_for_retry():
                existing.stop()
                existing = None
            else:
                # Inside the backoff window: leave it alone, the next session may try again.
                with _SERVERS_LOCK:
                    _SERVERS[key] = existing
                continue
        if existing is not None and existing.tools_changed:
            # New session: pick up the tool list the old session deliberately kept out (A1).
            try:
                _refresh(existing)
                existing.register_tools()  # the new list becomes this session's tools
            except McpError as exc:
                logger.warning("mcp server %s could not refresh its tool list: %s", name, exc)
                existing.stop()
                existing = None
        if existing is not None and existing.is_alive():
            connected[str(name)] = list(existing.registered)
            continue
        server = McpServer(str(name), spec)
        try:
            server.start()
            connected[str(name)] = server.register_tools()
            server.clear_failure()
        except McpError as exc:
            logger.warning("mcp server %s is unavailable: %s", name, exc)
            server.stop()
            server.mark_failure()
            logger.info("mcp server %s will not be retried for %.0fs", name, max(server.retry_seconds_left(), 0))
        with _SERVERS_LOCK:
            _SERVERS[key] = server
    return connected


def _refresh(server: McpServer) -> None:
    """Re-read a server's tools, resources and prompts after it announced a change."""
    server.tools = server._list_paginated("tools/list", "tools")
    if server._supports("resources"):
        server.resources = server._list_paginated("resources/list", "resources")
    if server._supports("prompts"):
        server.prompts = [server._to_prompt(entry) for entry in server._list_paginated("prompts/list", "prompts")
                          if isinstance(entry, dict) and entry.get("name")]
    server.tools_changed = False


def shutdown_mcp_servers() -> None:
    with _SERVERS_LOCK:
        servers = list(_SERVERS.values())
        _SERVERS.clear()
    for server in servers:
        server.stop()


def mcp_servers_snapshot() -> list[dict[str, Any]]:
    """Every known server and its state, for `clite mcp list` and `/mcp`."""
    with _SERVERS_LOCK:
        servers = list(_SERVERS.values())
    rows = []
    for server in servers:
        rows.append({
            "name": server.name,
            "transport": "http" if server.is_http else "stdio",
            "alive": server.is_alive(),
            "tools": list(server.registered),
            "resources": len(server.resources),
            "prompts": len(server.prompts),
            "tools_changed": server.tools_changed,
        })
    return rows


# ── prompts as slash commands ─────────────────────────────────────────────────────────────


def mcp_prompt_commands() -> dict[str, McpPrompt]:
    """``{slash command name: prompt}`` for every prompt of every connected server."""
    with _SERVERS_LOCK:
        servers = list(_SERVERS.values())
    commands: dict[str, McpPrompt] = {}
    for server in servers:
        for prompt in server.prompts:
            commands.setdefault(prompt.command, prompt)
    return commands


def read_mcp_prompt(command: str, args: str) -> str:
    """Run the prompt behind ``command`` with the user's free-text ``args``.

    Positional words fill the prompt's declared arguments in order; anything left over is
    appended to the last argument, or to no argument at all when the prompt takes none.
    """
    prompt = mcp_prompt_commands().get(command)
    if prompt is None:
        return f"Unknown MCP prompt /{command}."
    names = [str(arg.get("name")) for arg in prompt.arguments]
    words = args.split()
    arguments: dict[str, str] = {}
    for index, name in enumerate(names):
        if index < len(words):
            arguments[name] = " ".join(words[index:]) if index == len(names) - 1 else words[index]
    if names and not words:
        return (f"/{command} needs arguments: {' '.join(names)}. "
                f"Usage: /{command} {prompt.usage()}".strip())
    server = next((item for item in _servers_for(prompt.server)), None)
    if server is None:
        return f"MCP server {prompt.server!r} is not connected."
    return server.read_prompt(prompt.name, arguments)


def _servers_for(name: str) -> list[McpServer]:
    with _SERVERS_LOCK:
        return [server for server in _SERVERS.values() if server.name == name]


def render_mcp_prompt(command: str, args: str) -> str:
    """The user message that carries an MCP prompt, framed like a skill invocation."""
    body = read_mcp_prompt(command, args)
    return f'[The user invoked the "{command}" prompt from an MCP server. Its content follows.]\n\n{body}'


def mcp_prompt_error(command: str, args: str) -> str | None:
    """The failure text for a prompt command, or ``None`` when it would load."""
    prompts = mcp_prompt_commands()
    if command not in prompts:
        return f"Unknown MCP prompt /{command}."
    if not _servers_for(prompts[command].server):
        return f"MCP server {prompts[command].server!r} is not connected."
    return None


def mcp_prompt_catalog() -> list[dict[str, Any]]:
    """Prompt commands shaped like ``command_catalog`` entries, for help and autocomplete."""
    return [
        {"name": prompt.command, "description": (prompt.description or f"Prompt from {prompt.server}")[:80],
         "category": "MCP", "aliases": [], "args_hint": prompt.usage(), "subcommands": [], "kind": "mcp"}
        for prompt in sorted(mcp_prompt_commands().values(), key=lambda item: item.command)
    ]


atexit.register(shutdown_mcp_servers)
