"""``run_batch``: many prompts, unattended, each in its own session, results on disk.

A batch file is JSONL: one JSON object per line, one prompt per object. Every line runs on the
``batch`` platform, which has no user to ask and no way to schedule more work (see
``default_toolsets``), so a batch is safe to leave running.

The run is resumable. Results are appended to ``results.jsonl`` in the output directory as each
line finishes, and a second run skips the ids already recorded as ``completed``. Lines that
failed are tried again: a failure is usually about the model or the network, not the prompt.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clite.core.redact import redact
from clite.providers.client import ModelClient

RESULTS_FILENAME = "results.jsonl"
PLATFORM = "batch"
KNOWN_KEYS = frozenset({"id", "prompt", "model", "provider", "toolsets"})


class BatchError(Exception):
    """The batch file cannot be used: bad JSON, a missing prompt, a duplicated id."""


@dataclass(frozen=True)
class BatchRow:
    """One line of the batch file: the prompt and the settings for its session."""

    line: int
    prompt: str
    id: str
    model: str | None = None
    provider: str | None = None
    toolsets: list[str] | None = None


@dataclass
class BatchReport:
    total: int = 0
    skipped: int = 0
    completed: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


def read_rows(path: str | Path) -> list[BatchRow]:
    """Parse the batch file. Every problem names the line it came from."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise BatchError(f"Cannot read {source}: {exc}") from exc
    rows: list[BatchRow] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BatchError(f"{source}:{number}: not valid JSON ({exc.msg})") from exc
        if not isinstance(entry, dict):
            raise BatchError(f"{source}:{number}: each line must be a JSON object")
        unknown = sorted(set(entry) - KNOWN_KEYS)
        if unknown:
            raise BatchError(
                f"{source}:{number}: unknown key(s) {', '.join(unknown)}; "
                f"known keys are {', '.join(sorted(KNOWN_KEYS))}"
            )
        prompt = entry.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise BatchError(f"{source}:{number}: needs a non-empty 'prompt'")
        row_id = str(entry.get("id") or f"line-{number}")
        if row_id in seen:
            raise BatchError(f"{source}:{number}: id {row_id!r} was already used on line {seen[row_id]}")
        seen[row_id] = number
        toolsets = entry.get("toolsets")
        if toolsets is not None and not isinstance(toolsets, list):
            raise BatchError(f"{source}:{number}: 'toolsets' must be a list of names")
        rows.append(
            BatchRow(
                line=number,
                prompt=prompt,
                id=row_id,
                model=str(entry["model"]) if entry.get("model") else None,
                provider=str(entry["provider"]) if entry.get("provider") else None,
                toolsets=[str(name) for name in toolsets] if toolsets else None,
            )
        )
    if not rows:
        raise BatchError(f"{source}: no prompts found")
    return rows


def read_results(out_dir: str | Path) -> list[dict[str, Any]]:
    """The records already written to ``results.jsonl``, last one per id."""
    path = Path(out_dir) / RESULTS_FILENAME
    if not path.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written line from an interrupted run; the row simply runs again
        if isinstance(record, dict) and record.get("id"):
            latest[str(record["id"])] = record
    return list(latest.values())


def run_batch(
    path: str | Path,
    *,
    out_dir: str | Path,
    workers: int = 1,
    client_factory: Callable[[], ModelClient] | None = None,
    on_result: Callable[[dict[str, Any], BatchReport], None] | None = None,
) -> BatchReport:
    """Run every prompt in ``path``, writing one result line per prompt.

    ``client_factory`` is how tests supply a scripted model; in normal use the client comes
    from the resolved provider. ``on_result`` is called after each line finishes, from the
    worker thread that ran it.
    """
    rows = read_rows(path)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    done = {str(record["id"]) for record in read_results(directory) if record.get("status") == "completed"}
    report = BatchReport(total=len(rows))
    todo = [row for row in rows if row.id not in done]
    report.skipped = len(rows) - len(todo)
    write_lock = threading.Lock()
    results_path = directory / RESULTS_FILENAME

    def record(result: dict[str, Any]) -> None:
        with write_lock, results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        if result["status"] == "completed":
            report.completed += 1
        else:
            report.failed += 1
        report.results.append(result)
        if on_result is not None:
            on_result(result, report)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for result in pool.map(lambda row: _run_row(row, client_factory), todo):
            record(result)
    return report


def _run_row(row: BatchRow, client_factory: Callable[[], ModelClient] | None) -> dict[str, Any]:
    """Run one prompt. Never raises: a broken line becomes a ``failed`` record."""
    from clite.runtime.factory import build_agent

    result: dict[str, Any] = {
        "id": row.id,
        "line": row.line,
        "prompt": redact(row.prompt),
        "status": "failed",
        "final_response": "",
        "exit_reason": "",
        "error": None,
        "session_id": "",
        "model": row.model or "",
        "provider": row.provider or "",
        "duration_seconds": 0.0,
        "api_calls": 0,
        "usage": {},
    }
    agent = None
    try:
        agent = build_agent(
            platform=PLATFORM,
            model=row.model,
            provider=row.provider,
            toolsets=row.toolsets,
            client=client_factory() if client_factory is not None else None,
            auto_title=False,
            session_meta={"display_name": row.id},
        )
        turn = agent.run_conversation(row.prompt)
        result.update(
            status="completed" if turn.completed else "failed",
            final_response=redact(turn.final_response or ""),
            exit_reason=turn.exit_reason,
            error=redact(turn.error) if turn.error else None,
            session_id=turn.session_id,
            model=turn.model or result["model"],
            provider=turn.provider or result["provider"],
            duration_seconds=round(turn.duration, 3),
            api_calls=turn.api_calls,
            usage={
                "input_tokens": turn.usage.input_tokens,
                "output_tokens": turn.usage.output_tokens,
                "cache_read_tokens": turn.usage.cache_read_tokens,
                "cache_write_tokens": turn.usage.cache_write_tokens,
            },
        )
    except Exception as exc:  # noqa: BLE001 - one bad prompt must not stop the batch
        result["error"] = redact(f"{type(exc).__name__}: {exc}")
    finally:
        if agent is not None:
            try:
                agent.close()
            except Exception:  # noqa: BLE001 - closing must not turn a good run into a failure
                pass
    return result


def result_lines(out_dir: str | Path) -> Iterable[str]:
    """The result file's lines, for a caller that wants to print them."""
    path = Path(out_dir) / RESULTS_FILENAME
    if path.exists():
        yield from path.read_text(encoding="utf-8").splitlines()
