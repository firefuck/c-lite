"""The contract every ``ContextEngine`` must honour, in one reusable check.

An engine is safe to plug into the turn loop when ``compress`` keeps the promises the loop
relies on: it does not mutate the list it is given, it never separates a tool call from its
result, it leaves the roles alternating, and it returns a shorter transcript. A plugin author
runs ``check_context_engine`` on a new engine to prove it; ``tests/agent/test_compression.py``
runs the same function against every engine the registry knows.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from clite.agent.context.engine import ContextEngine

__all__ = ["CONTRACT_WINDOWS", "check_context_engine", "contract_messages"]

# Protected head/tail pairs the check runs by default. The tool round sits at index 9-10, so
# each window exercises a different cut: (2, 3) drops the round whole, (2, 10) keeps the result
# but drops its call, (2, 9) keeps the call and drops the round that follows it. One window
# alone would let a broken engine through.
CONTRACT_WINDOWS: tuple[tuple[int, int], ...] = ((2, 3), (2, 10), (2, 9))


def contract_messages() -> list[dict[str, Any]]:
    """A valid alternating transcript with one tool round, long enough to force a shrink."""
    messages: list[dict[str, Any]] = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index}"}
        for index in range(9)
    ]
    messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_contract",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": "{}"},
                }
            ],
        }
    )
    messages.append({"role": "tool", "tool_call_id": "call_contract", "name": "terminal", "content": "ok"})
    messages.extend(
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index}"}
        for index in range(11, 20)
    )
    return messages


def check_context_engine(
    engine: ContextEngine,
    messages: list[dict[str, Any]] | None = None,
    *,
    protect: tuple[int, int] | None = None,
    summarize: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Assert the ``ContextEngine`` contract for ``engine``; return what ``compress`` produced.

    The transcript is run through ``CONTRACT_WINDOWS`` — several protected head/tail pairs —
    because a single window exercises only some of the promises. Pass ``protect`` to check one
    window, or ``messages`` to check a different transcript (then only the first window runs).
    """
    source = contract_messages() if messages is None else messages
    windows: tuple[tuple[int, int], ...]
    if protect is not None:
        windows = (protect,)
    elif messages is None:
        windows = CONTRACT_WINDOWS
    else:
        windows = (CONTRACT_WINDOWS[0],)
    result: list[dict[str, Any]] = []
    for window in windows:
        result = _check_window(engine, source, window, summarize)
    return result


def _check_window(
    engine: ContextEngine,
    source: list[dict[str, Any]],
    window: tuple[int, int],
    summarize: Callable[[str], str] | None,
) -> list[dict[str, Any]]:
    engine.configure(
        context_length=1_000_000,
        config={"compression": {"protect_first_n": window[0], "protect_last_n": window[1]}},
    )
    before = copy.deepcopy(source)
    result = engine.compress(source, summarize=summarize or _fixed_summary)
    where = f" with protect_first_n={window[0]}, protect_last_n={window[1]}"
    _require(source == before, f"compress must not mutate the messages it was given{where}")
    _require(
        isinstance(result, list) and bool(result),
        f"compress must return a non-empty list{where}",
    )
    _check_tool_pairs(result, where)
    _check_roles_alternate(result, where)
    _require(
        len(result) < len(source),
        f"compress must shorten the transcript{where} ({len(result)} >= {len(source)})",
    )
    return result


def _fixed_summary(prompt: str) -> str:  # the summariser signature takes a prompt
    return "## Goal\ncontract check"


def _check_tool_pairs(messages: list[dict[str, Any]], where: str) -> None:
    calls = sorted(str(call.get("id")) for message in messages for call in message.get("tool_calls") or [])
    results = sorted(
        str(message.get("tool_call_id")) for message in messages if message.get("role") == "tool"
    )
    _require(
        calls == results,
        f"every tool call must keep exactly one matching tool result{where}: {calls} != {results}",
    )


def _check_roles_alternate(messages: list[dict[str, Any]], where: str) -> None:
    """Two messages of one role may follow each other only across a tool round: the assistant
    that called a tool is followed by its results, then by the assistant that read them. Any
    other repeat means the cut butted two halves of the conversation together."""
    previous: dict[str, Any] | None = None
    for message in messages:
        if message.get("role") == "tool":
            continue
        if (
            previous is not None
            and message.get("role") == previous.get("role")
            and not previous.get("tool_calls")
        ):
            _require(
                False,
                f"two {message.get('role')} messages follow each other with no tool round "
                f"between them{where}",
            )
        previous = message


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
