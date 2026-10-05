"""Environment registry: one execution environment per task, created on first use."""

from __future__ import annotations

import threading
from collections.abc import Callable

from clite.core.config import config_get
from clite.tools.environments.base import BaseEnvironment, ExecResult
from clite.tools.environments.local import LocalEnvironment

_BACKENDS: dict[str, Callable[..., BaseEnvironment]] = {"local": LocalEnvironment}
_ACTIVE: dict[str, BaseEnvironment] = {}
_LOCK = threading.Lock()


def register_environment_backend(name: str, factory: Callable[..., BaseEnvironment]) -> None:
    """Add a backend. ``factory(cwd=..., timeout=...)`` must return a ``BaseEnvironment``."""
    _BACKENDS[name] = factory


def environment_backends() -> list[str]:
    return sorted(_BACKENDS)


def get_environment(task_id: str = "", *, cwd: str = "") -> BaseEnvironment:
    """The environment for ``task_id``. All tools of one session share it, so ``cd`` in the
    terminal changes where ``read_file`` resolves relative paths."""
    key = task_id or "default"
    with _LOCK:
        environment = _ACTIVE.get(key)
        if environment is None:
            backend = str(config_get("terminal.backend", "local") or "local")
            factory = _BACKENDS.get(backend)
            if factory is None:
                raise ValueError(f"unknown terminal.backend {backend!r}; available: {environment_backends()}")
            start = cwd or str(config_get("terminal.cwd", "") or "")
            environment = factory(cwd=start, timeout=int(config_get("terminal.timeout", 180) or 180))
            _ACTIVE[key] = environment
        return environment


def cleanup_environment(task_id: str = "") -> None:
    with _LOCK:
        environment = _ACTIVE.pop(task_id or "default", None)
    if environment is not None:
        environment.cleanup()


def cleanup_all_environments() -> None:
    with _LOCK:
        environments = list(_ACTIVE.values())
        _ACTIVE.clear()
    for environment in environments:
        environment.cleanup()


__all__ = [
    "BaseEnvironment",
    "ExecResult",
    "LocalEnvironment",
    "cleanup_all_environments",
    "cleanup_environment",
    "environment_backends",
    "get_environment",
    "register_environment_backend",
]
