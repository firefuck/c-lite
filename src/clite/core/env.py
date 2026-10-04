"""Secrets: ``<home>/.env`` and nothing else.

``.env`` is for credentials only. Behavioural settings belong in ``config.yaml``.

Code reads a secret through :func:`get_secret`, never ``os.getenv``. One process may serve
several profiles, each with its own ``.env``; :func:`secret_scope` binds a profile's secrets
for the current activity so a second profile never sees the first one's keys.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from clite.core.constants import get_env_path, home_key
from clite.core.io import atomic_write_text

_SECRET_SCOPE: ContextVar[Mapping[str, str] | None] = ContextVar("clite_secret_scope", default=None)
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOCK = threading.Lock()
# Names loaded from each home's .env, so child processes can have them stripped.
_LOADED: dict[str, set[str]] = {}


@dataclass(frozen=True)
class SecretSpec:
    """A credential the setup flow knows how to ask for."""

    name: str
    description: str
    category: str = "provider"  # provider | tool | messaging
    url: str = ""


SECRET_REGISTRY: dict[str, SecretSpec] = {}


def register_secret(spec: SecretSpec) -> None:
    SECRET_REGISTRY[spec.name] = spec


def read_env_file(path: Path | None = None) -> dict[str, str]:
    """Parsed ``.env`` contents; ``{}`` when the file is missing."""
    target = path or get_env_path()
    if not target.is_file():
        return {}
    return {key: value for key, value in dotenv_values(target).items() if value is not None}


def load_env(path: Path | None = None, *, override: bool = True) -> list[str]:
    """Load ``.env`` into the process environment and return the names it defined.

    ``override=True`` because the profile's file is the source of truth for that profile: a
    stale ``export`` in the shell must not silently beat the key the user saved.
    """
    target = path or get_env_path()
    values = read_env_file(target)
    for name, value in values.items():
        if override or name not in os.environ:
            os.environ[name] = value
    with _LOCK:
        _LOADED.setdefault(home_key(target.parent), set()).update(values)
    return sorted(values)


def loaded_secret_names() -> set[str]:
    """Every name any loaded ``.env`` defined."""
    with _LOCK:
        return set().union(*_LOADED.values()) if _LOADED else set()


def secret_names() -> set[str]:
    """Every environment variable known to hold a credential.

    That is every name a loaded ``.env`` defined, plus every name a provider or a platform
    registered, whether its value came from ``.env`` or from the shell that started the
    process, plus the numbered variants a credential pool reads (``NAME_2`` to ``NAME_9``).
    Commands the agent runs get these stripped from their environment, and their values are
    redacted from what the model reads.
    """
    names = loaded_secret_names() | set(SECRET_REGISTRY)
    numbered = {f"{name}_{index}" for name in names for index in range(2, 10)}
    return names | {name for name in numbered if name in os.environ}


@contextmanager
def secret_scope(values: Mapping[str, str]) -> Iterator[None]:
    """Bind ``values`` as the secrets for the current context (one profile's activity)."""
    token = _SECRET_SCOPE.set(dict(values))
    try:
        yield
    finally:
        _SECRET_SCOPE.reset(token)


def get_secret(name: str, default: str | None = None) -> str | None:
    """A credential by name: the bound scope if any, else the process environment.

    With a scope bound, a miss returns ``default`` and never falls through to
    ``os.environ``. Falling through would hand one profile another profile's key.
    """
    scope = _SECRET_SCOPE.get()
    if scope is not None:
        value = scope.get(name)
        return value if value else default
    value = os.environ.get(name)
    return value if value else default


def save_secret(name: str, value: str, path: Path | None = None) -> None:
    """Write ``NAME=value`` into ``.env`` (mode 0600), replacing an existing line."""
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid environment variable name: {name!r}")
    if "\n" in value or "\r" in value:
        raise ValueError("secret values must be a single line")
    target = path or get_env_path()
    lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    rendered = f"{name}={_quote(value)}"
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(name)}\s*=")
    replaced = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = rendered
            replaced = True
    if not replaced:
        lines.append(rendered)
    atomic_write_text(target, "\n".join(lines) + "\n", mode=0o600)
    os.environ[name] = value
    with _LOCK:
        _LOADED.setdefault(home_key(target.parent), set()).add(name)


def remove_secret(name: str, path: Path | None = None) -> bool:
    """Delete ``name`` from ``.env``. Returns False when it was not there."""
    target = path or get_env_path()
    if not target.is_file():
        return False
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(name)}\s*=")
    lines = target.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not pattern.match(line)]
    if len(kept) == len(lines):
        return False
    atomic_write_text(target, "\n".join(kept) + ("\n" if kept else ""), mode=0o600)
    os.environ.pop(name, None)
    return True


def _quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@+=,-]*", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mask_secret(value: str | None) -> str:
    """A credential as it may be shown: first and last four characters only."""
    if not value:
        return "(not set)"
    return "****" if len(value) <= 10 else f"{value[:4]}…{value[-4:]}"
