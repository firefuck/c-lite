"""Running scheduled jobs.

``tick()`` runs every job that is due, once. It is called by the gateway's background
scheduler, by ``clite cron daemon``, or by an external timer running ``clite cron tick``.
A lock file makes overlapping ticks harmless: the second one returns immediately.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from clite.agent import AgentCallbacks
from clite.core.config import config_get
from clite.core.constants import ensure_dir, get_cron_dir
from clite.core.threads import start_thread
from clite.cron.jobs import JobStore, get_job_store
from clite.providers.client import ModelClient
from clite.skills.catalog import get_skill
from clite.skills.commands import build_skill_message

logger = logging.getLogger("clite.cron")

SILENT_MARKER = "[SILENT]"
TICK_SECONDS = 60
# A job this late is treated as "missed while nothing was running", not as "due now".
MISSED_GRACE_SECONDS = 300

Deliver = Callable[[dict[str, Any], str], None]


def build_job_prompt(job: dict[str, Any]) -> str:
    """The job's prompt, preceded by any skills it asked for."""
    parts = []
    for name in job.get("skills") or []:
        skill = get_skill(name)
        if skill is None:
            logger.warning("cron job %s names an unknown skill: %s", job["id"], name)
            continue
        parts.append(build_skill_message(skill))
    parts.append(job["prompt"])
    return "\n\n".join(parts)


def run_job(job: dict[str, Any], *, store: JobStore | None = None, client: ModelClient | None = None,
            deliver: Deliver | None = None) -> dict[str, Any]:
    """Run one job in a fresh session and record the outcome."""
    from clite.runtime.factory import build_agent

    store = store or get_job_store()
    timeout = float(config_get("cron.inactivity_timeout_seconds", 600) or 0)
    last_activity = [time.monotonic()]

    def touch(*_args: Any) -> None:
        last_activity[0] = time.monotonic()

    callbacks = AgentCallbacks(on_step=touch, on_delta=touch, on_tool_start=touch, on_tool_complete=touch)
    outcome: dict[str, Any] = {"job_id": job["id"], "status": "failed", "delivered": False}
    agent = None
    try:
        agent = build_agent(
            platform="cron", model=job.get("model") or None, provider=job.get("provider") or None,
            toolsets=job.get("toolsets") or None, callbacks=callbacks, client=client, auto_title=False,
            session_meta={"display_name": job.get("name") or f"cron {job['id']}"},
        )
        done = threading.Event()
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["result"] = agent.run_conversation(build_job_prompt(job))
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
            finally:
                done.set()

        start_thread(work, name=f"clite-cron-{job['id']}")
        while not done.wait(1.0):
            if timeout and time.monotonic() - last_activity[0] > timeout:
                logger.warning("cron job %s made no progress for %ss; interrupting", job["id"], timeout)
                agent.interrupt()
                done.wait(30)
                break
        if "error" in box:
            raise box["error"]
        result = box.get("result")
        if result is None:
            raise TimeoutError(f"no activity for {int(timeout)}s")
        text = (result.final_response or "").strip()
        output_path = store.save_output(job["id"], text or "(no output)")
        outcome.update(status="ok" if result.completed else "failed", output_path=str(output_path), response=text,
                       session_id=result.session_id, error=result.error)
        silent = text.upper().startswith(SILENT_MARKER) or not text
        if result.completed and not silent and deliver is not None and job.get("deliver", "local") != "local":
            try:
                deliver(job, text)
                outcome["delivered"] = True
            except Exception as exc:  # noqa: BLE001 - the output is on disk either way
                logger.warning("delivery for cron job %s failed: %s", job["id"], exc)
                outcome["delivery_error"] = str(exc)
        store.mark_finished(job["id"], status=outcome["status"], error=result.error, output_path=str(output_path))
    except Exception as exc:  # noqa: BLE001 - one job failing must not stop the tick
        logger.warning("cron job %s failed", job["id"], exc_info=True)
        outcome.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        store.mark_finished(job["id"], status="failed", error=outcome["error"])
    finally:
        if agent is not None:
            agent.close("cron_done")
    return outcome


class _TickLock:
    """Exclusive, non-blocking lock so two ticks never run the same jobs."""

    def __init__(self) -> None:
        self.path = ensure_dir(get_cron_dir()) / ".tick.lock"
        self._fd: int | None = None

    def acquire(self) -> bool:
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode())
            return True
        except FileExistsError:
            # A crashed tick leaves its lock behind; take it over once it is clearly stale.
            try:
                if time.time() - self.path.stat().st_mtime > 2 * 3600:
                    self.path.unlink()
                    return self.acquire()
            except OSError:
                pass
            return False

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            try:
                self.path.unlink()
            except OSError:
                pass


def tick(now: float | None = None, *, client: ModelClient | None = None, deliver: Deliver | None = None) -> list[dict[str, Any]]:
    """Run every due job once. Returns one outcome per job run (empty when another tick holds
    the lock or scheduling is disabled)."""
    if not config_get("cron.enabled", True):
        return []
    lock = _TickLock()
    if not lock.acquire():
        return []
    try:
        store = get_job_store()
        current = time.time() if now is None else now
        catch_up = bool(config_get("cron.catch_up_missed", True))
        outcomes = []
        for job in store.due(current):
            if not catch_up and current - job["next_run_at"] > MISSED_GRACE_SECONDS:
                store.skip_missed(job["id"], current)
                continue
            dispatched = store.mark_dispatched(job["id"], current)  # before running: at-most-once
            outcomes.append(run_job(dispatched, store=store, client=client, deliver=deliver))
        return outcomes
    finally:
        lock.release()


class Scheduler:
    """Background ticker for long-running processes (the gateway, ``clite cron daemon``)."""

    def __init__(self, *, interval: float = TICK_SECONDS, deliver: Deliver | None = None,
                 client: ModelClient | None = None) -> None:
        self.interval = interval
        self.deliver = deliver
        self.client = client
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = start_thread(self._run, name="clite-cron-scheduler")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                tick(client=self.client, deliver=self.deliver)
            except Exception:  # noqa: BLE001
                logger.warning("cron tick failed", exc_info=True)
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
