"""RPC handlers for what a client sends into a session: prompts, slash commands and attachments."""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from clite.agent.attachments import AttachmentError
from clite.core.config import get_path, load_config
from clite.rpc.contracts import schema
from clite.rpc.server import REQUEST_FAILED, RpcError, RpcServer, rpc_method
from clite.runtime.commands import command_catalog


@rpc_method("prompt.submit")
def prompt_submit(server: RpcServer, params: schema.PromptSubmitParams) -> schema.PromptSubmitResult:
    if not params.text.strip() and not params.attachments:
        raise RpcError(REQUEST_FAILED, "the prompt is empty")
    try:
        return server.get_session(params.session_id).submit(params.text, params.busy_mode, params.attachments)
    except AttachmentError as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc


@rpc_method("slash.exec")
def slash_exec(server: RpcServer, params: schema.SlashExecParams) -> schema.SlashExecResult:
    return server.get_session(params.session_id).run_slash(params.command)


def _catalog(server: RpcServer, session_id: str | None) -> list[schema.CommandEntry]:
    cwd, platform = None, server.platform
    if session_id:
        session = server.get_session(session_id)
        cwd, platform = session.chat.agent.cwd, session.chat.platform
    return [schema.CommandEntry(**entry) for entry in command_catalog(platform, cwd=cwd)]


@rpc_method("commands.catalog")
def commands_catalog(server: RpcServer, params: schema.CatalogParams) -> schema.CatalogResult:
    return schema.CatalogResult(commands=_catalog(server, params.session_id))


@rpc_method("complete.slash")
def complete_slash(server: RpcServer, params: schema.CompleteParams) -> schema.CompleteResult:
    prefix = params.prefix.lstrip("/").lower()
    matches = [
        entry
        for entry in _catalog(server, params.session_id)
        if entry.name.startswith(prefix) or any(alias.startswith(prefix) for alias in entry.aliases)
    ]
    return schema.CompleteResult(items=matches[:50])


ATTACHMENT_MAX_AGE_SECONDS = 24 * 3600


def attachments_dir() -> Path:
    """Where a dropped or pasted file waits for the agent. Under the cache: it is disposable."""
    from clite.core.constants import get_cache_dir

    return get_cache_dir() / "attachments"


def _safe_attachment_name(name: str) -> str:
    """A file name with no directory part and nothing that means anything to a shell."""
    base = Path(str(name or "attachment")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return (cleaned or "attachment")[:120]


def _prune_attachments(directory: Path, *, now: float | None = None) -> int:
    """Drop attachments older than a day. They are a copy of something the user still has."""
    current = now if now is not None else time.time()
    removed = 0
    try:
        for entry in directory.iterdir():
            try:
                if entry.is_file() and current - entry.stat().st_mtime > ATTACHMENT_MAX_AGE_SECONDS:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    return removed


@rpc_method("attachment.save")
def attachment_save(server: RpcServer, params: schema.AttachmentSaveParams) -> schema.AttachmentSaveResult:
    import base64
    import binascii

    from clite.agent.attachments import detect_media_type
    from clite.core.constants import ensure_dir

    try:
        raw = base64.b64decode(params.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RpcError(REQUEST_FAILED, "the attachment's bytes are not valid base64") from exc
    limit = int(get_path(load_config(), "attachments.max_bytes", 5_000_000) or 5_000_000)
    if len(raw) > limit:
        raise RpcError(REQUEST_FAILED, f"the attachment is {len(raw)} bytes; the limit is {limit}")
    name = _safe_attachment_name(params.name)
    directory = attachments_dir()
    ensure_dir(directory)
    _prune_attachments(directory)
    target = directory / f"{uuid.uuid4().hex[:8]}-{name}"
    try:
        target.write_bytes(raw)
    except OSError as exc:
        raise RpcError(REQUEST_FAILED, f"could not store the attachment: {exc}") from exc
    return schema.AttachmentSaveResult(
        path=str(target),
        name=name,
        bytes=len(raw),
        image=detect_media_type(raw, target) is not None,
    )
