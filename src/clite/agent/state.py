"""Per-turn state and the verdicts phases return.

A phase is a function ``(agent, state) -> Verdict``. It reads and mutates ``TurnState`` and
says what the loop should do next. Keeping the turn's variables on one object (instead of
locals in one very long function) is what lets each phase be read and tested alone.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from clite.providers.runtime import RuntimeRoute
from clite.providers.transports.types import NormalizedResponse, Usage

NEXT = "next"  # go on to the next phase
CONTINUE = "continue"  # start a new iteration
BREAK = "break"  # leave the loop and finalize


@dataclass(frozen=True)
class Verdict:
    action: str
    reason: str = ""


PROCEED = Verdict(NEXT)


@dataclass
class TurnState:
    user_message: Any
    route: RuntimeRoute
    task_id: str
    started_at: float = field(default_factory=time.monotonic)
    iteration: int = 0
    api_calls: int = 0
    usage: Usage = field(default_factory=Usage)
    # What the model is offered and sent this iteration.
    api_messages: list[dict[str, Any]] = field(default_factory=list)
    response: NormalizedResponse | None = None
    # Outcome.
    final_response: str | None = None
    partial_text: str = ""  # text carried across "length" continuations
    completed: bool = False
    interrupted: bool = False
    error: str | None = None
    exit_reason: str = ""
    # Recovery counters, reset per turn.
    api_retries: int = 0
    compression_attempts: int = 0
    empty_retries: int = 0
    length_continuations: int = 0
    fallback_index: int = 0
    rotated_credentials: int = 0
    replay_dropped: bool = False  # replayed provider data was dropped once already this turn
    first_message_index: int = 0  # index in agent.messages where this turn begins


@dataclass
class TurnResult:
    final_response: str
    completed: bool
    interrupted: bool = False
    error: str | None = None
    exit_reason: str = ""
    api_calls: int = 0
    usage: Usage = field(default_factory=Usage)
    session_id: str = ""
    model: str = ""
    provider: str = ""
    duration: float = 0.0
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_response": self.final_response, "completed": self.completed, "interrupted": self.interrupted,
            "error": self.error, "exit_reason": self.exit_reason, "api_calls": self.api_calls,
            "session_id": self.session_id, "model": self.model, "provider": self.provider,
            "duration": round(self.duration, 3),
            "usage": {
                "input_tokens": self.usage.input_tokens, "output_tokens": self.usage.output_tokens,
                "cache_read_tokens": self.usage.cache_read_tokens, "cache_write_tokens": self.usage.cache_write_tokens,
                "reasoning_tokens": self.usage.reasoning_tokens, "prompt_tokens": self.usage.prompt_tokens,
            },
        }
