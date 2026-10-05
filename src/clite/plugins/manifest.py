"""``plugin.yaml``: what a plugin says about itself before any of its code runs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KIND_STANDALONE = "standalone"  # hooks and tools; opt-in
KIND_BACKEND = "backend"  # one implementation of a pluggable capability (memory, context engine, ...)
KIND_EXCLUSIVE = "exclusive"  # at most one of its category active at a time
KIND_PLATFORM = "platform"  # a gateway adapter
KIND_MODEL_PROVIDER = "model-provider"  # an inference provider profile
KINDS = (KIND_STANDALONE, KIND_BACKEND, KIND_EXCLUSIVE, KIND_PLATFORM, KIND_MODEL_PROVIDER)
SUPPORTED_MANIFEST_VERSION = 1
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ManifestError(ValueError):
    """The manifest is missing, unreadable or invalid."""


@dataclass
class PluginManifest:
    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    kind: str = KIND_STANDALONE
    manifest_version: int = SUPPORTED_MANIFEST_VERSION
    requires_env: tuple[str, ...] = ()
    provides_tools: tuple[str, ...] = ()
    provides_hooks: tuple[str, ...] = ()
    pip_dependencies: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def parse_manifest(data: Any, *, fallback_name: str = "") -> PluginManifest:
    if not isinstance(data, dict):
        raise ManifestError("plugin.yaml must be a mapping")
    name = str(data.get("name") or fallback_name).strip()
    if not _NAME_RE.match(name):
        raise ManifestError(f"invalid plugin name {name!r}: use lowercase letters, digits, hyphens and underscores")
    kind = str(data.get("kind") or KIND_STANDALONE)
    if kind not in KINDS:
        raise ManifestError(f"unknown plugin kind {kind!r}; valid kinds: {', '.join(KINDS)}")
    try:
        manifest_version = int(data.get("manifest_version") or SUPPORTED_MANIFEST_VERSION)
    except (TypeError, ValueError):
        raise ManifestError("manifest_version must be an integer") from None
    if manifest_version > SUPPORTED_MANIFEST_VERSION:
        raise ManifestError(
            f"plugin {name!r} needs manifest version {manifest_version}; this release supports "
            f"{SUPPORTED_MANIFEST_VERSION}. Upgrade the agent to use it."
        )
    return PluginManifest(
        name=name,
        version=str(data.get("version") or "0.0.0"),
        description=str(data.get("description") or ""),
        author=str(data.get("author") or ""),
        kind=kind,
        manifest_version=manifest_version,
        requires_env=_strings(data.get("requires_env")),
        provides_tools=_strings(data.get("provides_tools")),
        provides_hooks=_strings(data.get("provides_hooks")),
        pip_dependencies=_strings(data.get("pip_dependencies")),
        raw=data,
    )


def load_manifest(plugin_dir: Path) -> PluginManifest:
    path = plugin_dir / "plugin.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path} is not valid YAML: {exc}") from exc
    return parse_manifest(data, fallback_name=plugin_dir.name)
