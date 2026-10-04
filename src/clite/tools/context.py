"""``ToolContext``: what a tool handler may know about the call it is serving."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolContext:
    """Passed to a handler as ``ctx`` when the handler names that parameter.

    Everything is optional so a tool can be called from a test or a script with
    ``ToolContext()`` and still behave sensibly.
    """

    session_id: str = ""
    task_id: str = ""  # key for the per-task execution environment (cwd, background processes)
    tool_call_id: str = ""
    platform: str = "cli"
    cwd: str = ""
    agent: Any = None  # the AIAgent serving the turn; agent-level tools need it
    callbacks: Any = None  # AgentCallbacks: approve / clarify / progress
    config: dict[str, Any] | None = None
    interrupt: threading.Event | None = None
    approval_mode: str | None = None  # per-run override; "off" is what --yolo sets
    enabled_tools: frozenset[str] = field(default_factory=frozenset)
    depth: int = 0  # delegation depth of the calling agent

    def interrupted(self) -> bool:
        return self.interrupt is not None and self.interrupt.is_set()

    def setting(self, dotpath: str, default: Any = None) -> Any:
        """A config value for this call: the agent's snapshot if present, else the live config."""
        from clite.core.config import get_path, load_config

        return get_path(self.config if self.config is not None else load_config(), dotpath, default)
