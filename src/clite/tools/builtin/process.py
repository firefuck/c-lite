"""Background processes: start with ``terminal(background=true)``, manage with ``process``."""

from __future__ import annotations

import atexit
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from clite.core.constants import home_key
from clite.core.redact import redact
from clite.core.threads import start_thread
from clite.tools.context import ToolContext
from clite.tools.environments import get_environment
from clite.tools.environments.local import kill_process_tree, read_output_chunks
from clite.tools.registry import registry, tool_error, tool_result

_BUFFER_CHARS = 200_000
_MAX_PROCESSES = 32


@dataclass
class ManagedProcess:
    id: str
    command: str
    cwd: str
    task_id: str
    process: subprocess.Popen
    profile: str = field(default_factory=home_key)
    drained: threading.Event = field(default_factory=threading.Event)
    started_at: float = field(default_factory=time.time)
    chunks: list[str] = field(default_factory=list)
    size: int = 0
    dropped: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def exit_code(self) -> int | None:
        return self.process.poll()

    @property
    def status(self) -> str:
        return "running" if self.exit_code is None else "exited"

    def append(self, text: str) -> None:
        with self.lock:
            self.chunks.append(text)
            self.size += len(text)
            while self.size > _BUFFER_CHARS:
                excess = self.size - _BUFFER_CHARS
                removed = min(excess, len(self.chunks[0]))
                if removed == len(self.chunks[0]):
                    self.chunks.pop(0)
                else:
                    self.chunks[0] = self.chunks[0][removed:]
                self.size -= removed
                self.dropped += removed

    def output(self, tail_lines: int | None = None) -> str:
        with self.lock:
            text = "".join(self.chunks)
            dropped = self.dropped
        if tail_lines:
            text = "\n".join(text.splitlines()[-tail_lines:])
        prefix = f"[{dropped} earlier characters dropped]\n" if dropped else ""
        return redact(prefix + text)

    def summary(self) -> dict[str, Any]:
        return {
            "process_id": self.id,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "uptime_seconds": round(time.time() - self.started_at, 1),
        }


class ProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[str, ManagedProcess] = {}

    def spawn(self, command: str, *, cwd: str, task_id: str = "", environment=None) -> ManagedProcess:
        with self._lock:
            running = [p for p in self._processes.values() if p.exit_code is None]
            if len(running) >= _MAX_PROCESSES:
                raise RuntimeError(f"too many background processes ({_MAX_PROCESSES}); kill one first")
        if environment is None:
            environment = get_environment(task_id, cwd=cwd)
        process = environment.spawn_background(command, cwd=cwd)
        managed = ManagedProcess(
            id="proc_" + uuid.uuid4().hex[:8], command=command, cwd=cwd, task_id=task_id, process=process
        )

        def pump() -> None:
            assert process.stdout is not None
            try:
                for chunk in read_output_chunks(process.stdout):
                    managed.append(chunk)
            finally:
                managed.drained.set()

        start_thread(pump, name=f"clite-{managed.id}")
        with self._lock:
            self._processes[managed.id] = managed
        return managed

    def get(self, process_id: str) -> ManagedProcess | None:
        with self._lock:
            return self._processes.get(process_id)

    def list(self, task_id: str | None = None) -> list[ManagedProcess]:
        with self._lock:
            return [p for p in self._processes.values() if task_id is None or p.task_id == task_id]

    def wait(self, managed: ManagedProcess, timeout: float, interrupt: threading.Event | None = None) -> bool:
        deadline = time.monotonic() + timeout
        while managed.exit_code is None or not managed.drained.is_set():
            if time.monotonic() > deadline or (interrupt is not None and interrupt.is_set()):
                return False
            time.sleep(0.05)
        return True

    def kill(self, managed: ManagedProcess) -> None:
        kill_process_tree(managed.process)
        try:
            managed.process.wait(2.0)
        except subprocess.TimeoutExpired:
            kill_process_tree(managed.process, force=True)

    def kill_all(self, task_id: str | None = None) -> int:
        victims = [p for p in self.list(task_id) if p.exit_code is None]
        for managed in victims:
            self.kill(managed)
        return len(victims)

    def clear(self) -> None:
        self.kill_all()
        with self._lock:
            self._processes.clear()


process_registry = ProcessRegistry()
atexit.register(process_registry.kill_all)


def reset_process_registry() -> None:
    process_registry.clear()


PROCESS_SCHEMA = {
    "name": "process",
    "description": (
        "Manage background processes started with terminal(background=true). Actions: "
        "'list' shows them; 'poll' returns status and recent output; 'log' returns the full buffered "
        "output; 'wait' blocks until exit or timeout; 'kill' stops it; 'write' sends text to stdin."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "poll", "log", "wait", "kill", "write"]},
            "process_id": {"type": "string", "description": "Id returned by terminal(background=true)."},
            "timeout": {"type": "integer", "description": "Seconds to block for 'wait' (default 60)."},
            "data": {
                "type": "string",
                "description": "Text for 'write'. Add a trailing newline to submit a line.",
            },
            "lines": {"type": "integer", "description": "For 'poll': how many trailing lines (default 40)."},
        },
        "required": ["action"],
    },
}


def process_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    action = args.get("action")
    if action == "list":
        return tool_result(
            processes=[
                p.summary()
                for p in process_registry.list(ctx.task_id or ctx.session_id)
                if p.profile == home_key()
            ]
        )
    managed = process_registry.get(str(args.get("process_id") or ""))
    if managed is None or managed.profile != home_key() or managed.task_id != (ctx.task_id or ctx.session_id):
        return tool_error("Unknown process_id. Use action='list' to see running processes.")
    if action == "poll":
        return tool_result(managed.summary(), output=managed.output(int(args.get("lines") or 40)))
    if action == "log":
        return tool_result(managed.summary(), output=managed.output())
    if action == "wait":
        finished = process_registry.wait(managed, float(args.get("timeout") or 60), ctx.interrupt)
        return tool_result(managed.summary(), finished=finished, output=managed.output(40))
    if action == "kill":
        process_registry.kill(managed)
        return tool_result(managed.summary())
    if action == "write":
        if managed.exit_code is not None or managed.process.stdin is None:
            return tool_error("The process has exited; nothing to write to.")
        try:
            managed.process.stdin.write(str(args.get("data") or ""))
            managed.process.stdin.flush()
        except OSError as exc:
            return tool_error(f"write failed: {exc}")
        return tool_result(managed.summary(), written=True)
    return tool_error(f"Unknown action {action!r}. Use list, poll, log, wait, kill or write.")


registry.register("process", "terminal", PROCESS_SCHEMA, process_tool, emoji="⚙️")
