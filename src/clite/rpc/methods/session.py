"""RPC handlers for sessions: the ones open on this connection and the ones stored in the database.

``session_id`` names a runtime session of this server; ``stored_session_id`` names a row of the
session database, whether or not a runtime session has it open.
"""

from __future__ import annotations

import json
from typing import Any

from clite.rpc.contracts import schema
from clite.rpc.contracts.base import Ok
from clite.rpc.server import REQUEST_FAILED, RpcError, RpcServer, rpc_method
from clite.rpc.session import RpcSession
from clite.runtime.trajectory import build_trajectory
from clite.state.db import get_session_db


@rpc_method("session.create")
def session_create(server: RpcServer, params: schema.SessionCreateParams) -> schema.SessionInfo:
    session = RpcSession(server, params)
    session.id = server.add_session(session)
    return session.info()


@rpc_method("session.info")
def session_info(server: RpcServer, params: schema.SessionRef) -> schema.SessionInfo:
    return server.get_session(params.session_id).info()


@rpc_method("session.list")
def session_list(server: RpcServer, params: schema.SessionListParams) -> schema.SessionListResult:
    rows = get_session_db().list_sessions(
        limit=max(1, min(params.limit, 200)),
        sources=[params.source] if params.source else None,
        include_archived=params.include_archived,
    )
    return schema.SessionListResult(
        sessions=[
            schema.StoredSession(
                id=row["id"],
                title=row.get("title") or "",
                source=row["source"],
                model=row.get("model") or "",
                message_count=row.get("message_count") or 0,
                started_at=row["started_at"],
                last_activity_at=row.get("last_activity_at"),
                archived=bool(row.get("archived")),
                pinned=bool(row.get("pinned")),
                estimated_cost_usd=row.get("estimated_cost_usd"),
            )
            for row in rows
        ]
    )


@rpc_method("session.history")
def session_history(server: RpcServer, params: schema.SessionRef) -> schema.SessionHistoryResult:
    return schema.SessionHistoryResult(messages=server.get_session(params.session_id).history())


@rpc_method("session.close")
def session_close(server: RpcServer, params: schema.SessionRef) -> Ok:
    server.get_session(params.session_id)
    server.remove_session(params.session_id)
    return Ok()


@rpc_method("session.attach")
def session_attach(server: RpcServer, params: schema.SessionAttachParams) -> schema.SessionAttachResult:
    from clite.rpc.replay import get_detached_sessions, get_event_log
    from clite.rpc.server import SESSION_NOT_FOUND

    log = get_event_log()
    # The same critical section `emit` uses: taking the session back and reading what it missed
    # happen together, so nothing is delivered live *and* replayed, and nothing falls between.
    with log.lock:
        session = get_detached_sessions().adopt(params.session_id)
        if session is None:
            raise RpcError(
                SESSION_NOT_FOUND,
                f"session {params.session_id!r} is no longer open; resume the stored session instead",
            )
        events, complete = log.missed(params.session_id, max(0, params.last_seq))
        newest = log.last_seq
        server.adopt_session(session)
    return schema.SessionAttachResult(
        session=session.info(),
        events=[schema.ReplayEvent(**event) for event in events],
        complete=complete,
        last_seq=newest,
    )


@rpc_method("session.interrupt")
def session_interrupt(server: RpcServer, params: schema.SessionRef) -> Ok:
    server.get_session(params.session_id).chat.interrupt()
    return Ok()


@rpc_method("session.steer")
def session_steer(server: RpcServer, params: schema.SessionSteerParams) -> Ok:
    server.get_session(params.session_id).chat.steer(params.text)
    return Ok()


@rpc_method("session.title")
def session_title(server: RpcServer, params: schema.SessionTitleParams) -> schema.SessionTitleResult:
    session = server.get_session(params.session_id)
    if params.title is not None:
        title = session.chat.set_title(params.title)
        server.emit("session.info", session.id, session.info())
        return schema.SessionTitleResult(title=title)
    return schema.SessionTitleResult(title=session.info().title)


@rpc_method("session.delete")
def session_delete(server: RpcServer, params: schema.SessionDeleteParams) -> Ok:
    if any(session.chat.session_id == params.stored_session_id for session in server.sessions.values()):
        raise RpcError(REQUEST_FAILED, "that session is open; close it or start a new one first")
    if not get_session_db().delete_session(params.stored_session_id):
        raise RpcError(REQUEST_FAILED, f"no stored session {params.stored_session_id!r}")
    return Ok()


@rpc_method("session.rename")
def session_rename(server: RpcServer, params: schema.SessionRenameParams) -> schema.SessionRenameResult:
    _require_stored_session(params.stored_session_id)
    title = get_session_db().set_title(params.stored_session_id, params.title)
    # If that session is open, its runtime copy carries the old title: refresh it too.
    for session in list(server.sessions.values()):
        if session.chat.session_id == params.stored_session_id:
            session.chat.set_title(title)
            server.emit("session.info", session.id, session.info())
            break
    return schema.SessionRenameResult(title=title)


@rpc_method("session.search")
def session_search(server: RpcServer, params: schema.SessionSearchParams) -> schema.SessionSearchResult:
    hits = get_session_db().search_messages(params.query, limit=max(1, min(params.limit, 200)))
    return schema.SessionSearchResult(
        hits=[
            schema.SessionSearchHit(
                stored_session_id=hit["session_id"],
                title=hit.get("session_title") or "",
                source=hit.get("session_source") or "",
                role=hit.get("role") or "",
                snippet=hit.get("snippet") or "",
                timestamp=hit.get("timestamp"),
            )
            for hit in hits
        ]
    )


def _require_stored_session(stored_session_id: str) -> dict[str, Any]:
    row = get_session_db().get_session(stored_session_id)
    if row is None:
        raise RpcError(REQUEST_FAILED, f"no stored session {stored_session_id!r}")
    return row


@rpc_method("session.pin")
def session_pin(server: RpcServer, params: schema.SessionPinParams) -> Ok:
    _require_stored_session(params.stored_session_id)
    get_session_db().update_session(params.stored_session_id, pinned=1 if params.pinned else 0)
    return Ok()


@rpc_method("session.archive")
def session_archive(server: RpcServer, params: schema.SessionArchiveParams) -> Ok:
    _require_stored_session(params.stored_session_id)
    get_session_db().update_session(params.stored_session_id, archived=1 if params.archived else 0)
    return Ok()


@rpc_method("session.export")
def session_export(server: RpcServer, params: schema.SessionExportParams) -> schema.SessionExportResult:
    row = _require_stored_session(params.stored_session_id)
    db = get_session_db()
    if params.format == "trajectory":
        document = build_trajectory(row, db.get_messages(row["id"]))
        count = len(document["steps"])
    else:
        messages = [
            {key: value for key, value in message.items() if key != "_row_id"}
            for message in db.get_messages(row["id"])
        ]
        document = {
            "session": {
                key: row[key] for key in ("id", "source", "model", "provider", "title", "started_at")
            },
            "messages": messages,
        }
        count = len(messages)
    return schema.SessionExportResult(
        filename=f"{row['id']}.json",
        content=json.dumps(document, ensure_ascii=False, indent=2),
        count=count,
    )


@rpc_method("session.compress")
def session_compress(server: RpcServer, params: schema.SessionCompressParams) -> schema.SessionCompressResult:
    session = server.get_session(params.session_id)
    if session.busy:
        from clite.rpc.server import SESSION_BUSY

        raise RpcError(SESSION_BUSY, "a turn is running")
    compressed = session.chat.agent.compress_context(focus=params.focus)
    server.emit("session.info", session.id, session.info())
    return schema.SessionCompressResult(compressed=compressed, message_count=len(session.chat.agent.messages))


@rpc_method("session.usage")
def session_usage(server: RpcServer, params: schema.SessionRef) -> schema.SessionUsageResult:
    agent = server.get_session(params.session_id).chat.agent
    usage = agent.total_usage
    row = get_session_db().get_session(agent.session_id) or {}
    cost = row.get("estimated_cost_usd")
    if cost is None:
        cost = agent.total_cost_usd
    return schema.SessionUsageResult(
        usage=schema.UsageTotals(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            prompt_tokens=usage.prompt_tokens,
            estimated_cost_usd=cost,
        ),
        context=schema.ContextStatus(**agent.context_status()),
        estimated_cost_usd=cost,
    )
