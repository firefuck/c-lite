"""RPC handlers for scheduled jobs: listing, creating and acting on them, and reading their runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clite.rpc.contracts import schema
from clite.rpc.contracts.base import Empty
from clite.rpc.server import REQUEST_FAILED, RpcError, RpcServer, rpc_method


@rpc_method("cron.output")
def cron_output(server: RpcServer, params: schema.CronOutputParams) -> schema.CronOutputResult:
    from clite.core.redact import redact
    from clite.cron.jobs import get_job_store

    job = get_job_store().get(params.job_id)
    if job is None:
        raise RpcError(REQUEST_FAILED, f"no job with id {params.job_id!r}")
    stored = job.get("last_output")
    path = Path(str(stored)) if stored else None
    if path is None or not path.is_file():
        return schema.CronOutputResult(job_id=params.job_id)
    limit = max(200, min(params.max_chars, 200_000))
    # A run may have written a very large report; read a bounded prefix and redact it.
    text = path.read_text(encoding="utf-8", errors="replace")
    return schema.CronOutputResult(
        job_id=params.job_id,
        content=redact(text[:limit]),
        path=str(path),
        truncated=len(text) > limit,
    )


def _job(job: dict[str, Any]) -> schema.CronJob:
    return schema.CronJob.model_validate(
        {key: job.get(key) for key in schema.CronJob.model_fields if job.get(key) is not None}
    )


@rpc_method("cron.list")
def cron_list(server: RpcServer, params: Empty) -> schema.CronListResult:
    from clite.cron.jobs import get_job_store

    return schema.CronListResult(jobs=[_job(job) for job in get_job_store().list()])


@rpc_method("cron.history")
def cron_history(server: RpcServer, params: schema.CronHistoryParams) -> schema.CronHistoryResult:
    from clite.cron.history import CronHistory
    from clite.cron.jobs import get_job_store

    store = get_job_store()
    return schema.CronHistoryResult(
        entries=[
            schema.CronHistoryEntry.model_validate(entry)
            for entry in CronHistory(store.directory).list(params.job_id)
        ]
    )


@rpc_method("cron.create")
def cron_create(server: RpcServer, params: schema.CronCreateParams) -> schema.CronJob:
    from clite.cron.jobs import JobError, get_job_store

    try:
        return _job(
            get_job_store().create(
                params.prompt, params.schedule, name=params.name, deliver=params.deliver, repeat=params.repeat
            )
        )
    except JobError as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc


@rpc_method("cron.action")
def cron_action(server: RpcServer, params: schema.CronActionParams) -> schema.CronListResult:
    from clite.cron.jobs import JobError, get_job_store

    store = get_job_store()
    try:
        if params.action == "remove":
            if not store.remove(params.job_id):
                raise JobError(f"no job with id {params.job_id!r}")
        else:
            {"pause": store.pause, "resume": store.resume, "run": store.trigger}[params.action](params.job_id)
    except JobError as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc
    return schema.CronListResult(jobs=[_job(job) for job in store.list()])
