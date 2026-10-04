"""Scheduled jobs: storage and state transitions.

A job is an agent task, not a shell command: a prompt run in a fresh session on a schedule.
Jobs live in ``<home>/cron/jobs.json``; each run's output is saved under
``<home>/cron/output/<job id>/``.

The one rule that matters for correctness: a job's ``next_run_at`` is advanced *before* the
job is dispatched (``mark_dispatched``). If the process dies mid-run, the job is not run a
second time on restart. A run can be lost; it can never be duplicated.
"""

from __future__ import annotations

import contextlib
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from clite.core.config import config_get
from clite.core.constants import ensure_dir, get_cron_dir, home_key
from clite.core.io import atomic_write_json, atomic_write_text, read_json
from clite.core.threats import describe, scan_text
from clite.cron.schedule import KIND_ONCE, Schedule, ScheduleError, next_run, parse_schedule

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]

MAX_PROMPT_CHARS = 20_000
UPDATABLE_FIELDS = frozenset({"name", "prompt", "deliver", "model", "provider", "toolsets", "skills", "repeat"})


class JobError(ValueError):
    """A job operation was refused. The message is written for the model or the user to act on."""


def _check_prompt(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        raise JobError("a job needs a prompt: what the agent should do each time it runs")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise JobError(f"the prompt is longer than {MAX_PROMPT_CHARS} characters")
    threats = scan_text(prompt)
    if threats:
        # A cron prompt runs unattended with the agent's tools. It is held to the same bar
        # as anything else that reaches the model with authority.
        raise JobError(f"the prompt was rejected by the security scan ({describe(threats)})")
    return prompt


class JobStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else get_cron_dir()
        self.path = self.directory / "jobs.json"
        self._lock = threading.RLock()

    # ── storage ──────────────────────────────────────────────────────────────────────────

    @contextlib.contextmanager
    def _locked(self):
        ensure_dir(self.directory)
        with self._lock:
            if fcntl is None:
                yield
                return
            with open(self.directory / ".jobs.lock", "a+") as handle:  # noqa: PTH123
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _load(self) -> list[dict[str, Any]]:
        data = read_json(self.path, {})
        jobs = data.get("jobs") if isinstance(data, dict) else None
        return jobs if isinstance(jobs, list) else []

    def _save(self, jobs: list[dict[str, Any]]) -> None:
        atomic_write_json(self.path, {"jobs": jobs})

    def _timezone(self) -> str:
        return str(config_get("timezone", "") or "")

    # ── queries ──────────────────────────────────────────────────────────────────────────

    def list(self) -> list[dict[str, Any]]:
        return self._load()

    def get(self, job_id: str) -> dict[str, Any] | None:
        matches = [job for job in self._load() if job["id"] == job_id or job["id"].startswith(job_id)]
        return matches[0] if len(matches) == 1 else None

    def due(self, now: float | None = None) -> list[dict[str, Any]]:
        current = time.time() if now is None else now
        return [job for job in self._load()
                if job.get("enabled", True) and job.get("next_run_at") is not None and job["next_run_at"] <= current]

    # ── mutations ────────────────────────────────────────────────────────────────────────

    def create(self, prompt: str, schedule: str, *, name: str = "", deliver: str = "local", repeat: int | None = None,
               model: str | None = None, provider: str | None = None, toolsets: list[str] | None = None,
               skills: list[str] | None = None, origin: dict[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        prompt = _check_prompt(prompt)
        try:
            parsed = parse_schedule(schedule, now=current, timezone=self._timezone())
            first_run = next_run(parsed, current, timezone=self._timezone())
        except ScheduleError as exc:
            raise JobError(str(exc)) from exc
        if repeat is not None and repeat < 1:
            raise JobError("repeat must be at least 1 (or omitted to run until removed)")
        job = {
            "id": uuid.uuid4().hex[:8],
            "name": (name or "").strip()[:80],
            "prompt": prompt,
            "schedule": parsed.to_dict(),
            "schedule_display": parsed.display,
            "enabled": True,
            "deliver": deliver or "local",
            "repeat": repeat,
            "model": model, "provider": provider, "toolsets": toolsets, "skills": list(skills or []),
            "origin": origin,
            "created_at": current, "next_run_at": first_run,
            "last_run_at": None, "last_status": None, "last_error": None, "run_count": 0,
        }
        with self._locked():
            jobs = self._load()
            jobs.append(job)
            self._save(jobs)
        return job

    def _mutate(self, job_id: str, change) -> dict[str, Any]:
        with self._locked():
            jobs = self._load()
            matches = [job for job in jobs if job["id"] == job_id or job["id"].startswith(job_id)]
            if len(matches) != 1:
                raise JobError(f"no job with id {job_id!r}" if not matches else f"job id {job_id!r} is ambiguous")
            change(matches[0])
            self._save(jobs)
            return matches[0]

    def update(self, job_id: str, *, schedule: str | None = None, now: float | None = None, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - UPDATABLE_FIELDS
        if unknown:
            raise JobError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        if "prompt" in fields:
            fields["prompt"] = _check_prompt(fields["prompt"])
        current = time.time() if now is None else now

        def change(job: dict[str, Any]) -> None:
            job.update(fields)
            if schedule is not None:
                try:
                    parsed = parse_schedule(schedule, now=current, timezone=self._timezone())
                    job["next_run_at"] = next_run(parsed, current, timezone=self._timezone())
                except ScheduleError as exc:
                    raise JobError(str(exc)) from exc
                job["schedule"], job["schedule_display"] = parsed.to_dict(), parsed.display

        return self._mutate(job_id, change)

    def pause(self, job_id: str) -> dict[str, Any]:
        return self._mutate(job_id, lambda job: job.update(enabled=False))

    def resume(self, job_id: str, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now

        def change(job: dict[str, Any]) -> None:
            job["enabled"] = True
            schedule = Schedule.from_dict(job["schedule"])
            if job.get("next_run_at") is None or job["next_run_at"] < current:
                job["next_run_at"] = next_run(schedule, current, timezone=self._timezone()) or (
                    current if schedule.kind == KIND_ONCE else None)

        return self._mutate(job_id, change)

    def trigger(self, job_id: str, now: float | None = None) -> dict[str, Any]:
        """Make the job due on the next tick."""
        current = time.time() if now is None else now
        return self._mutate(job_id, lambda job: job.update(next_run_at=current, enabled=True))

    def remove(self, job_id: str) -> bool:
        with self._locked():
            jobs = self._load()
            kept = [job for job in jobs if job["id"] != job_id and not job["id"].startswith(job_id)]
            if len(jobs) - len(kept) != 1:
                return False
            self._save(kept)
            return True

    def mark_dispatched(self, job_id: str, now: float | None = None) -> dict[str, Any]:
        """Advance the job past this run. Call this BEFORE running it (at-most-once)."""
        current = time.time() if now is None else now

        def change(job: dict[str, Any]) -> None:
            schedule = Schedule.from_dict(job["schedule"])
            job["last_run_at"] = current
            job["run_count"] = int(job.get("run_count") or 0) + 1
            remaining = job.get("repeat")
            if remaining is not None:
                remaining -= 1
                job["repeat"] = remaining
            following = next_run(schedule, current, timezone=self._timezone())
            if following is None or (remaining is not None and remaining <= 0):
                job["next_run_at"], job["enabled"] = None, False
            else:
                job["next_run_at"] = following

        return self._mutate(job_id, change)

    def skip_missed(self, job_id: str, now: float | None = None) -> dict[str, Any]:
        """Move a job that came due while nothing was running to its next future slot."""
        current = time.time() if now is None else now

        def change(job: dict[str, Any]) -> None:
            following = next_run(Schedule.from_dict(job["schedule"]), current, timezone=self._timezone())
            job["next_run_at"] = following
            if following is None:
                job["enabled"] = False

        return self._mutate(job_id, change)

    def mark_finished(self, job_id: str, *, status: str, error: str | None = None, output_path: str | None = None) -> None:
        with contextlib.suppress(JobError):  # the job may have been removed while it ran
            self._mutate(job_id, lambda job: job.update(last_status=status, last_error=error, last_output=output_path))

    def save_output(self, job_id: str, text: str, now: float | None = None) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now if now is not None else time.time()))
        path = self.directory / "output" / job_id / f"{stamp}.md"
        atomic_write_text(path, text)
        return path


_STORES: dict[str, JobStore] = {}
_STORES_LOCK = threading.Lock()


def get_job_store() -> JobStore:
    """The job store for the active home (each profile has its own jobs)."""
    key = home_key()
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            store = _STORES[key] = JobStore()
        return store


def reset_job_stores() -> None:
    with _STORES_LOCK:
        _STORES.clear()
