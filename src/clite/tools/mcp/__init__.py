"""MCP (Model Context Protocol) client: tools, resources and prompts from another program."""

from clite.tools.mcp.client import (
    McpError,
    McpPrompt,
    McpServer,
    connect_mcp_servers,
    mcp_prompt_catalog,
    mcp_prompt_commands,
    mcp_prompt_error,
    mcp_servers_snapshot,
    read_mcp_prompt,
    render_mcp_prompt,
    shutdown_mcp_servers,
)

__all__ = [
    "McpError",
    "McpPrompt",
    "McpServer",
    "connect_mcp_servers",
    "mcp_prompt_catalog",
    "mcp_prompt_commands",
    "mcp_prompt_error",
    "mcp_servers_snapshot",
    "read_mcp_prompt",
    "render_mcp_prompt",
    "shutdown_mcp_servers",
]
