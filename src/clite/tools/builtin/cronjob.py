"""``cronjob``: let the agent schedule its own future work."""

from __future__ import annotations

from typing import Any

from clite.tools.context import ToolContext
from clite.tools.registry import registry, tool_error, tool_result

CRONJOB_SCHEMA = {
    "name": "cronjob",
    "description": (
        "Schedule a task for later. Each run starts a fresh session with no memory of this conversation, "
        "so the prompt must be self-contained: say what to do, where, and what to report. Actions: "
        "'create' (prompt, schedule), 'list', 'update' (job_id plus fields to change), 'pause', 'resume', "
        "'run' (make it due now), 'remove'. Schedules: a delay ('30m', '2h'), an interval ('every 1d'), a "
        "cron expression ('0 9 * * 1-5') or a timestamp ('2026-01-31T09:00'). deliver: 'local' saves the "
        "output to a file; 'origin' sends it back to the chat this job was created from."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "update", "pause", "resume", "run", "remove"]},
            "job_id": {"type": "string", "description": "Job id (or a unique prefix) for update, pause, resume, run, remove."},
            "prompt": {"type": "string", "description": "What the agent should do on each run. Self-contained."},
            "schedule": {"type": "string", "description": "When to run: '30m', 'every 2h', '0 9 * * *', or an ISO timestamp."},
            "name": {"type": "string", "description": "Short label for the job."},
            "deliver": {"type": "string", "description": "'local' (default) or 'origin'."},
            "repeat": {"type": "integer", "description": "Stop after this many runs. Omit to run until removed."},
            "skills": {"type": "array", "items": {"type": "string"}, "description": "Skills to load into each run."},
        },
        "required": ["action"],
    },
}

_PUBLIC_FIELDS = ("id", "name", "prompt", "schedule_display", "enabled", "deliver", "repeat", "next_run_at",
                  "last_run_at", "last_status", "last_error", "run_count", "skills")


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {key: job.get(key) for key in _PUBLIC_FIELDS}


def _origin(ctx: ToolContext) -> dict[str, Any]:
    meta = getattr(ctx.agent, "session_meta", None) or {}
    return {"platform": ctx.platform, "chat_id": meta.get("chat_id"), "thread_id": meta.get("thread_id"),
            "session_id": ctx.session_id}


def cronjob_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    from clite.cron.jobs import JobError, get_job_store

    ctx = ctx or ToolContext()
    store = get_job_store()
    action = args.get("action")
    job_id = str(args.get("job_id") or "")
    try:
        if action == "list":
            return tool_result(jobs=[_public(job) for job in store.list()])
        if action == "create":
            deliver = str(args.get("deliver") or "local")
            job = store.create(
                str(args.get("prompt") or ""), str(args.get("schedule") or ""), name=str(args.get("name") or ""),
                deliver=deliver, repeat=args.get("repeat"), skills=args.get("skills") or [], origin=_origin(ctx),
            )
            return tool_result(job=_public(job), created=True)
        if not job_id:
            return tool_error("job_id is required for this action; use action='list' to see ids")
        if action == "update":
            fields = {key: args[key] for key in ("prompt", "name", "deliver", "repeat", "skills") if key in args}
            return tool_result(job=_public(store.update(job_id, schedule=args.get("schedule"), **fields)), updated=True)
        if action == "pause":
            return tool_result(job=_public(store.pause(job_id)))
        if action == "resume":
            return tool_result(job=_public(store.resume(job_id)))
        if action == "run":
            return tool_result(job=_public(store.trigger(job_id)), note="The job will run on the next scheduler tick.")
        if action == "remove":
            return tool_result(removed=True) if store.remove(job_id) else tool_error(f"no job with id {job_id!r}")
    except JobError as exc:
        return tool_error(str(exc))
    return tool_error(f"Unknown action {action!r}.")


registry.register("cronjob", "cronjob", CRONJOB_SCHEMA, cronjob_tool, emoji="⏰")
