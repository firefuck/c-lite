"""SSH execution: one connection per ``task_id`` to a host named in config.

Commands run on the remote host over the system ``ssh`` binary (no extra dependency), reusing
ControlMaster so the whole session shares one authenticated connection. File operations for
the file tools run over the same connection with POSIX tools (``cat``, ``tee``, ``ls``,
``stat``, ``mkdir``): the file tools still decide *what* to read and write and how to validate
it, and this backend only transports the bytes.

Config:

* ``terminal.ssh.host``      — user@host, or a Host alias from ``~/.ssh/config`` (required)
* ``terminal.ssh.port``      — port (default 22, or the alias's own)
* ``terminal.ssh.key``       — private key path (empty = the agent's usual ssh agent/config)
* ``terminal.ssh.known_hosts`` — known_hosts file (empty = the user's default)
* ``terminal.ssh.cwd``       — remote working directory (default: the login directory)

The key path is a *path*, not a secret, and is passed to ssh as ``-i``. Like Docker, nothing
from ``.env`` or a provider key is forwarded: ``SendEnv`` is never set.
"""

from __future__ import annotations

import base64
import os
import shlex
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import PurePosixPath

from clite.core.config import config_get
from clite.core.threads import start_thread
from clite.tools.environments.base import BaseEnvironment, DirEntry, ExecResult, FileInfo, FileRead
from clite.tools.environments.local import _POLL_SECONDS, read_output_chunks

_READ_BLOCK = 1_000_000
_LIST_MARKER = "clite-ls-entry"


class SSHEnvironment(BaseEnvironment):
    """Run commands and file operations on a remote host over one ssh connection."""

    name = "ssh"

    def __init__(self, cwd: str = "", *, timeout: int = 180) -> None:
        host = str(config_get("terminal.ssh.host", "") or "").strip()
        if not host:
            raise ValueError(
                "terminal.ssh.host is empty; set it in config.yaml (e.g. `terminal.ssh.host: me@build-box`) "
                "to use the SSH backend"
            )
        configured_cwd = str(config_get("terminal.ssh.cwd", "") or "")
        super().__init__(cwd or configured_cwd or ".", timeout=timeout)
        self._host = host
        self._control_path = os.path.join(self._control_dir(), f"conn-{uuid.uuid4().hex[:10]}")
        self._connected = False

    # ── connection ───────────────────────────────────────────────────────────────────────

    @staticmethod
    def _control_dir() -> str:
        from clite.core.constants import get_home

        directory = str(get_home() / "ssh")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _ssh_base(self) -> list[str]:
        ssh = shutil.which("ssh") or "ssh"
        argv = [ssh, "-o", "BatchMode=yes", "-o", "ControlMaster=auto",
                "-o", f"ControlPath={self._control_path}", "-o", "ControlPersist=600"]
        port = str(config_get("terminal.ssh.port", "") or "")
        if port and port != "22":
            argv += ["-p", port]
        key = str(config_get("terminal.ssh.key", "") or "")
        if key:
            argv += ["-i", os.path.expanduser(key)]
        known_hosts = str(config_get("terminal.ssh.known_hosts", "") or "")
        if known_hosts:
            argv += ["-o", f"UserKnownHostsFile={os.path.expanduser(known_hosts)}"]
        return argv

    def _run_ssh(self, remote_command: str, *, timeout: int = 60, stdin_data: str | bytes | None = None) -> ExecResult:
        import subprocess

        argv = [*self._ssh_base(), "--", self._host, remote_command]
        data = stdin_data.encode("utf-8") if isinstance(stdin_data, str) else stdin_data
        try:
            completed = subprocess.run(  # noqa: S603 - reaching the configured host is this backend's job
                argv, input=data, capture_output=True, timeout=timeout, check=False,
            )
        except FileNotFoundError:
            return ExecResult("ssh is not installed or not on PATH", 127)
        except subprocess.TimeoutExpired:
            return ExecResult(f"ssh command timed out after {timeout}s", 124, timed_out=True)
        output = completed.stdout.decode("utf-8", errors="replace") + completed.stderr.decode("utf-8", errors="replace")
        return ExecResult(output, completed.returncode)

    def _start(self) -> None:
        if self._connected:
            return
        probe = self._run_ssh("true", timeout=30)
        if probe.exit_code != 0:
            raise RuntimeError(f"could not connect to {self._host}: {probe.output.strip()}")
        self._connected = True

    def cleanup(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._run_ssh("-O exit", timeout=10)  # `ssh -O exit host` closes the shared master

    # ── file operations ──────────────────────────────────────────────────────────────────

    def resolve_path(self, path: str) -> str:
        expanded = os.path.expanduser(path)
        return expanded if expanded.startswith("/") else str(PurePosixPath(self.cwd) / expanded)

    def read_file(self, path: str, *, max_bytes: int | None = None) -> FileRead:
        info = self.stat(path)
        probe = self.execute(f"head -c 4096 {shlex.quote(path)} | cat", timeout=30)
        binary = "\x00" in probe.output
        if binary:
            return FileRead("", size=info.size, binary=True)
        command = f"base64 {shlex.quote(path)}"
        if max_bytes is not None:
            command = f"head -c {int(max_bytes * 4 // 3 + 8)} {shlex.quote(path)} | base64"
        result = self.execute(command, timeout=60)
        if result.exit_code != 0:
            raise OSError(result.output.strip() or f"could not read {path}")
        raw = base64.b64decode("".join(result.output.split()), validate=False)
        if max_bytes is not None:
            raw = raw[:max_bytes]
        return FileRead(raw.decode("utf-8", errors="replace"), size=info.size, binary=False)

    def write_file(self, path: str, content: str) -> None:
        parent = str(PurePosixPath(path).parent)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        # Written through a temp file in the same directory, then moved into place: a partial
        # transfer must never replace a good file, matching the local atomic write.
        script = (
            f"mkdir -p {shlex.quote(parent)} && "
            f"tmp=$(mktemp {shlex.quote(parent)}/clite-write-XXXXXX) && "
            f"base64 -d > \"$tmp\" && mv -f \"$tmp\" {shlex.quote(path)}"
        )
        result = self._run_ssh(script, timeout=120, stdin_data=encoded)
        if result.exit_code != 0:
            raise OSError(result.output.strip() or f"could not write {path}")

    def list_dir(self, path: str) -> list[DirEntry]:
        script = (
            f"cd {shlex.quote(path)} && for f in * .[!.]*; do "
            f"[ -e \"$f\" ] || continue; "
            f"if [ -d \"$f\" ]; then printf '{_LIST_MARKER}\\td\\t%s\\t0\\n' \"$f\"; "
            f"else printf '{_LIST_MARKER}\\tf\\t%s\\t%s\\n' \"$f\" \"$(wc -c < \"$f\" 2>/dev/null || echo 0)\"; fi; done"
        )
        result = self.execute(script, timeout=60)
        if result.exit_code != 0:
            raise OSError(result.output.strip() or f"could not list {path}")
        entries: list[DirEntry] = []
        for line in result.output.splitlines():
            if not line.startswith(_LIST_MARKER):
                continue
            _, kind, name, size = line.split("\t", 3)
            is_dir = kind == "d"
            try:
                byte_size = int(size)
            except ValueError:
                byte_size = 0
            entries.append(DirEntry(name, is_dir, not is_dir, byte_size))
        return entries

    def stat(self, path: str) -> FileInfo:
        quoted = shlex.quote(path)
        script = (
            f"if [ -d {quoted} ]; then echo dir; "
            f"elif [ -f {quoted} ]; then echo file; echo \"$(wc -c < {quoted} 2>/dev/null)\"; "
            f"elif [ -e {quoted} ]; then echo other; else echo missing; fi"
        )
        result = self.execute(script, timeout=30)
        lines = result.output.splitlines()
        kind = lines[0] if lines else "missing"
        if kind == "missing":
            return FileInfo()
        if kind == "dir":
            return FileInfo(exists=True, is_dir=True)
        size = 0
        if len(lines) > 1:
            try:
                size = int(lines[1].strip() or 0)
            except ValueError:
                size = 0
        return FileInfo(exists=True, is_file=(kind == "file"), size=size)

    # ── command execution ────────────────────────────────────────────────────────────────

    def spawn_background(self, command: str, *, cwd: str) -> object:
        """Run the command over a dedicated ssh connection kept open, so ``process`` can read
        its output, feed stdin and kill it. The client process dying ends the remote command."""
        import subprocess

        self._start()
        workdir = self.resolve_path(cwd)
        remote = f"cd {shlex.quote(workdir)} 2>/dev/null; {command}"
        # A fresh non-multiplexed connection: a shared master would mix this stream with the
        # session's foreground commands.
        argv = [shutil.which("ssh") or "ssh", "-o", "BatchMode=yes", "-o", "ControlMaster=no"]
        port = str(config_get("terminal.ssh.port", "") or "")
        if port and port != "22":
            argv += ["-p", port]
        key = str(config_get("terminal.ssh.key", "") or "")
        if key:
            argv += ["-i", os.path.expanduser(key)]
        argv += ["--", self._host, remote]
        return subprocess.Popen(  # noqa: S603
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )

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
        import subprocess

        try:
            self._start()
        except RuntimeError as exc:
            return ExecResult(str(exc), 126)
        workdir = self.resolve_path(cwd) if cwd else self.cwd
        limit = 50_000 if max_output_chars is None else max(0, max_output_chars)
        deadline = time.monotonic() + (timeout or self.default_timeout)
        remote = f"cd {shlex.quote(workdir)} 2>/dev/null; {command}"

        try:
            process = subprocess.Popen(  # noqa: S603
                [*self._ssh_base(), "--", self._host, remote],
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            return ExecResult(f"could not run ssh: {exc}", 126)

        chunks: list[str] = []
        size = 0
        truncated = False

        def collect() -> None:
            nonlocal size, truncated
            assert process.stdout is not None
            for chunk in read_output_chunks(process.stdout):
                if on_output is not None:
                    try:
                        on_output(chunk)
                    except Exception:  # noqa: BLE001
                        pass
                retained = chunk[: max(0, limit - size)]
                if retained:
                    chunks.append(retained)
                    size += len(retained)
                if len(retained) < len(chunk):
                    truncated = True

        reader_thread = start_thread(collect, name="clite-ssh-reader")
        if stdin_data is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin_data)
                process.stdin.close()
            except OSError:
                pass
        timed_out = interrupted = False
        while process.poll() is None:
            if interrupt is not None and interrupt.is_set():
                interrupted = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            time.sleep(_POLL_SECONDS)
        if timed_out or interrupted:
            process.kill()
            try:
                process.wait(2.0)
            except subprocess.TimeoutExpired:
                pass
        reader_thread.join(timeout=2.0)

        output = "".join(chunks)
        if truncated:
            output += f"\n[output truncated at {limit} characters]"
        exit_code = process.returncode if process.returncode is not None else -1
        if timed_out:
            output += f"\n[command timed out after {timeout or self.default_timeout}s and was killed]"
            exit_code = 124
        elif interrupted:
            output += "\n[command interrupted]"
            exit_code = 130
        return ExecResult(output, exit_code, timed_out, interrupted, truncated)


def ssh_factory(*, cwd: str = "", timeout: int = 180) -> SSHEnvironment:
    return SSHEnvironment(cwd=cwd, timeout=timeout)
