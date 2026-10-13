#!/usr/bin/env python3
"""Measure what a compression summary loses.

    python scripts/eval_compression.py                       # runs against the mock provider
    python scripts/eval_compression.py --provider anthropic  # uses a real auxiliary route
    python scripts/eval_compression.py --json                # machine-readable report

The transcript below is built to contain a known set of facts (paths, decisions, a failed
command with its reason, unfinished work). The script compresses it through the real
``ContextCompressor`` and reports which of those facts are still present in the summary that
replaces the middle. Comparing two summary prompts is then a matter of running this before and
after a change and diffing the report.

With ``--provider mock`` nothing touches the network: the call goes through the normal
auxiliary route and the offline mock transport answers, so the whole path can run in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from clite.agent.context.compressor import (  # noqa: E402 - after the sys.path setup above
    ContextCompressor,
    missing_summary_sections,
)
from clite.core.config import load_config  # noqa: E402 - after the sys.path setup above
from clite.providers.auxiliary import resolve_auxiliary_route  # noqa: E402 - after the sys.path setup above
from clite.providers.client import LLMClient  # noqa: E402 - after the sys.path setup above
from clite.providers.runtime import resolve_runtime_provider  # noqa: E402 - after the sys.path setup above
from clite.providers.transports.types import RequestParams  # noqa: E402 - after the sys.path setup above

# Each fact is a string that a good handoff note keeps: a file path, a decision, a failed
# command with its reason, and a piece of unfinished work.
SAMPLE_FACTS = (
    "src/clite/runtime/session.py",
    "src/clite/agent/context/compressor.py",
    "we chose staged summarisation over truncation",
    "pytest tests/runtime -k session failed with exit 2: fixture clite_home not found",
    "finish wiring the eval script into CI",
)


def sample_transcript() -> list[dict[str, Any]]:
    """A short but realistic transcript that contains every fact above."""
    return [
        {"role": "user", "content": "Session resume drops the running turn; make it pick the turn back up."},
        {"role": "assistant", "content": "I will look at the session layer first."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "src/clite/runtime/session.py"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "src/clite/runtime/session.py defines ChatSession.resume() and rebuilds the agent there.",
        },
        {
            "role": "user",
            "content": "Also, src/clite/agent/context/compressor.py should be smarter about long middles.",
        },
        {
            "role": "assistant",
            "content": "For src/clite/agent/context/compressor.py we chose staged summarisation over truncation, "
            "because silently cutting the tape loses the newest facts.",
        },
        {"role": "assistant", "content": "Let me run the tests."},
        {"role": "user", "content": "go on"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": '{"command": "pytest tests/runtime -k session"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_2",
            "name": "terminal",
            "content": "pytest tests/runtime -k session failed with exit 2: fixture clite_home not found",
        },
        {
            "role": "assistant",
            "content": "The failure is unrelated to my change; I will note it and move on.",
        },
        {"role": "user", "content": "ok, keep going"},
        {
            "role": "assistant",
            "content": "Remaining: finish wiring the eval script into CI, then update the specs.",
        },
        {"role": "user", "content": "sounds good"},
    ]


def build_summarizer(provider: str, *, config: dict[str, Any] | None = None) -> Callable[[str], str]:
    """A summariser that goes through the real auxiliary route so the whole path is exercised."""
    cfg = config if config is not None else load_config()
    main_route = resolve_runtime_provider(provider, None, config=cfg)
    route = resolve_auxiliary_route("compression", main_route, cfg)
    client = LLMClient()

    def summarize(prompt: str) -> str:
        response = client.complete(
            route,
            [{"role": "user", "content": prompt}],
            None,
            params=RequestParams(max_tokens=4000, timeout=60.0),
        )
        return (response.content or "").strip()

    return summarize


def evaluate(provider: str = "mock", *, summarize: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Compress the sample transcript and report which facts survived.

    Returns a dict with the counts, the missing facts, the summary itself, and which fixed
    sections the summary omitted. ``summarize`` overrides the provider call (tests use it to
    supply a scripted model).
    """
    config = load_config()
    config["compression"].update({"protect_first_n": 2, "protect_last_n": 2})
    engine = ContextCompressor()
    engine.configure(context_length=200_000, auxiliary_context_length=32_000, config=config)

    transcript = sample_transcript()
    summariser = summarize or build_summarizer(provider, config=config)
    compressed = engine.compress(transcript, summarize=summariser, focus="session resume")
    summary_message = next((message for message in compressed if message.get("is_summary")), None)
    summary = _text(summary_message.get("content")) if summary_message else ""
    # A fact counts as kept when it survives anywhere in the compressed transcript: a path in
    # the protected tail is preserved just as well as one the summary carried forward.
    kept_text = "\n".join(_text(message.get("content")) for message in compressed)

    missing = [fact for fact in SAMPLE_FACTS if fact not in kept_text]
    return {
        "provider": provider,
        "messages_before": len(transcript),
        "messages_after": len(compressed),
        "summariser_calls": engine.last_compression_calls,
        "facts_total": len(SAMPLE_FACTS),
        "facts_kept": len(SAMPLE_FACTS) - len(missing),
        "missing": missing,
        "missing_sections": list(missing_summary_sections(summary)),
        "summary": summary,
    }


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return "" if content is None else str(content)


def render(report: dict[str, Any]) -> str:
    """A human-readable report, for comparing two summary prompts side by side."""
    lines = [
        f"provider:        {report['provider']}",
        f"messages:        {report['messages_before']} -> {report['messages_after']}",
        f"summariser calls: {report['summariser_calls']}",
        f"facts kept:      {report['facts_kept']}/{report['facts_total']}",
    ]
    if report["missing"]:
        lines.append("missing facts:")
        lines += [f"  - {fact}" for fact in report["missing"]]
    if report["missing_sections"]:
        lines.append("missing sections: " + ", ".join(report["missing_sections"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="mock", help="provider for the auxiliary compression route")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--show-summary", action="store_true", help="include the produced summary in the text report"
    )
    args = parser.parse_args(argv)

    report = evaluate(args.provider)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report))
        if args.show_summary:
            print("\n--- summary ---\n" + report["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
