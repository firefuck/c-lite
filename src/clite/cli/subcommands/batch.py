"""``clite batch``: run many prompts without watching, and keep the results on disk."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from clite.runtime.batch import RESULTS_FILENAME, BatchError, BatchReport, read_rows, run_batch


def _default_out(source: str) -> str:
    """Where the results go when ``--out`` is not given: beside the batch file, named after it.

    Derived from the file rather than the working directory, so running the same file from two
    places resumes the same run instead of starting a second one.
    """
    path = Path(source)
    return str(path.parent / f"{path.stem}-out")


def run_run(args: argparse.Namespace) -> int:
    out_dir = args.out or _default_out(args.file)
    try:
        rows = read_rows(args.file)
    except BatchError as exc:
        print(f"Not run: {exc}")
        return 1
    print(
        f"{len(rows)} prompt(s) from {args.file}, {max(1, args.workers)} at a time. "
        f"Results: {Path(out_dir) / RESULTS_FILENAME}"
    )

    def announce(result: dict[str, Any], report: BatchReport) -> None:
        finished = report.completed + report.failed
        status = "ok" if result["status"] == "completed" else "FAILED"
        line = f"[{finished}/{report.total - report.skipped}] {result['id']}: {status}"
        if result.get("error"):
            line += f" - {result['error']}"
        print(line)

    try:
        report = run_batch(args.file, out_dir=out_dir, workers=args.workers, on_result=announce)
    except BatchError as exc:
        print(f"Not run: {exc}")
        return 1
    print(f"Done: {report.completed} completed, {report.failed} failed, {report.skipped} already done.")
    return 0 if report.ok else 1


def run_usage(args: argparse.Namespace) -> int:
    print(
        "Usage: clite batch run <file.jsonl> [--workers N] [--out <dir>]\n"
        'Each line of the file is one prompt: {"prompt": "...", "id": "..."}.\n'
        "A run that stops can be started again: lines already completed are skipped."
    )
    return 1


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("batch", help="run many prompts unattended")
    parser.set_defaults(handler=run_usage)
    actions = parser.add_subparsers(dest="batch_action")
    run = actions.add_parser("run", help="run every prompt in a JSONL file")
    run.add_argument("file", help="one JSON object per line, each with a 'prompt'")
    run.add_argument("--workers", type=int, default=1, help="how many prompts run at once (default 1)")
    run.add_argument("-o", "--out", help="directory for results.jsonl (default: beside the input file)")
    run.set_defaults(handler=run_run)
