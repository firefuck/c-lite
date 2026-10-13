"""Persistent cron execution history and retryable delivery queue."""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from clite.core.constants import ensure_dir
from clite.core.io import atomic_write_json, read_json
from clite.core.locking import exclusive_lock


class CronHistory:
    """Store completed execution records and outputs waiting for delivery."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "history.json"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        ensure_dir(self.directory)
        with exclusive_lock(self.directory / ".history.lock"):
            yield

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        data = read_json(self.path, {})
        return {
            "runs": list(data.get("runs") or []) if isinstance(data, dict) else [],
            "deliveries": list(data.get("deliveries") or []) if isinstance(data, dict) else [],
        }

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        atomic_write_json(self.path, data)

    def record(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            data = self._load()
            data["runs"].append(entry)
            self._save(data)
        return entry

    def list(self, job_id: str | None = None) -> list[dict[str, Any]]:
        entries = self._load()["runs"]
        if job_id:
            entries = [entry for entry in entries if str(entry.get("job_id", "")).startswith(job_id)]
        return entries

    def enqueue_delivery(self, job: dict[str, Any], target: str, text: str, error: str) -> None:
        with self._locked():
            data = self._load()
            data["deliveries"].append(
                {
                    "id": uuid.uuid4().hex,
                    "job": job,
                    "target": target,
                    "text": text,
                    "attempts": 1,
                    "last_error": error,
                    "queued_at": time.time(),
                }
            )
            self._save(data)

    def retry_deliveries(self, deliver: Callable[[dict[str, Any], str], None], max_attempts: int) -> int:
        """Retry pending sends once; discard entries after their configured attempt limit."""
        with self._locked():
            data = self._load()
            keep = []
            completed = 0
            for entry in data["deliveries"]:
                try:
                    job = dict(entry["job"])
                    job["deliver"] = entry["target"]
                    deliver(job, entry["text"])
                    completed += 1
                except Exception as exc:  # noqa: BLE001 - delivery must never stop a tick
                    entry["attempts"] = int(entry.get("attempts", 0)) + 1
                    entry["last_error"] = str(exc)
                    if entry["attempts"] < max_attempts:
                        keep.append(entry)
            data["deliveries"] = keep
            self._save(data)
        return completed
