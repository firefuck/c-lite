"""Local execution: a subprocess on the host, in its own process group."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from clite.core.config import config_get
from clite.core.env import secret_names
from clite.core.io import atomic_write_text
from clite.core.redact import credential_values
from clite.tools.environments.base import BaseEnvironment, DirEntry, ExecResult, FileInfo, FileRead
from clite.tools.environments.capture import capture

_KILL_GRACE_SECONDS = 2.0


def build_child_env(
    extra: dict[str, str] | None = None, passthrough: list[str] | None = None
) -> dict[str, str]:
    """Environment for a command the agent runs.

    Known credentials (``core.env.secret_names``: everything from ``.env``, and every provider
    and platform key even when it was exported in the shell) are removed unless the user listed
    them in ``terminal.env_passthrough``: an API key has no business in a build script's
    environment, and one ``env`` call would otherwise put every credential into the transcript.
    """
    allowed = set(
        passthrough if passthrough is not None else (config_get("terminal.env_passthrough", []) or [])
    )
    secrets = secret_names() - allowed
    cred_vals = credential_values()
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in secrets and (not cred_vals or value not in cred_vals)
    }
    env.setdefault("TERM", "dumb")
    env["PAGER"] = "cat"
    env["GIT_PAGER"] = "cat"
    if extra:
        for k, v in extra.items():
            if k not in secrets and (not cred_vals or v not in cred_vals):
                env[k] = v
    return env


def find_shell() -> list[str]:
    if sys.platform == "win32":
        # System32/bash.exe is a WSL launcher, not Git Bash. Do not pick it.
        candidates = [shutil.which("bash")]
        git = shutil.which("git")
        if git:
            candidates.append(str(Path(git).parent.parent / "bin" / "bash.exe"))
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(variable):
                candidates.append(str(Path(os.environ[variable]) / "Git" / "bin" / "bash.exe"))
        bash = next(
            (
                path
                for path in candidates
                if path
                and Path(path).is_file()
                and "system32" not in path.lower().replace("\\", "/").split("/")
            ),
            None,
        )
        return [bash, "-c"] if bash else [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"]
    return [shutil.which("bash") or "/bin/sh", "-c"]


def kill_process_tree(process: subprocess.Popen[str], *, force: bool = False) -> None:
    """Signal the whole process group so children of the shell die with it."""
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(  # noqa: S603 - the system's taskkill, no shell
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],  # noqa: S607 - the system's taskkill
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _stop_tree(process: subprocess.Popen[str]) -> None:
    """End a timed-out or interrupted command: ask the group to stop, then force it."""
    kill_process_tree(process)
    try:
        process.wait(_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        kill_process_tree(process, force=True)
        process.wait()


class LocalEnvironment(BaseEnvironment):
    name = "local"

    def __init__(self, cwd: str = "", *, timeout: int = 180) -> None:
        super().__init__(cwd or os.getcwd(), timeout=timeout)

    def resolve_path(self, path: str) -> str:
        expanded = Path(os.path.expanduser(path))
        return str(expanded if expanded.is_absolute() else Path(self.cwd) / expanded)

    # ── file operations ──────────────────────────────────────────────────────────────────
    # The host filesystem is the workspace, so these are plain reads and writes. They are the
    # reference behaviour the Docker and SSH backends mirror over their own transport.

    def read_file(self, path: str, *, max_bytes: int | None = None) -> FileRead:
        target = Path(path)
        size = target.stat().st_size
        with target.open("rb") as handle:
            raw = handle.read() if max_bytes is None else handle.read(max_bytes)
        return FileRead(raw.decode("utf-8", errors="replace"), size=size, binary=b"\x00" in raw[:4096])

    def write_file(self, path: str, content: str) -> None:
        atomic_write_text(path, content)

    def list_dir(self, path: str) -> list[DirEntry]:
        entries = []
        for child in Path(path).iterdir():
            entries.append(
                DirEntry(
                    child.name,
                    child.is_dir(),
                    child.is_file(),
                    child.stat().st_size if child.is_file() else 0,
                )
            )
        return entries

    def stat(self, path: str) -> FileInfo:
        target = Path(path)
        if not target.exists():
            return FileInfo()
        is_dir, is_file = target.is_dir(), target.is_file()
        return FileInfo(
            exists=True, is_dir=is_dir, is_file=is_file, size=target.stat().st_size if is_file else 0
        )

    def spawn_background(self, command: str, *, cwd: str) -> subprocess.Popen[str]:
        shell = find_shell()
        # list2cmdline quotes argv using CRT rules, which cmd.exe does not follow for /c.
        is_cmd = shell[0].replace("\\", "/").rsplit("/", 1)[-1].lower() in {"cmd", "cmd.exe"}
        argv = (
            subprocess.list2cmdline(shell) + " chcp 65001 >nul & " + command if is_cmd else [*shell, command]
        )
        return subprocess.Popen(  # noqa: S603 - running the model's command is this tool's job
            argv,
            cwd=cwd,
            env=build_child_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=sys.platform != "win32",
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
        workdir = self.resolve_path(cwd) if cwd else self.cwd
        if not os.path.isdir(workdir):
            return ExecResult(f"working directory does not exist: {workdir}", 1)
        shell = find_shell()
        track_cwd = cwd is None
        cwd_file = batch_file = None
        script = command
        is_cmd = Path(shell[0]).name.lower() in {"cmd", "cmd.exe"}
        if track_cwd:
            # Record where the command left the shell so a later call starts there: `cd src`
            # in one call and `ls` in the next behave like one terminal.
            handle, cwd_file = tempfile.mkstemp(prefix="clite-cwd-")
            os.close(handle)
            if not is_cmd:
                pwd = "pwd -W" if sys.platform == "win32" else "pwd -P"
                script = (
                    f"{command}\n__clite_ec=$?\n{pwd} > "
                    f"{shlex.quote(Path(cwd_file).as_posix())} 2>/dev/null\nexit $__clite_ec"
                )
        if is_cmd:
            # A batch file expands ERRORLEVEL/CD on separate lines, after the user command.
            # /d disables AutoRun; UTF-8 covers non-ASCII paths and output on Windows.
            handle, batch_file = tempfile.mkstemp(prefix="clite-command-", suffix=".cmd")
            with os.fdopen(handle, "w", encoding="utf-8", newline="\r\n") as batch:
                batch.write(f'@echo off\n{command}\nset "__clite_ec=%errorlevel%"\n')
                if cwd_file:
                    batch.write(f'cd > "{cwd_file}"\n')
                batch.write("exit /b %__clite_ec%\n")
            script = f'chcp 65001 >nul & call "{batch_file}"'

        try:
            process = subprocess.Popen(  # noqa: S603 - running the model's command is this tool's job
                subprocess.list2cmdline(shell) + " " + script if is_cmd else [*shell, script],
                cwd=workdir,
                env=build_child_env(),
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=sys.platform != "win32",
            )
        except OSError as exc:
            _remove(cwd_file)
            _remove(batch_file)
            return ExecResult(f"could not start command: {exc}", 126)

        result = capture(
            process,
            timeout=timeout or self.default_timeout,
            stdin_data=stdin_data,
            interrupt=interrupt,
            on_output=on_output,
            max_output_chars=max_output_chars,
            stop=_stop_tree,
            reader_name="clite-terminal-reader",
        )

        if track_cwd and cwd_file and not (result.timed_out or result.interrupted):
            try:
                new_cwd = Path(cwd_file).read_text(encoding="utf-8").strip()
                if new_cwd and os.path.isdir(new_cwd):
                    self.cwd = new_cwd
            except OSError:
                pass
        _remove(cwd_file)
        _remove(batch_file)
        return result


def _remove(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass
