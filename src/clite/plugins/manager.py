"""Plugin discovery and loading.

Sources, in the order they are scanned (a later source replaces an earlier plugin of the
same name):

1. bundled   ``<package>/bundled/plugins/<name>/``
2. user      ``<home>/plugins/<name>/``
3. project   ``./.clite/plugins/<name>/``  (only with ``CLITE_ENABLE_PROJECT_PLUGINS=1``)
4. pip       packages declaring the ``clite.plugins`` entry-point group

Loading is opt-in: a plugin runs only when it is listed in ``plugins.enabled``, and
``plugins.disabled`` always wins. The exception is bundled plugins that only add an inert
capability (a platform adapter or a backend that does nothing until configured).

``model-providers/`` directories are not plugins in this sense; the provider registry loads
them itself (see ``clite.providers.registry``).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clite.core.brand import ENTRY_POINT_GROUP, ENV_PREFIX, PLUGIN_NAMESPACE, PROJECT_DIRNAME
from clite.core.config import atomic_config_update, get_path, load_config
from clite.core.constants import bundled_dir, ensure_dir, get_plugins_dir, home_key
from clite.core.env import get_secret
from clite.plugins.context import PluginCliCommand, PluginCommand, PluginContext
from clite.plugins.hooks import get_hook_bus
from clite.plugins.manifest import (
    KIND_BACKEND,
    KIND_MODEL_PROVIDER,
    KIND_PLATFORM,
    ManifestError,
    PluginManifest,
    load_manifest,
)

logger = logging.getLogger("clite.plugins")

SOURCE_BUNDLED, SOURCE_USER, SOURCE_PROJECT, SOURCE_PIP = "bundled", "user", "project", "pip"
_RESERVED_DIRS = frozenset({"model-providers"})
_AUTO_LOAD_KINDS = frozenset({KIND_PLATFORM, KIND_BACKEND, KIND_MODEL_PROVIDER})
PROJECT_PLUGINS_ENV = f"{ENV_PREFIX}_ENABLE_PROJECT_PLUGINS"


@dataclass
class PluginInfo:
    manifest: PluginManifest
    source: str
    path: Path | None = None
    entry_point: Any = None
    status: str = "not_enabled"  # loaded | not_enabled | disabled | error
    error: str = ""
    context: PluginContext | None = None

    @property
    def name(self) -> str:
        return self.manifest.name

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.manifest.version, "description": self.manifest.description,
            "kind": self.manifest.kind, "source": self.source, "status": self.status, "error": self.error,
            "path": str(self.path) if self.path else "",
        }


class PluginManager:
    def __init__(self) -> None:
        self.plugins: dict[str, PluginInfo] = {}
        self.commands: dict[str, PluginCommand] = {}
        self.cli_commands: dict[str, PluginCliCommand] = {}
        self._lock = threading.RLock()
        self._loaded = False

    # ── discovery ────────────────────────────────────────────────────────────────────────

    def _scan_directory(self, root: Path, source: str) -> None:
        if not root.is_dir():
            return
        for plugin_dir in sorted(root.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith((".", "_")) or plugin_dir.name in _RESERVED_DIRS:
                continue
            if not (plugin_dir / "plugin.yaml").is_file():
                continue
            try:
                manifest = load_manifest(plugin_dir)
            except ManifestError as exc:
                logger.warning("skipping plugin at %s: %s", plugin_dir, exc)
                continue
            self.plugins[manifest.name] = PluginInfo(manifest, source, plugin_dir)

    def _scan_entry_points(self) -> None:
        try:
            entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
        except Exception:  # noqa: BLE001 - broken package metadata must not stop startup
            logger.debug("could not read entry points", exc_info=True)
            return
        for entry_point in entry_points:
            manifest = PluginManifest(name=entry_point.name.lower().replace(".", "-"),
                                      description=f"Installed package ({entry_point.value})")
            self.plugins[manifest.name] = PluginInfo(manifest, SOURCE_PIP, entry_point=entry_point)

    def discover(self) -> dict[str, PluginInfo]:
        with self._lock:
            loaded = {name: info for name, info in self.plugins.items() if info.status == "loaded"}
            self.plugins = {}
            self._scan_directory(bundled_dir() / "plugins", SOURCE_BUNDLED)
            self._scan_directory(get_plugins_dir(), SOURCE_USER)
            if os.environ.get(PROJECT_PLUGINS_ENV, "").lower() in ("1", "true", "yes"):
                self._scan_directory(Path.cwd() / PROJECT_DIRNAME / "plugins", SOURCE_PROJECT)
            self._scan_entry_points()
            self.plugins.update(loaded)  # a plugin that is running stays as it was loaded
            return self.plugins

    # ── gating ───────────────────────────────────────────────────────────────────────────

    def _gate(self, info: PluginInfo, config: dict[str, Any]) -> str:
        enabled = set(get_path(config, "plugins.enabled", []) or [])
        disabled = set(get_path(config, "plugins.disabled", []) or [])
        if info.name in disabled:
            return "disabled"
        if info.name in enabled:
            return "load"
        if info.source == SOURCE_BUNDLED and info.manifest.kind in _AUTO_LOAD_KINDS:
            return "load"
        return "not_enabled"

    # ── loading ──────────────────────────────────────────────────────────────────────────

    def _import(self, info: PluginInfo) -> Any:
        if info.entry_point is not None:
            return info.entry_point.load()
        assert info.path is not None
        _ensure_namespace()
        module_name = f"{PLUGIN_NAMESPACE}.{info.name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(
            module_name, info.path / "__init__.py", submodule_search_locations=[str(info.path)])
        if spec is None or spec.loader is None:
            raise ImportError(f"{info.path} has no __init__.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        return module

    def load(self, name: str) -> PluginInfo:
        with self._lock:
            info = self.plugins.get(name)
            if info is None:
                raise KeyError(f"no plugin named {name!r}")
            if info.status == "loaded":
                return info
            missing = [variable for variable in info.manifest.requires_env if not get_secret(variable)]
            if missing:
                info.status, info.error = "error", f"missing environment variable(s): {', '.join(missing)}"
                return info
            context = PluginContext(info.manifest, info.path, self)
            try:
                module = self._import(info)
                register = module if callable(module) else getattr(module, "register", None)
                if register is None:
                    raise AttributeError("plugin has no register(ctx) function")
                register(context)
            except Exception as exc:  # noqa: BLE001 - a broken plugin must not stop the agent
                logger.warning("plugin %s failed to load", name, exc_info=True)
                self._undo(context)
                info.status, info.error = "error", f"{type(exc).__name__}: {exc}"
                return info
            info.status, info.error, info.context = "loaded", "", context
            return info

    def _undo(self, context: PluginContext) -> None:
        for registration in reversed(context.ledger):
            try:
                registration.undo()
            except Exception:  # noqa: BLE001
                logger.debug("undo of %s %s failed", registration.kind, registration.name, exc_info=True)
        context.ledger.clear()
        get_hook_bus().unregister_plugin(context.plugin_id)

    def unload(self, name: str) -> bool:
        with self._lock:
            info = self.plugins.get(name)
            if info is None or info.context is None:
                return False
            self._undo(info.context)
            info.context = None
            info.status = "not_enabled"
            for module_name in [m for m in sys.modules if m.startswith(f"{PLUGIN_NAMESPACE}.{name.replace('-', '_')}")]:
                sys.modules.pop(module_name, None)
            return True

    def load_all(self, config: dict[str, Any] | None = None) -> None:
        """Discover, then load every plugin the config enables. Idempotent."""
        cfg = config if config is not None else load_config()
        with self._lock:
            self.discover()
            get_hook_bus().timeout = float(get_path(cfg, "plugins.hook_callback_timeout", 30) or 0) or None
            for name, info in list(self.plugins.items()):
                decision = self._gate(info, cfg)
                if decision == "load":
                    self.load(name)
                elif info.status == "loaded":
                    self.unload(name)
                    info.status = decision
                else:
                    info.status = decision
            self._loaded = True

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load_all()

    def list(self) -> list[PluginInfo]:
        return [self.plugins[name] for name in sorted(self.plugins)]


def _ensure_namespace() -> None:
    if PLUGIN_NAMESPACE not in sys.modules:
        namespace = types.ModuleType(PLUGIN_NAMESPACE)
        namespace.__path__ = []  # type: ignore[attr-defined]
        sys.modules[PLUGIN_NAMESPACE] = namespace


_MANAGERS: dict[str, PluginManager] = {}
_MANAGERS_LOCK = threading.Lock()


def get_plugin_manager() -> PluginManager:
    """The manager for the active home. Each profile enables its own set of plugins."""
    key = home_key()
    with _MANAGERS_LOCK:
        manager = _MANAGERS.get(key)
        if manager is None:
            manager = _MANAGERS[key] = PluginManager()
        return manager


def ensure_plugins_loaded() -> PluginManager:
    manager = get_plugin_manager()
    manager.ensure_loaded()
    return manager


def reset_plugin_managers() -> None:
    with _MANAGERS_LOCK:
        managers = list(_MANAGERS.values())
        _MANAGERS.clear()
    for manager in managers:
        for name in [info.name for info in manager.list() if info.status == "loaded"]:
            manager.unload(name)
    for module_name in [name for name in sys.modules if name == PLUGIN_NAMESPACE or
                        (name.startswith(f"{PLUGIN_NAMESPACE}.") and ".model_providers" not in name)]:
        sys.modules.pop(module_name, None)


# ── enable / disable / install ───────────────────────────────────────────────────────────


def set_plugin_enabled(name: str, enabled: bool) -> None:
    """Record the user's choice in config.yaml (``plugins.enabled`` / ``plugins.disabled``)."""

    def mutate(document: dict[str, Any]) -> None:
        section = document.setdefault("plugins", {})
        on = [item for item in section.get("enabled") or [] if item != name]
        off = [item for item in section.get("disabled") or [] if item != name]
        (on if enabled else off).append(name)
        section["enabled"], section["disabled"] = on, off

    atomic_config_update(mutate)


def install_plugin(source: str, *, force: bool = False) -> PluginInfo:
    """Copy a plugin directory, or clone a git URL, into ``<home>/plugins``.

    Installing does not enable: the user reads what was installed and then runs
    ``clite plugins enable <name>``.
    """
    plugins_dir = ensure_dir(get_plugins_dir())
    local = Path(source).expanduser()
    if local.is_dir():
        manifest = load_manifest(local)
        target = plugins_dir / manifest.name
        if target.exists():
            if not force:
                raise FileExistsError(f"plugin {manifest.name!r} is already installed; use --force to replace it")
            shutil.rmtree(target)
        shutil.copytree(local, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    elif source.startswith(("https://", "git@", "ssh://")) or source.endswith(".git"):
        staging = plugins_dir / ".staging"
        shutil.rmtree(staging, ignore_errors=True)
        result = subprocess.run(["git", "clone", "--depth", "1", source, str(staging)],  # noqa: S603, S607
                                capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()[:300]}")
        try:
            manifest = load_manifest(staging)
            target = plugins_dir / manifest.name
            if target.exists():
                if not force:
                    raise FileExistsError(f"plugin {manifest.name!r} is already installed; use --force to replace it")
                shutil.rmtree(target)
            shutil.rmtree(staging / ".git", ignore_errors=True)
            staging.rename(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    else:
        raise ValueError("a plugin source is a directory path or a git URL")
    return PluginInfo(manifest, SOURCE_USER, target)


def remove_plugin(name: str) -> bool:
    target = get_plugins_dir() / name
    if not (target / "plugin.yaml").is_file():
        return False
    get_plugin_manager().unload(name)
    shutil.rmtree(target)
    return True
