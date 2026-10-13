"""``clite mcp``: add, list, remove and test MCP servers without editing YAML.

The config edit goes through :func:`clite.core.config.atomic_config_update`, the same single
writer the rest of the CLI uses, so a crash mid-write cannot leave a half-written config.

    clite mcp add files --command npx --args "-y @modelcontextprotocol/server-filesystem /notes"
    clite mcp add remote --url https://mcp.example.com/mcp --header Authorization "Bearer ${TOKEN}"
    clite mcp list
    clite mcp test remote          # connect once and report the tools, resources and prompts
    clite mcp remove remote
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from clite.core.config import atomic_config_update, load_config
from clite.core.errors import CliteError
from clite.tools.mcp import McpServer, mcp_servers_snapshot
from clite.tools.mcp.http import build_headers

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise CliteError(f"invalid server name {name!r}: use letters, digits, '-' and '_'")


def _split_args(values: list[str] | None) -> list[str]:
    """``--args "a b"`` or repeated ``--args a --args b`` both become a flat list."""
    tokens: list[str] = []
    for value in values or []:
        tokens.extend(value.split())
    return tokens


def _parse_headers(pairs: list[str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for pair in pairs or []:
        header, _, value = pair.partition("=")
        header, value = header.strip(), value.strip()
        if not header or not value:
            raise CliteError(f"invalid --header {pair!r}: write it as NAME=VALUE")
        headers[header] = value
    return headers


def run_add(args: argparse.Namespace) -> int:
    _check_name(args.name)
    if bool(args.url) == bool(args.command):
        raise CliteError("give exactly one of --command (a local process) or --url (a remote HTTP endpoint)")
    spec: dict[str, object] = {}
    if args.url:
        spec["url"] = args.url
    else:
        spec["command"] = args.command
        if args.args or args.cwd:
            spec["args"] = _split_args(args.args)
        if args.cwd:
            spec["cwd"] = args.cwd
    headers = _parse_headers(args.header)
    if headers:
        spec["headers"] = headers
    if args.timeout:
        spec["timeout"] = args.timeout
    if args.disabled:
        spec["enabled"] = False

    def mutate(document: dict[str, Any]) -> None:
        servers = document.get("mcp_servers")
        if not isinstance(servers, dict):
            servers = document["mcp_servers"] = {}
        servers[args.name] = spec

    atomic_config_update(mutate)
    transport = f"url {args.url}" if args.url else f"command {args.command}"
    print(f"Added MCP server {args.name!r} ({transport}).")
    if headers and not _references_resolve(headers):
        print(
            "Note: a header references a variable that is not set in .env yet. Add it to .env, "
            "then `clite mcp test` will connect.",
            file=sys.stderr,
        )
    print(f"Check it with `clite mcp test {args.name}`; new sessions will pick it up.")
    return 0


def _references_resolve(headers: dict[str, str]) -> bool:
    try:
        build_headers({"headers": headers}, "check", register=False)
    except Exception:  # noqa: BLE001 - only used to print an advisory note
        return False
    return True


def run_list(args: argparse.Namespace) -> int:
    configured = load_config().get("mcp_servers") or {}
    if not configured:
        print("No MCP servers are configured. Add one with `clite mcp add --help`.")
        return 0
    live = {row["name"]: row for row in mcp_servers_snapshot()}
    for name, spec in sorted(configured.items()):
        if not isinstance(spec, dict):
            continue
        target = spec.get("url") or spec.get("command") or "(no command or url)"
        enabled = "" if spec.get("enabled", True) else "  [disabled]"
        selection = spec.get("tools")
        included = len(selection.get("include") or []) if isinstance(selection, dict) else 0
        row = live.get(name)
        status = (
            f"{len(row['tools'])} tools live"
            if row and row["alive"]
            else ("not started" if not row else "down")
        )
        print(
            f"{name:<16} {('http' if spec.get('url') else 'stdio'):<6} {status:<12} {target}"
            f"{f'  (restricted to {included} tools)' if included else ''}{enabled}"
        )
    print("\nTest one with `clite mcp test <name>`, remove it with `clite mcp remove <name>`.")
    return 0


def run_remove(args: argparse.Namespace) -> int:
    removed = False

    def mutate(document: dict[str, Any]) -> None:
        nonlocal removed
        servers = document.get("mcp_servers")
        if isinstance(servers, dict) and args.name in servers:
            del servers[args.name]
            removed = True

    atomic_config_update(mutate)
    if not removed:
        print(f"No MCP server named {args.name!r} in the config.")
        return 1
    print(f"Removed MCP server {args.name!r}. It stops being connected in new sessions.")
    return 0


def run_test(args: argparse.Namespace) -> int:
    """Connect once and report what the server offers, without touching the running agent."""
    configured = (load_config().get("mcp_servers") or {}).get(args.name)
    if not isinstance(configured, dict):
        print(f"No MCP server named {args.name!r} in the config. `clite mcp list` shows them.")
        return 1
    spec = {**configured, "enabled": True}
    server = McpServer(args.name, spec)
    try:
        server.start()
    except Exception as exc:  # noqa: BLE001 - a test is exactly where errors are reported
        print(f"{args.name}: could not connect: {exc}", file=sys.stderr)
        return 1
    try:
        print(f"{args.name}: connected ({'http' if server.is_http else 'stdio'})")
        info = server.server_info or {}
        if info:
            print(f"  server: {info.get('name', '?')} {info.get('version', '')}".rstrip())
        tool_names = [str(tool.get("name")) for tool in server.tools]
        print(f"  tools ({len(tool_names)}): {', '.join(tool_names) or 'none'}")
        if server.resources:
            print(
                f"  resources ({len(server.resources)}): "
                f"{', '.join(str(item.get('uri')) for item in server.resources)}"
            )
        if server.prompts:
            print(
                f"  prompts ({len(server.prompts)}): {', '.join(prompt.command for prompt in server.prompts)}"
            )
        if args.json:
            print(
                json.dumps(
                    {
                        "tools": server.tools,
                        "resources": server.resources,
                        "prompts": [prompt.name for prompt in server.prompts],
                    },
                    indent=2,
                )
            )
    finally:
        server.stop()
    return 0


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("mcp", help="add, list, remove and test MCP servers")
    parser.set_defaults(handler=run_list)
    actions = parser.add_subparsers(dest="mcp_action")

    actions.add_parser("list", help="show the configured MCP servers").set_defaults(handler=run_list)

    add = actions.add_parser("add", help="add an MCP server to the config")
    add.add_argument("name", help="the server name used in tool names (mcp_<name>_<tool>)")
    add.add_argument("--command", help="the program that speaks MCP over stdio")
    add.add_argument(
        "--args", action="append", help="arguments for --command (repeatable, or one quoted string)"
    )
    add.add_argument("--url", help="the Streamable HTTP endpoint of a remote server")
    add.add_argument(
        "--header",
        action="append",
        metavar="NAME=VALUE",
        help="an HTTP header; use ${VAR} to read a secret from .env (repeatable)",
    )
    add.add_argument("--cwd", help="working directory for a stdio server")
    add.add_argument("--timeout", type=float, help="seconds to wait for one call")
    add.add_argument("--disabled", action="store_true", help="write the entry but do not connect it")
    add.set_defaults(handler=run_add)

    remove = actions.add_parser("remove", help="remove an MCP server from the config")
    remove.add_argument("name")
    remove.set_defaults(handler=run_remove)

    test = actions.add_parser("test", help="connect once and report the tools found")
    test.add_argument("name")
    test.add_argument("--json", action="store_true", help="also print the raw tool schemas")
    test.set_defaults(handler=run_test)
