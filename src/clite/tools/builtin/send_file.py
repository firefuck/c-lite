"""``send_file``: hand a local file to the user over a connected chat platform.

Offered only when a gateway is running (``check_fn``), so a terminal session never sees it. The
path is bounded: only files under the session's working directory or its inbound-media directory
may be sent, and the agent's own protected files (``.env`` and friends) stay refused even there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clite.tools.context import ToolContext
from clite.tools.file_safety import read_denied_reason
from clite.tools.registry import PARALLEL_NEVER, registry, tool_error, tool_result

SEND_FILE_SCHEMA = {
    "name": "send_file",
    "description": (
        "Send a local file to the user through a connected chat platform, for example a report "
        "or a generated image. The path must be inside the working directory or a file the user "
        "sent you; the agent's own settings and credentials can never be sent. The target is a "
        "platform name (its home channel) or 'platform:chat id', and defaults to the chat this "
        "conversation is in."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The file to send."},
            "caption": {"type": "string", "description": "Optional text to send with the file."},
            "target": {
                "type": "string",
                "description": "A platform name or 'platform:chat id'; defaults to this chat.",
            },
        },
        "required": ["path"],
    },
}


def _gateway_available() -> bool:
    from clite.gateway.runner import active_runner

    return active_runner() is not None


def _allowed_roots(ctx: ToolContext | None) -> list[Path]:
    """Where a file may be sent from: the working directory and the session's media directory."""
    from clite.gateway import media

    session_key = ""
    agent = getattr(ctx, "agent", None)
    meta = getattr(agent, "session_meta", None)
    if isinstance(meta, dict):
        session_key = str(meta.get("session_key") or "")
    roots: list[Path] = []
    cwd = str(getattr(ctx, "cwd", "") or "")
    if cwd:
        roots.append(Path(cwd))
    if session_key:
        roots.append(media.media_dir(session_key))
    return roots


def send_file_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    from clite.core.errors import CliteError
    from clite.gateway.runner import active_runner

    runner = active_runner()
    if runner is None:
        return tool_error("No gateway is running, so there is no chat to send a file to.")
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return tool_error("path is required")
    path = Path(raw_path).expanduser()
    if not path.is_file():
        return tool_error(f"no file at {path}; check the path and try again")
    denied = read_denied_reason(path)
    if denied:
        return tool_error(f"refusing to send {path}: {denied}")
    roots = _allowed_roots(ctx)
    if roots and not any(path.resolve().is_relative_to(root.resolve()) for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        return tool_error(
            f"refusing to send {path}: it is outside the directories the agent may send from ({allowed})"
        )
    meta = getattr(getattr(ctx, "agent", None), "session_meta", None) or {}
    origin = meta.get("origin") if isinstance(meta, dict) else None
    target = str(args.get("target") or "").strip()
    if not target:
        if not origin or not origin.get("platform"):
            return tool_error("no target given and this conversation has no chat to reply to")
        target = f"{origin['platform']}:{origin.get('chat_id', '')}"
    try:
        destination = runner.send_file_to(
            target, str(path), caption=str(args.get("caption") or ""), origin=origin
        )
    except CliteError as exc:
        return tool_error(str(exc))
    return tool_result(delivered=True, destination=destination, path=str(path))


registry.register(
    "send_file",
    "messaging",
    SEND_FILE_SCHEMA,
    send_file_tool,
    check_fn=_gateway_available,
    emoji="📎",
    parallel=PARALLEL_NEVER,
)
