"""Execution environments: where the ``terminal`` tool actually runs a command.

``local`` runs on the host. Other backends (docker, ssh, ...) implement the same methods and
register a factory with :func:`register_environment_backend`, so the terminal tool, the file
tools and the approval gate work unchanged on all of them.

An environment owns one working context for a session: a current directory that persists
between commands, and a workspace the file tools read and write. Beyond running commands it
offers four file operations (``read_file``, ``write_file``, ``list_dir``, ``stat``), so
``read_file``, ``write_file``, ``patch`` and ``search_files`` reach their data through the
active backend instead of assuming the host filesystem. ``LocalEnvironment`` implements them
with plain ``pathlib``; a backend that keeps its workspace inside a container or on another
machine overrides them with a listing/exec translation of the same calls.
"""

from __future__ import annotations

import subprocess
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


@dataclass
class FileRead:
    """What a file read returns.

    ``content`` is the exact bytes decoded as UTF-8 (``errors="replace"``); ``size`` is the
    byte length, kept separately because ``len(content)`` is characters. ``binary=True`` marks
    content that held a NUL byte in its first block; the caller decides what to do with it but
    a text tool refuses it.
    """

    content: str
    size: int = 0
    binary: bool = False


@dataclass
class DirEntry:
    name: str
    is_dir: bool
    is_file: bool
    size: int = 0


@dataclass
class FileInfo:
    exists: bool = False
    is_dir: bool = False
    is_file: bool = False
    size: int = 0


class BaseEnvironment(ABC):
    """One working context: a current directory that persists between commands.

    File operations default to the local filesystem so a backend that only adds remote
    *command* execution (and mounts its workspace, like Docker and SSH do) inherits them. A
    backend that keeps the workspace somewhere the host cannot see overrides them.
    """

    name = "base"
    # Kept so callers can tell that the environment does not edit file bytes itself: its
    # file tools apply changes through the host temp-file swap even on a mounted workspace.
    os_name: str = "posix"

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

    def read_file(self, path: str, *, max_bytes: int | None = None) -> FileRead:
        """Read ``path`` as text. Empty content and ``exists`` in the caller's ``stat`` mark a
        missing file; a backend that cannot reach it fills ``binary=True`` instead of guessing."""
        raise NotImplementedError

    def write_file(self, path: str, content: str) -> None:
        """Create or replace ``path`` with ``content``. Parent directories are created."""
        raise NotImplementedError

    def list_dir(self, path: str) -> list[DirEntry]:
        """Direct children of the directory ``path`` (names only, sorted by the caller)."""
        raise NotImplementedError

    def stat(self, path: str) -> FileInfo:
        """Whether ``path`` exists and what it is."""
        raise NotImplementedError

    def spawn_background(self, command: str, *, cwd: str) -> subprocess.Popen[str]:
        """Start ``command`` without waiting and return its process.

        The ``process`` tool polls, waits on and kills it, writes to its ``stdin`` and reads its
        text ``stdout``. A backend that cannot keep a process alive across calls raises
        ``NotImplementedError``; the caller reports that to the model.
        """
        raise NotImplementedError

    def cleanup(self) -> None:
        """Release anything the environment holds (containers, connections)."""
