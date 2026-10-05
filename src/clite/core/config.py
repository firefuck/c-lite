"""Configuration: ``config.yaml`` holds settings, ``.env`` holds secrets.

Readers:

* :func:`load_config` returns the user file deep-merged over :data:`DEFAULT_CONFIG`. Use it
  everywhere a default should apply.
* :func:`load_user_config_raw` returns only what the user wrote. Use it for presence-sensitive
  checks and for write-back round trips.

Writers: every write goes through :func:`config_set`, :func:`config_unset` or
:func:`atomic_config_update`. Nothing else may dump YAML onto the config path.

Known limitation: the writer re-serialises with PyYAML, so comments in a hand-edited file are
lost on the first programmatic write (key order is kept). Hermes solves this with a ruamel
round-trip behind the same seam; see roadmap task F1-T6.
"""

from __future__ import annotations

import copy
import os
import re
import threading
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

import yaml

from clite.core.config_defaults import CONFIG_VERSION, DEFAULT_CONFIG
from clite.core.constants import get_config_path, home_key
from clite.core.errors import ConfigError
from clite.core.io import atomic_write_text

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_CACHE: dict[str, tuple[tuple[int, int] | None, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()

# version N -> function that upgrades a raw user config from N to N+1.
MIGRATIONS: dict[int, Callable[[MutableMapping[str, Any]], None]] = {}


# ── helpers ──────────────────────────────────────────────────────────────────────────────


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """``override`` laid over ``base``; nested mappings merge, everything else replaces."""
    merged: dict[str, Any] = {key: copy.deepcopy(value) for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def get_path(config: Mapping[str, Any], dotpath: str, default: Any = None) -> Any:
    """Value at ``a.b.c`` or ``default`` when any segment is missing."""
    node: Any = config
    for part in dotpath.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def _expand_env(value: Any) -> Any:
    """Replace ``${VAR}`` in strings with the environment value; unknown names are left as-is."""
    if isinstance(value, str):
        return _ENV_REF.sub(lambda match: os.environ.get(match.group(1), match.group(0)), value)
    if isinstance(value, Mapping):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _normalize(raw: MutableMapping[str, Any]) -> None:
    """Accept the short ``model: "name"`` form by lifting it into ``model.default``."""
    model = raw.get("model")
    if isinstance(model, str):
        raw["model"] = {"default": model}


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


# ── readers ──────────────────────────────────────────────────────────────────────────────


def load_user_config_raw(path: Path | None = None) -> dict[str, Any]:
    """The user's file as written, without defaults. ``{}`` when the file does not exist.

    An unreadable or malformed file raises :class:`ConfigError`. It is never treated as
    empty: a writer that did so would replace the user's settings with defaults.
    """
    target = path or get_config_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {target}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{target} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{target} must contain a mapping at the top level")
    return data


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Effective configuration: defaults, user file, migrations, ``${VAR}`` expansion.

    The result is cached per home against the file's mtime and size, and every caller gets
    its own copy, so mutating the returned dict never leaks into another caller.
    """
    target = path or get_config_path()
    key = home_key(target.parent) + "|" + target.name
    signature = _signature(target)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return copy.deepcopy(cached[1])
    raw = load_user_config_raw(target)
    _normalize(raw)
    _apply_migrations(raw)
    effective = _expand_env(deep_merge(DEFAULT_CONFIG, raw))
    effective["_config_version"] = CONFIG_VERSION
    with _CACHE_LOCK:
        _CACHE[key] = (signature, effective)
    return copy.deepcopy(effective)


def config_get(dotpath: str, default: Any = None) -> Any:
    return get_path(load_config(), dotpath, default)


def reset_config_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _apply_migrations(raw: MutableMapping[str, Any]) -> bool:
    """Upgrade ``raw`` in place to :data:`CONFIG_VERSION`. Returns True if anything ran."""
    version = raw.get("_config_version")
    if not isinstance(version, int):
        return False
    ran = False
    while version < CONFIG_VERSION and version in MIGRATIONS:
        MIGRATIONS[version](raw)
        version += 1
        raw["_config_version"] = version
        ran = True
    return ran


# ── writers ──────────────────────────────────────────────────────────────────────────────


def _load_for_write(target: Path) -> dict[str, Any]:
    """The user file for a write-back. Fails closed on an unreadable file: saving over a file
    we could not parse would replace the user's settings with whatever we happened to hold."""
    return load_user_config_raw(target)


def atomic_config_update(mutate: Callable[[dict[str, Any]], None], path: Path | None = None) -> None:
    """The one writer seam: load the user file, apply ``mutate``, write atomically."""
    target = path or get_config_path()
    document = _load_for_write(target)
    mutate(document)
    if "_config_version" not in document:
        document["_config_version"] = CONFIG_VERSION
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)
    atomic_write_text(target, text)
    reset_config_cache()


def _descend(document: MutableMapping[str, Any], parts: list[str], *, create: bool) -> MutableMapping[str, Any] | None:
    node: Any = document
    for part in parts:
        child = node.get(part) if isinstance(node, Mapping) else None
        if not isinstance(child, MutableMapping):
            if not create:
                return None
            child = {}
            node[part] = child
        node = child
    return node


def config_set(dotpath: str, value: Any, path: Path | None = None) -> None:
    """Set ``a.b.c`` to ``value``, creating intermediate mappings."""
    parts = dotpath.split(".")
    if not all(parts):
        raise ConfigError(f"invalid config key: {dotpath!r}")

    def mutate(document: MutableMapping[str, Any]) -> None:
        parent = _descend(document, parts[:-1], create=True)
        assert parent is not None  # create=True always yields a mapping
        parent[parts[-1]] = value

    atomic_config_update(mutate, path)


def config_unset(dotpath: str, path: Path | None = None) -> bool:
    """Remove ``a.b.c`` from the user file. Returns False when it was not set."""
    parts = dotpath.split(".")
    removed = False

    def mutate(document: MutableMapping[str, Any]) -> None:
        nonlocal removed
        parent = _descend(document, parts[:-1], create=False)
        if parent is not None and parts[-1] in parent:
            del parent[parts[-1]]
            removed = True

    atomic_config_update(mutate, path)
    return removed


def migrate_config_file(path: Path | None = None) -> bool:
    """Persist pending migrations to the user file. Returns True when the file was rewritten."""
    raw = load_user_config_raw(path)
    version = raw.get("_config_version")
    if not isinstance(version, int) or version >= CONFIG_VERSION:
        return False

    def mutate(document: MutableMapping[str, Any]) -> None:
        _apply_migrations(document)

    atomic_config_update(mutate, path)
    return True


def parse_cli_value(text: str) -> Any:
    """Turn ``clite config set`` input into a typed value (``true``, ``3``, ``[a, b]``, ...)."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_CONFIG",
    "MIGRATIONS",
    "atomic_config_update",
    "config_get",
    "config_set",
    "config_unset",
    "deep_merge",
    "get_path",
    "load_config",
    "load_user_config_raw",
    "migrate_config_file",
    "parse_cli_value",
    "reset_config_cache",
]
