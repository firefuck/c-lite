"""Phase: call the model, with the whole recovery ladder around it.

Recovery order for a failed call, first match wins:

1. context overflow      compress, then start the iteration again
2. credential problem    rotate to another key for the same provider and retry at once
3. transient failure     back off (honouring ``Retry-After``) and retry, up to ``agent.api_max_retries``
4. provider is down      move to the next entry in ``fallback_providers`` for the rest of the turn
5. otherwise             end the turn with the classified error

The decision comes from ``classify_api_error``; nothing here looks at status codes.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any

from clite.agent.messages import append_to_content, sanitize_for_api
from clite.agent.prompt.caching import apply_cache_markers
from clite.agent.state import BREAK, CONTINUE, PROCEED, TurnState, Verdict
from clite.core.config import get_path
from clite.plugins.hooks import has_hook, invoke_hook
from clite.providers.credentials import get_credential_pool
from clite.providers.errors import ClassifiedError, FailoverReason, classify_api_error
from clite.providers.transports.types import RequestParams

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent

logger = logging.getLogger("clite.agent.turn")

MAX_BACKOFF_SECONDS = 30.0


def assemble_api_messages(agent: AIAgent, state: TurnState) -> list[dict[str, Any]]:
    """The exact message list for this request, built on a copy of the stored history."""
    messages = sanitize_for_api(agent.messages)
    if state.turn_context:
        for message in reversed(messages):
            if message.get("role") == "user":
                message["content"] = append_to_content(message.get("content"), state.turn_context)
                break
    request = [{"role": "system", "content": agent.system_prompt or ""}, *messages]
    profile = state.route.profile
    if profile is not None and profile.wants_cache_markers(state.route.model):
        request = apply_cache_markers(request, str(get_path(agent.config, "prompt_caching.cache_ttl", "5m")))
    return request


def _backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(max(retry_after, 0.0), 120.0)
    return min(2.0 ** attempt, MAX_BACKOFF_SECONDS) + random.uniform(0, 0.5)  # noqa: S311 - jitter, not security


def _recover(agent: AIAgent, state: TurnState, error: ClassifiedError) -> str:
    """``"retry"``, ``"restart"`` (the history changed) or ``"fail"``."""
    max_compress = int(get_path(agent.config, "compression.max_attempts", 3))
    may_compress = (error.should_compress and get_path(agent.config, "compression.enabled", True)
                    and state.compression_attempts < max_compress)
    if may_compress and agent.compress_context(state, reason=error.reason.value):
        return "restart"

    route = state.route
    if error.should_rotate_credential and route.credential is not None and route.profile is not None:
        replacement = get_credential_pool(route.provider, route.profile.env_vars).rotate(route.credential)
        if replacement is not None:
            state.route = route.with_credential(replacement)
            state.rotated_credentials += 1
            agent.callbacks.emit("on_status", "retry", f"{error.reason.value}: switching to another API key")
            return "retry"

    max_retries = int(get_path(agent.config, "agent.api_max_retries", 3))
    if error.retryable and state.api_retries < max_retries:
        state.api_retries += 1
        delay = _backoff(state.api_retries, error.retry_after)
        agent.callbacks.emit(
            "on_status", "retry", f"{error.user_message()} - retrying in {delay:.0f}s ({state.api_retries}/{max_retries})"
        )
        if agent.interrupt_event.wait(delay):
            return "fail"
        return "retry"

    if error.should_fallback:
        fallbacks = agent.get_fallback_routes()
        while state.fallback_index < len(fallbacks):
            candidate = fallbacks[state.fallback_index]
            state.fallback_index += 1
            if (candidate.provider, candidate.model) != (route.provider, route.model):
                state.route = candidate
                state.api_retries = 0
                agent.callbacks.emit("on_status", "fallback",
                                     f"{error.user_message()} - falling back to {candidate.model} via {candidate.provider}")
                return "retry"
    return "fail"


def call_model(agent: AIAgent, state: TurnState) -> Verdict:
    params = RequestParams(
        reasoning_effort=agent.reasoning_effort, session_id=agent.session_id,
        timeout=float(get_path(agent.config, "agent.api_timeout", 600) or 600),
    )
    while True:
        state.api_messages = assemble_api_messages(agent, state)
        if has_hook("pre_api_request"):
            invoke_hook("pre_api_request", session_id=agent.session_id, model=state.route.model,
                        provider=state.route.provider, message_count=len(state.api_messages), api_call=state.api_calls + 1)
        try:
            response = agent.client.complete(
                state.route, state.api_messages, agent.tools or None, params=params, stream=agent.stream,
                on_delta=agent.callbacks.on_delta, on_reasoning=agent.callbacks.on_reasoning,
                cancel=agent.interrupt_event,
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            error = classify_api_error(exc)
            if error.reason is FailoverReason.CANCELLED or agent.interrupt_event.is_set():
                state.interrupted = True
                state.exit_reason = "interrupted"
                return Verdict(BREAK, "interrupted")
            logger.warning("model call failed: %s", error.user_message())
            if has_hook("api_request_error"):
                invoke_hook("api_request_error", session_id=agent.session_id, model=state.route.model,
                            provider=state.route.provider, reason=error.reason.value, status_code=error.status_code,
                            message=error.message)
            action = _recover(agent, state, error)
            if action == "retry":
                continue
            if action == "restart":
                agent.budget.refund()  # the iteration never reached the model
                return Verdict(CONTINUE, "compressed")
            if agent.interrupt_event.is_set():
                state.interrupted = True
                state.exit_reason = "interrupted"
            else:
                state.error = error.user_message()
                state.exit_reason = f"api_error:{error.reason.value}"
            return Verdict(BREAK, state.exit_reason)

        state.response = response
        state.api_calls += 1
        state.api_retries = 0
        agent.record_usage(state, response.usage)
        if has_hook("post_api_request"):
            invoke_hook("post_api_request", session_id=agent.session_id, model=state.route.model,
                        provider=state.route.provider, usage=response.usage, finish_reason=response.finish_reason,
                        api_call=state.api_calls)
        return PROCEED
