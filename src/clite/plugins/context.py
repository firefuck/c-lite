"""``PluginContext``: the API a plugin's ``register(ctx)`` receives.

Everything a plugin adds goes through this object, and every registration is written to a
ledger. That is what makes a plugin removable: unloading replays the ledger backwards.

A plugin must not import core internals to patch them. If a plugin needs something this
context cannot do, the fix is a new method here (a general capability any plugin could use),
not a special case in core for that one plugin.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clite.core.config import get_path, load_config
from clite.core.constants import get_home
from clite.plugins.hooks import get_hook_bus
from clite.plugins.manifest import PluginManifest

if TYPE_CHECKING:
    from clite.plugins.manager import PluginManager


@dataclass
class PluginCommand:
    """A slash command contributed by a plugin."""

    name: str
    handler: Callable[..., Any]  # handler(args: str, session) -> str | None
    description: str = ""
    args_hint: str = ""
    plugin: str = ""


@dataclass
class PluginCliCommand:
    """A ``clite <name>`` subcommand contributed by a plugin."""

    name: str
    help: str
    setup: Callable[[Any], None] | None  # setup(parser): add arguments
    handler: Callable[[Any], int | None]  # handler(args) -> exit code
    plugin: str = ""


@dataclass
class Registration:
    kind: str
    name: str
    undo: Callable[[], Any] = field(repr=False, default=lambda: None)


class PluginContext:
    def __init__(self, manifest: PluginManifest, plugin_dir: Path | None, manager: PluginManager) -> None:
        self.manifest = manifest
        self.plugin_id = manifest.name
        self.plugin_dir = plugin_dir
        self.home = get_home()
        self.logger = logging.getLogger(f"clite.plugin.{manifest.name}")
        self._manager = manager
        self.ledger: list[Registration] = []

    # ── configuration ────────────────────────────────────────────────────────────────────

    @property
    def settings(self) -> dict[str, Any]:
        """This plugin's settings: ``plugins.entries.<plugin id>.settings`` in config.yaml."""
        return dict(get_path(load_config(), f"plugins.entries.{self.plugin_id}.settings", {}) or {})

    def _entry(self, key: str, default: Any = None) -> Any:
        return get_path(load_config(), f"plugins.entries.{self.plugin_id}.{key}", default)

    def _record(self, kind: str, name: str, undo: Callable[[], Any]) -> None:
        self.ledger.append(Registration(kind, name, undo))

    # ── tools ────────────────────────────────────────────────────────────────────────────

    def register_tool(self, name: str, toolset: str, schema: dict[str, Any], handler: Callable[..., Any], **options: Any) -> None:
        """Add a tool the model can call. Replacing a built-in tool needs the user's explicit
        ``plugins.entries.<id>.allow_tool_override: true``."""
        from clite.tools.registry import registry

        override = bool(self._entry("allow_tool_override", False))
        displaced = registry.get(name)
        registry.register(name, toolset, schema, handler, origin=f"plugin:{self.plugin_id}", override=override, **options)

        def undo() -> None:
            registry.deregister(name)
            if displaced is not None:
                registry.restore(displaced)  # unloading an override brings the original back

        self._record("tool", name, undo)

    def register_toolset(self, name: str, description: str, tools: list[str] | None = None,
                         includes: list[str] | None = None) -> None:
        from clite.tools import toolsets

        previous = toolsets.TOOLSETS.get(name)
        toolsets.register_toolset(name, description, tools, includes)

        def undo() -> None:
            if previous is None:
                toolsets.TOOLSETS.pop(name, None)
            else:
                toolsets.TOOLSETS[name] = previous

        self._record("toolset", name, undo)

    def register_environment(self, name: str, factory: Callable[..., Any]) -> None:
        """Add a terminal backend selectable with ``terminal.backend: <name>``."""
        from clite.tools import environments

        environments.register_environment_backend(name, factory)
        self._record("environment", name, lambda: environments._BACKENDS.pop(name, None))

    # ── hooks and prompt ─────────────────────────────────────────────────────────────────

    def register_hook(self, name: str, callback: Callable[..., Any]) -> None:
        bus = get_hook_bus()
        registration = bus.register(name, callback, plugin=self.plugin_id)
        self._record("hook", name, lambda: bus.unregister(registration))

    def register_prompt_section(self, section_id: str, content: str | Callable[[], str]) -> None:
        """Add a block to the system prompt. Rendered once per session; keep it short."""
        bus = get_hook_bus()
        key = f"{self.plugin_id}:{section_id}"
        bus.register_prompt_section(key, content, plugin=self.plugin_id)
        self._record("prompt_section", key, lambda: bus._sections.pop(key, None))

    # ── commands ─────────────────────────────────────────────────────────────────────────

    def register_command(self, name: str, handler: Callable[..., Any], description: str = "", args_hint: str = "") -> None:
        """Add a slash command, available on every surface."""
        command = PluginCommand(name.lstrip("/").lower(), handler, description, args_hint, self.plugin_id)
        self._manager.commands[command.name] = command
        self._record("command", command.name, lambda: self._manager.commands.pop(command.name, None))

    def register_cli_command(self, name: str, help: str, handler: Callable[[Any], int | None],  # noqa: A002
                             setup: Callable[[Any], None] | None = None) -> None:
        """Add a ``clite <name>`` subcommand."""
        command = PluginCliCommand(name, help, setup, handler, self.plugin_id)
        self._manager.cli_commands[name] = command
        self._record("cli_command", name, lambda: self._manager.cli_commands.pop(name, None))

    # ── pluggable backends ───────────────────────────────────────────────────────────────

    def register_provider(self, profile: Any) -> None:
        """Add or replace a model provider."""
        from clite.providers import registry as provider_registry

        provider_registry.register_provider(profile)
        self._record("provider", profile.name, lambda: provider_registry._BASE.pop(profile.name, None))

    def register_transport(self, transport: Any) -> None:
        """Add a wire protocol (a new ``api_mode``)."""
        from clite.providers.transports import base

        base.register_transport(transport)
        self._record("transport", transport.api_mode, lambda: base._TRANSPORTS.pop(transport.api_mode, None))

    def register_memory_provider(self, name: str, factory: Callable[[], Any]) -> None:
        from clite.agent.memory import manager as memory_manager

        memory_manager.register_memory_provider(name, factory)
        self._record("memory_provider", name, lambda: memory_manager._PROVIDER_FACTORIES.pop(name, None))

    def register_context_engine(self, name: str, factory: Callable[[], Any]) -> None:
        from clite.agent.context import engine

        engine.register_context_engine(name, factory)
        self._record("context_engine", name, lambda: engine._ENGINES.pop(name, None))

    def register_platform(self, name: str, factory: Callable[..., Any]) -> None:
        """Add a gateway platform adapter. ``factory(config, runner)`` returns the adapter."""
        from clite.gateway.platforms import base

        base.register_platform(name, factory)
        self._record("platform", name, lambda: base.PLATFORMS.pop(name, None))

    def register_skills_dir(self, path: str | Path) -> None:
        """Expose a directory of skills that ship with this plugin (read-only tier)."""
        from clite.skills import catalog

        directory = Path(path)
        if not directory.is_absolute() and self.plugin_dir is not None:
            directory = self.plugin_dir / directory
        catalog.register_extra_root(directory)
        self._record("skills_dir", str(directory), lambda: catalog.unregister_extra_root(directory))

    def register_skill_source(self, source: Any) -> None:
        """Add a place ``clite skills install`` can fetch from."""
        from clite.skills import hub

        hub.register_skill_source(source)
        self._record("skill_source", source.source_id, lambda: hub.SOURCES.pop(source.source_id, None))
