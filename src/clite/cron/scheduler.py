"""Running scheduled jobs.

``tick()`` runs every job that is due, once. It is called by the gateway's background
scheduler, by ``clite cron daemon``, or by an external timer running ``clite cron tick``.
A lock file makes overlapping ticks harmless: the second one returns immediately.
"""

from __future__ import annotations

import errno
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from clite.agent import AgentCallbacks
from clite.core.config import config_get
from clite.core.constants import ensure_dir, get_cron_dir
from clite.core.threads import start_thread
from clite.cron.history import CronHistory
from clite.cron.jobs import JobStore, get_job_store
from clite.providers.client import ModelClient
from clite.skills.catalog import get_skill
from clite.skills.commands import build_skill_message
from clite.tools.environments.local import build_child_env

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

logger = logging.getLogger("clite.cron")

SILENT_MARKER = "[SILENT]"
TICK_SECONDS = 60
# A job this late is treated as "missed while nothing was running", not as "due now".
MISSED_GRACE_SECONDS = 300

Deliver = Callable[[dict[str, Any], str], None]


def _run_script(job: dict[str, Any], store: JobStore) -> tuple[str, str | None]:
    """Run a user-owned collector from cron/scripts and return its output or failure."""
    script = job.get("script")
    if not script:
        return "", None
    path = (store.directory / "scripts" / str(script)).resolve(strict=False)
    scripts = (store.directory / "scripts").resolve(strict=False)
    try:
        path.relative_to(scripts)
    except ValueError:
        return "", "script is outside cron/scripts"
    if not path.is_file():
        return "", f"script {script!r} does not exist in cron/scripts"
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
            env=build_child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"script failed: {exc}"
    output = (completed.stdout or "").strip()
    if completed.returncode:
        return output, f"script exited with status {completed.returncode}: {(completed.stderr or '').strip()}"
    return output, None


def build_job_prompt(job: dict[str, Any], script_output: str = "") -> str:
    """The job's prompt, preceded by its skills and optional script-collected data."""
    parts = []
    for name in job.get("skills") or []:
        skill = get_skill(name)
        if skill is None:
            logger.warning("cron job %s names an unknown skill: %s", job["id"], name)
            continue
        parts.append(build_skill_message(skill))
    if script_output:
        parts.append(f"Data collected before this run:\n{script_output}")
    parts.append(job["prompt"])
    return "\n\n".join(parts)


def run_job(
    job: dict[str, Any],
    *,
    store: JobStore | None = None,
    client: ModelClient | None = None,
    deliver: Deliver | None = None,
) -> dict[str, Any]:
    """Run one job in a fresh session and record the outcome."""
    from clite.runtime.factory import build_agent

    store = store or get_job_store()
    history = CronHistory(store.directory)
    started_at = time.time()
    script_output, script_error = _run_script(job, store)
    timeout = float(config_get("cron.inactivity_timeout_seconds", 600) or 0)
    last_activity = [time.monotonic()]

    def touch(*_args: Any) -> None:
        last_activity[0] = time.monotonic()

    callbacks = AgentCallbacks(on_step=touch, on_delta=touch, on_tool_start=touch, on_tool_complete=touch)
    outcome: dict[str, Any] = {"job_id": job["id"], "status": "failed", "delivered": False}
    usage: dict[str, int] = {}
    agent = None
    try:
        agent = build_agent(
            platform="cron",
            model=job.get("model") or None,
            provider=job.get("provider") or None,
            toolsets=job.get("toolsets") or None,
            callbacks=callbacks,
            client=client,
            auto_title=False,
            session_meta={"display_name": job.get("name") or f"cron {job['id']}"},
        )
        done = threading.Event()
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["result"] = agent.run_conversation(build_job_prompt(job, script_output))
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
        usage = {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cache_read_tokens": result.usage.cache_read_tokens,
            "cache_write_tokens": result.usage.cache_write_tokens,
            "reasoning_tokens": result.usage.reasoning_tokens,
        }
        output_path = store.save_output(job["id"], text or "(no output)")
        outcome.update(
            status="ok" if result.completed else "failed",
            output_path=str(output_path),
            response=text,
            session_id=result.session_id,
            error=result.error,
        )
        silent = text.upper().startswith(SILENT_MARKER) or not text
        if result.completed and not silent and deliver is not None and job.get("deliver", "local") != "local":
            try:
                deliver(job, text)
                outcome["delivered"] = True
            except Exception as exc:  # noqa: BLE001 - the output is on disk either way
                logger.warning("delivery for cron job %s failed: %s", job["id"], exc)
                outcome["delivery_error"] = str(exc)
                history.enqueue_delivery(job, str(job.get("deliver") or "local"), text, str(exc))
        store.mark_finished(
            job["id"], status=outcome["status"], error=result.error, output_path=str(output_path)
        )
    except Exception as exc:  # noqa: BLE001 - one job failing must not stop the tick
        logger.warning("cron job %s failed", job["id"], exc_info=True)
        outcome.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        store.mark_finished(job["id"], status="failed", error=outcome["error"])
    finally:
        if agent is not None:
            agent.close("cron_done")
        history.record(
            {
                "job_id": job["id"],
                "started_at": started_at,
                "duration_seconds": round(time.time() - started_at, 3),
                "status": outcome["status"],
                "usage": usage,
                "output_path": outcome.get("output_path"),
                "error": outcome.get("error"),
                "script_error": script_error,
            }
        )
    return outcome


class _TickLock:
    """Exclusive, non-blocking OS lock, released when its process exits."""

    def __init__(self) -> None:
        self.path = ensure_dir(get_cron_dir()) / ".tick.lock"
        self._fd: int | None = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        # Keep the inode in place: unlinking an advisory lock file lets another tick
        # lock a different inode while the first tick still owns the old one.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if sys.platform == "win32":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd = fd
            return True
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise

    def release(self) -> None:
        if self._fd is not None:
            fd = self._fd
            self._fd = None
            try:
                if sys.platform == "win32":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def tick(
    now: float | None = None, *, client: ModelClient | None = None, deliver: Deliver | None = None
) -> list[dict[str, Any]]:
    """Run every due job once. Returns one outcome per job run (empty when another tick holds
    the lock or scheduling is disabled)."""
    if not config_get("cron.enabled", True):
        return []
    lock = _TickLock()
    if not lock.acquire():
        return []
    try:
        store = get_job_store()
        if deliver is not None:
            CronHistory(store.directory).retry_deliveries(
                deliver, int(config_get("cron.delivery_max_attempts", 3) or 3)
            )
        current = time.time() if now is None else now
        catch_up = bool(config_get("cron.catch_up_missed", True))
        dispatched_jobs = []
        for job in store.due(current):
            if not catch_up and current - job["next_run_at"] > MISSED_GRACE_SECONDS:
                store.skip_missed(job["id"], current)
                continue
            dispatched_jobs.append(store.mark_dispatched(job["id"], current))  # before running: at-most-once
        workers = max(1, int(config_get("cron.max_concurrent_jobs", 4) or 1))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clite-cron-tick") as executor:
            return list(executor.map(lambda job: run_job(job, store=store, client=client, deliver=deliver), dispatched_jobs))
    finally:
        lock.release()


class Scheduler:
    """Background ticker for long-running processes (the gateway, ``clite cron daemon``)."""

    def __init__(
        self,
        *,
        interval: float = TICK_SECONDS,
        deliver: Deliver | None = None,
        client: ModelClient | None = None,
    ) -> None:
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
