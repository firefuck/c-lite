"""Model pricing and cost estimation: rates per million tokens and layered lookup.

Rates are specified in USD per million tokens across four dimensions:
- input (prompt tokens excluding cache)
- output (generation/completion tokens including reasoning)
- cache read (prompt tokens served from cache)
- cache write (prompt tokens written into cache)

Layered resolution:
1. User overrides in configuration (``pricing.overrides`` or ``model.pricing``)
2. Provider profile declarations (``ProviderProfile.model_pricing``)
3. Cached model catalog when reported by the provider (e.g. OpenRouter)
4. None (unknown / unpriced model)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from clite.core.config import get_path, load_config

if TYPE_CHECKING:
    from clite.providers.base import ProviderProfile

logger = logging.getLogger("clite.providers.pricing")


def _to_million_rate(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        rate = float(val)
    except (TypeError, ValueError):
        return 0.0
    # Values smaller than 0.0001 are per-token rates (e.g. OpenRouter returns
    # USD per token like 0.000003). Scale them to USD per million tokens.
    if 0.0 < rate < 0.0001:
        return rate * 1_000_000.0
    return rate


@dataclass(frozen=True)
class ModelPricing:
    """Pricing rates in USD per million tokens."""

    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    cache_read_cost_per_million: float = 0.0
    cache_write_cost_per_million: float = 0.0

    def calculate_cost(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Calculate total USD cost for the given token counts."""
        return (
            (input_tokens / 1_000_000.0) * self.input_cost_per_million
            + (output_tokens / 1_000_000.0) * self.output_cost_per_million
            + (cache_read_tokens / 1_000_000.0) * self.cache_read_cost_per_million
            + (cache_write_tokens / 1_000_000.0) * self.cache_write_cost_per_million
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelPricing:
        """Parse pricing from varied dictionary keys and conventions."""
        raw_in = (
            data.get("input_cost_per_million")
            if "input_cost_per_million" in data
            else (
                data.get("input")
                if "input" in data
                else data.get("prompt_cost_per_million", data.get("prompt"))
            )
        )
        raw_out = (
            data.get("output_cost_per_million")
            if "output_cost_per_million" in data
            else (
                data.get("output")
                if "output" in data
                else data.get("completion_cost_per_million", data.get("completion"))
            )
        )
        raw_read = (
            data.get("cache_read_cost_per_million")
            if "cache_read_cost_per_million" in data
            else (
                data.get("cache_read")
                if "cache_read" in data
                else (
                    data.get("input_cache_read")
                    if "input_cache_read" in data
                    else data.get("cache_read_token")
                )
            )
        )
        raw_write = (
            data.get("cache_write_cost_per_million")
            if "cache_write_cost_per_million" in data
            else (
                data.get("cache_write")
                if "cache_write" in data
                else (
                    data.get("input_cache_write")
                    if "input_cache_write" in data
                    else data.get("cache_write_token")
                )
            )
        )
        return cls(
            input_cost_per_million=_to_million_rate(raw_in),
            output_cost_per_million=_to_million_rate(raw_out),
            cache_read_cost_per_million=_to_million_rate(raw_read),
            cache_write_cost_per_million=_to_million_rate(raw_write),
        )


def _match_override(model: str, provider: str, overrides: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [model]
    if provider:
        candidates.append(f"{provider}:{model}")

    # Exact matches first
    for cand in candidates:
        if cand in overrides and isinstance(overrides[cand], dict):
            return overrides[cand]

    # Prefix matches, longest match wins
    matches: list[tuple[str, dict[str, Any]]] = []
    for pattern, val in overrides.items():
        if not isinstance(val, dict):
            continue
        for cand in candidates:
            if cand.startswith(pattern):
                matches.append((pattern, val))
                break

    if matches:
        return max(matches, key=lambda pair: len(pair[0]))[1]
    return None


def resolve_model_pricing(
    model: str,
    provider: str = "",
    *,
    profile: ProviderProfile | None = None,
    config: dict[str, Any] | None = None,
) -> ModelPricing | None:
    """Resolve pricing for a model following the layered hierarchy.

    1. User configuration override (``pricing.overrides`` or ``model.pricing``)
    2. Provider profile declared pricing
    3. Cached model catalog (e.g. OpenRouter)
    4. None when no pricing is known
    """
    if not model:
        return None

    cfg = config if config is not None else load_config()

    # 1. User config override
    overrides = get_path(cfg, "pricing.overrides") or get_path(cfg, "model.pricing") or {}
    if isinstance(overrides, dict) and overrides:
        entry = _match_override(model, provider, overrides)
        if entry is not None:
            return ModelPricing.from_dict(entry)

    # 2. Provider profile
    resolved_profile = profile
    if resolved_profile is None and provider:
        from clite.providers.registry import get_provider

        resolved_profile = get_provider(provider)

    if resolved_profile is not None:
        declared = resolved_profile.get_model_pricing(model)
        if declared is not None:
            return declared

    # 3. Cached model catalog
    if provider or (resolved_profile is not None and resolved_profile.name):
        prov_name = provider or (resolved_profile.name if resolved_profile else "")
        from clite.providers.models import get_cached_model_pricing

        cached_pricing = get_cached_model_pricing(prov_name, model)
        if cached_pricing is not None:
            return cached_pricing

    return None


get_model_pricing = resolve_model_pricing
