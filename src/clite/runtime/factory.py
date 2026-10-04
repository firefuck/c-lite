"""``build_agent``: the one place a surface turns "what the user asked for" into an ``AIAgent``.

The CLI, the RPC server, the gateway and cron all build agents here, so they agree on which
plugins are loaded, which toolset a platform gets and what ``--yolo`` means.
"""

from __future__ import annotations

from typing import Any

from clite.agent import AgentCallbacks, AIAgent
from clite.core.config import get_path, load_config
from clite.plugins.manager import ensure_plugins_loaded
from clite.providers.client import ModelClient
from clite.providers.runtime import RuntimeRoute, resolve_runtime_provider
from clite.tools.registry import discover_builtin_tools

# Platforms where a person sits at this machine. They share the user's main toolset setting.
LOCAL_PLATFORMS = frozenset({"cli", "tui", "desktop", "api", "acp"})


def default_toolsets(platform: str, config: dict[str, Any]) -> list[str]:
    """Toolsets for ``platform``: an explicit ``platform_toolsets`` entry, else the platform's
    composite. A messaging platform never silently inherits the terminal user's toolset."""
    override = (get_path(config, "platform_toolsets", {}) or {}).get(platform)
    if isinstance(override, list) and override:
        return [str(item) for item in override]
    if platform in LOCAL_PLATFORMS:
        return list(config.get("toolsets") or ["clite-cli"])
    if platform == "cron":
        return ["clite-cron"]
    return ["clite-gateway"]


def build_agent(
    *,
    platform: str = "cli",
    session_id: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    route: RuntimeRoute | None = None,
    toolsets: list[str] | None = None,
    disabled_toolsets: list[str] | None = None,
    callbacks: AgentCallbacks | None = None,
    cwd: str | None = None,
    yolo: bool = False,
    system_message: str | None = None,
    session_meta: dict[str, Any] | None = None,
    client: ModelClient | None = None,
    config: dict[str, Any] | None = None,
    max_turns: int | None = None,
    auto_title: bool = True,
    **agent_options: Any,
) -> AIAgent:
    cfg = config if config is not None else load_config()
    ensure_plugins_loaded()  # before tools are resolved: plugins contribute tools and providers
    discover_builtin_tools()
    if cfg.get("mcp_servers"):
        from clite.tools.mcp import connect_mcp_servers

        connect_mcp_servers(cfg)
    return AIAgent(
        route or resolve_runtime_provider(provider, model, config=cfg),
        session_id=session_id,
        platform=platform,
        cwd=cwd,
        enabled_toolsets=toolsets if toolsets is not None else default_toolsets(platform, cfg),
        disabled_toolsets=disabled_toolsets,
        max_turns=max_turns,
        callbacks=callbacks,
        config=cfg,
        client=client,
        system_message=system_message,
        approval_mode="off" if yolo else None,
        session_meta=session_meta,
        auto_title=auto_title,
        **agent_options,
    )
