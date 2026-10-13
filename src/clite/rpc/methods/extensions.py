"""RPC handlers for what extends the agent: tools, skills, plugins, shell hooks and MCP servers."""

from __future__ import annotations

from collections.abc import Mapping

from clite.core.config import get_path, load_config
from clite.plugins.manager import get_plugin_manager, set_plugin_enabled
from clite.rpc.contracts import schema
from clite.rpc.contracts.base import Empty
from clite.rpc.server import REQUEST_FAILED, RpcError, RpcServer, rpc_method
from clite.skills.catalog import discover_skills, get_skill, linked_files, read_skill_file
from clite.tools.registry import discover_builtin_tools
from clite.tools.toolsets import all_toolsets, resolve_toolset


@rpc_method("tools.list")
def tools_list(server: RpcServer, params: schema.CatalogParams) -> schema.ToolsListResult:
    discover_builtin_tools()
    if params.session_id:
        active = set(server.get_session(params.session_id).chat.agent.tool_names)
    else:
        from clite.tools.dispatch import resolve_enabled_tools

        active = set(resolve_enabled_tools())
    toolsets = []
    for name, spec in sorted(all_toolsets().items()):
        tools = resolve_toolset(name)
        toolsets.append(
            schema.ToolsetEntry(
                name=name,
                description=spec.get("description", ""),
                tools=tools,
                enabled_tools=[tool for tool in tools if tool in active],
            )
        )
    return schema.ToolsListResult(toolsets=toolsets)


@rpc_method("skills.list")
def skills_list(server: RpcServer, params: Empty) -> schema.SkillsListResult:
    return schema.SkillsListResult(
        skills=[schema.SkillEntry(**skill.summary()) for skill in discover_skills()]
    )


@rpc_method("skills.view")
def skills_view(server: RpcServer, params: schema.SkillViewParams) -> schema.SkillViewResult:
    skill = get_skill(params.name)
    if skill is None:
        raise RpcError(REQUEST_FAILED, f"no skill named {params.name!r}")
    try:
        content = read_skill_file(skill, params.file_path)
    except (PermissionError, FileNotFoundError) as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc
    return schema.SkillViewResult(name=skill.name, content=content, linked_files=linked_files(skill))


def _plugins() -> schema.PluginsListResult:
    manager = get_plugin_manager()
    manager.load_all()
    return schema.PluginsListResult(plugins=[schema.PluginEntry(**info.summary()) for info in manager.list()])


@rpc_method("plugins.list")
def plugins_list(server: RpcServer, params: Empty) -> schema.PluginsListResult:
    return _plugins()


@rpc_method("plugins.set_enabled")
def plugins_set_enabled(server: RpcServer, params: schema.PluginSetEnabledParams) -> schema.PluginsListResult:
    manager = get_plugin_manager()
    manager.discover()
    if params.name not in manager.plugins:
        raise RpcError(REQUEST_FAILED, f"no plugin named {params.name!r}")
    set_plugin_enabled(params.name, params.enabled)
    return _plugins()


@rpc_method("hooks.status")
def hooks_status(server: RpcServer, params: Empty) -> schema.HooksStatusResult:
    from clite.plugins.shell_hooks import allowlist_path, configured_hooks, is_approved

    hooks = [
        schema.ShellHookEntry(
            event=hook.event,
            command=hook.command,
            matcher=hook.matcher,
            timeout=hook.timeout,
            fail_closed=hook.fail_closed,
            approved=is_approved(hook),
        )
        for hook in configured_hooks()
    ]
    # Approval stays a local act (`clite hooks approve`): the dashboard only reports.
    return schema.HooksStatusResult(
        hooks=hooks,
        pending=sum(1 for hook in hooks if not hook.approved),
        allowlist_path=str(allowlist_path()),
    )


@rpc_method("mcp.status")
def mcp_status(server: RpcServer, params: Empty) -> schema.McpStatusResult:
    from clite.tools.mcp.client import mcp_servers_snapshot

    configured = get_path(load_config(), "mcp_servers", {}) or {}
    return schema.McpStatusResult(
        servers=[
            schema.McpServerEntry.model_validate(
                {key: row.get(key) for key in schema.McpServerEntry.model_fields if row.get(key) is not None}
            )
            for row in mcp_servers_snapshot()
        ],
        configured=len(configured) if isinstance(configured, Mapping) else 0,
    )
