"""Local execution: a subprocess on the host, in its own process group."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from clite.core.config import config_get
from clite.core.env import loaded_secret_names
from clite.tools.environments.base import BaseEnvironment, ExecResult

_POLL_SECONDS = 0.05
_KILL_GRACE_SECONDS = 2.0


def build_child_env(extra: dict[str, str] | None = None, passthrough: list[str] | None = None) -> dict[str, str]:
    """Environment for a command the agent runs.

    Names that came from ``.env`` are removed unless the user listed them in
    ``terminal.env_passthrough``: an API key has no business in a build script's environment,
    and one ``env`` call would otherwise put every credential into the transcript.
    """
    allowed = set(passthrough if passthrough is not None else (config_get("terminal.env_passthrough", []) or []))
    secrets = loaded_secret_names() - allowed
    env = {key: value for key, value in os.environ.items() if key not in secrets}
    env.setdefault("TERM", "dumb")
    env["PAGER"] = "cat"
    env["GIT_PAGER"] = "cat"
    if extra:
        env.update(extra)
    return env


def find_shell() -> list[str]:
    if sys.platform == "win32":
        bash = shutil.which("bash")
        return [bash, "-c"] if bash else [os.environ.get("COMSPEC", "cmd.exe"), "/c"]
    return [shutil.which("bash") or "/bin/sh", "-c"]


def kill_process_tree(process: subprocess.Popen, *, force: bool = False) -> None:
    """Signal the whole process group so children of the shell die with it."""
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class LocalEnvironment(BaseEnvironment):
    name = "local"

    def __init__(self, cwd: str = "", *, timeout: int = 180) -> None:
        super().__init__(cwd or os.getcwd(), timeout=timeout)

    def resolve_path(self, path: str) -> str:
        expanded = Path(os.path.expanduser(path))
        return str(expanded if expanded.is_absolute() else Path(self.cwd) / expanded)

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
        limit = max_output_chars or 50_000
        deadline = time.monotonic() + (timeout or self.default_timeout)
        shell = find_shell()
        track_cwd = cwd is None and sys.platform != "win32"
        cwd_file = None
        script = command
        if track_cwd:
            # Record where the command left the shell so a later call starts there: `cd src`
            # in one call and `ls` in the next behave like one terminal.
            handle, cwd_file = tempfile.mkstemp(prefix="clite-cwd-")
            os.close(handle)
            script = f"{command}\n__clite_ec=$?\npwd -P > '{cwd_file}' 2>/dev/null\nexit $__clite_ec"

        try:
            process = subprocess.Popen(  # noqa: S603 - running the model's command is this tool's job
                [*shell, script],
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
            return ExecResult(f"could not start command: {exc}", 126)

        chunks: list[str] = []
        size = 0
        truncated = False

        def read_output() -> None:
            nonlocal size, truncated
            assert process.stdout is not None
            for line in process.stdout:
                if on_output is not None:
                    try:
                        on_output(line)
                    except Exception:  # noqa: BLE001 - a display callback must not kill the read loop
                        pass
                if size < limit:
                    chunks.append(line)
                    size += len(line)
                else:
                    truncated = True

        reader = threading.Thread(target=read_output, name="clite-terminal-reader", daemon=True)
        reader.start()
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
            kill_process_tree(process)
            try:
                process.wait(_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                kill_process_tree(process, force=True)
                process.wait()
        reader.join(timeout=2.0)

        if track_cwd and cwd_file and not (timed_out or interrupted):
            try:
                new_cwd = Path(cwd_file).read_text(encoding="utf-8").strip()
                if new_cwd and os.path.isdir(new_cwd):
                    self.cwd = new_cwd
            except OSError:
                pass
        _remove(cwd_file)

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


def _remove(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass
