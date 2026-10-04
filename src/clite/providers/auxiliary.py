"""Auxiliary model calls: summaries, titles and other side tasks.

A side task never goes through the conversation's message history, so it cannot disturb the
prompt cache. Each task has its own ``auxiliary.<task>`` config; ``provider: main`` reuses
the conversation's route (with the provider's cheap model when it declares one).
"""

from __future__ import annotations

import logging
from typing import Any

from clite.core.config import get_path, load_config
from clite.core.errors import CliteError
from clite.providers.client import LLMClient, ModelClient
from clite.providers.runtime import RuntimeRoute, resolve_runtime_provider
from clite.providers.transports.types import RequestParams

logger = logging.getLogger("clite.providers.auxiliary")


def resolve_auxiliary_route(task: str, main_route: RuntimeRoute, config: dict[str, Any] | None = None) -> RuntimeRoute:
    cfg = config if config is not None else load_config()
    provider = str(get_path(cfg, f"auxiliary.{task}.provider", "main") or "main")
    model = str(get_path(cfg, f"auxiliary.{task}.model", "") or "")
    if provider in ("main", "auto", ""):
        if model:
            return main_route.with_model(model)
        cheap = main_route.profile.resolve_aux_model() if main_route.profile else ""
        return main_route.with_model(cheap) if cheap else main_route
    try:
        return resolve_runtime_provider(provider, model or None, config=cfg)
    except CliteError as exc:
        logger.warning("auxiliary.%s route %r is unusable (%s); using the main route", task, provider, exc)
        return main_route


def call_auxiliary(
    task: str,
    messages: list[dict[str, Any]],
    *,
    main_route: RuntimeRoute,
    client: ModelClient | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float = 120.0,
    config: dict[str, Any] | None = None,
) -> str:
    """Run a one-shot side task and return the text. Raises on failure; callers decide the
    fallback (a compression that cannot summarise still has to make room)."""
    route = resolve_auxiliary_route(task, main_route, config)
    response = (client or LLMClient()).complete(
        route, messages, None, stream=False,
        params=RequestParams(max_tokens=max_tokens, temperature=temperature, timeout=timeout),
    )
    return (response.content or "").strip()
