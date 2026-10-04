"""Execution environments: where the ``terminal`` tool actually runs a command.

``local`` runs on the host. Other backends (docker, ssh, ...) implement the same three
methods and register a factory with :func:`register_environment_backend`, so the terminal
tool, the file tools and the approval gate work unchanged on all of them.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ExecResult:
    output: str
    exit_code: int
    timed_out: bool = False
    interrupted: bool = False
    truncated: bool = False


class BaseEnvironment(ABC):
    """One working context: a current directory that persists between commands."""

    name = "base"

    def __init__(self, cwd: str = "", *, timeout: int = 180) -> None:
        self.cwd = cwd
        self.default_timeout = timeout

    @abstractmethod
    def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        stdin_data: str | None = None,
        interrupt: threading.Event | None = None,
        on_output: Callable[[str], None] | None = None,
        max_output_chars: int | None = None,
    ) -> ExecResult:
        """Run ``command`` to completion and return its merged stdout and stderr."""

    def resolve_path(self, path: str) -> str:
        """Absolute form of ``path`` as the file tools should see it (relative to ``cwd``)."""
        return path

    def cleanup(self) -> None:
        """Release anything the environment holds (containers, connections)."""
