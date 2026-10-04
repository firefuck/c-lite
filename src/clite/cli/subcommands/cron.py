"""``clite cron``: scheduled agent tasks."""

from __future__ import annotations

import argparse
import time

from clite.cron.jobs import JobError, get_job_store
from clite.cron.scheduler import Scheduler, tick


def _when(timestamp: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp)) if timestamp else "-"


def run_list(args: argparse.Namespace) -> int:
    jobs = get_job_store().list()
    if not jobs:
        print("No scheduled jobs.")
        return 0
    for job in jobs:
        state = "active" if job.get("enabled", True) else "paused"
        print(f"{job['id']}  {state:<7} {job['schedule_display']:<22} next {_when(job.get('next_run_at')):<17} "
              f"last {job.get('last_status') or '-':<7} {job.get('name') or job['prompt'][:50]}")
    return 0


def run_add(args: argparse.Namespace) -> int:
    try:
        job = get_job_store().create(args.prompt, args.schedule, name=args.name or "", deliver=args.deliver,
                                     repeat=args.repeat, skills=args.skill or [])
    except JobError as exc:
        print(f"Not scheduled: {exc}")
        return 1
    print(f"Scheduled {job['id']} ({job['schedule_display']}); next run {_when(job['next_run_at'])}")
    return 0


def _apply(method: str, job_id: str, done: str) -> int:
    store = get_job_store()
    try:
        if method == "remove":
            if not store.remove(job_id):
                raise JobError(f"no job with id {job_id!r}")
        else:
            getattr(store, method)(job_id)
    except JobError as exc:
        print(str(exc))
        return 1
    print(f"{job_id}: {done}")
    return 0


def run_tick(args: argparse.Namespace) -> int:
    outcomes = tick()
    for outcome in outcomes:
        print(f"{outcome['job_id']}: {outcome['status']}" + (f" ({outcome.get('error')})" if outcome.get("error") else ""))
    if not outcomes:
        print("Nothing was due.")
    return 0 if all(outcome["status"] == "ok" for outcome in outcomes) else 1


def run_daemon(args: argparse.Namespace) -> int:
    scheduler = Scheduler(interval=args.interval)
    scheduler.start()
    print(f"Cron scheduler running (checking every {args.interval:.0f}s). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        scheduler.stop()
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("cron", help="schedule agent tasks")
    parser.set_defaults(handler=run_list)
    actions = parser.add_subparsers(dest="cron_action")
    actions.add_parser("list", help="list jobs").set_defaults(handler=run_list)
    add = actions.add_parser("add", help="schedule a prompt")
    add.add_argument("schedule", help="'30m', 'every 2h', '0 9 * * 1-5' or an ISO timestamp")
    add.add_argument("prompt", help="what the agent should do on each run")
    add.add_argument("--name")
    add.add_argument("--deliver", default="local", help="'local' (save to a file) or '<platform>:<chat id>'")
    add.add_argument("--repeat", type=int, help="stop after this many runs")
    add.add_argument("--skill", action="append", help="skill to load into each run (repeatable)")
    add.set_defaults(handler=run_add)
    for action, method, done in (("pause", "pause", "paused"), ("resume", "resume", "resumed"),
                                 ("run", "trigger", "due on the next tick"), ("remove", "remove", "removed")):
        sub = actions.add_parser(action, help=f"{action} a job")
        sub.add_argument("job_id")
        sub.set_defaults(handler=lambda args, method=method, done=done: _apply(method, args.job_id, done))
    actions.add_parser("tick", help="run every job that is due, once").set_defaults(handler=run_tick)
    daemon = actions.add_parser("daemon", help="keep running and tick every minute")
    daemon.add_argument("--interval", type=float, default=60.0)
    daemon.set_defaults(handler=run_daemon)
