"""Tests for model pricing resolution and cost estimation."""

import pytest

from clite.core.constants import ensure_dir, get_cache_dir
from clite.core.io import atomic_write_json
from clite.providers.base import ModelPricing, ProviderProfile
from clite.providers.pricing import get_model_pricing, resolve_model_pricing
from clite.providers.registry import register_provider


def test_pricing_cost_calculation():
    rates = ModelPricing(
        input_cost_per_million=3.0,
        output_cost_per_million=15.0,
        cache_read_cost_per_million=0.30,
        cache_write_cost_per_million=3.75,
    )
    # 10,000 input tokens = $0.03
    # 2,000 output tokens = $0.03
    # 50,000 cache read tokens = $0.015
    # 20,000 cache write tokens = $0.075
    # Total = $0.15
    cost = rates.calculate_cost(
        input_tokens=10_000,
        output_tokens=2_000,
        cache_read_tokens=50_000,
        cache_write_tokens=20_000,
    )
    assert cost == pytest.approx(0.15)


def test_pricing_from_dict_per_million_and_per_token():
    # Per-million convention
    p1 = ModelPricing.from_dict(
        {
            "input_cost_per_million": 3.0,
            "output_cost_per_million": 15.0,
            "cache_read_cost_per_million": 0.3,
            "cache_write_cost_per_million": 3.75,
        }
    )
    assert p1.input_cost_per_million == 3.0
    assert p1.output_cost_per_million == 15.0
    assert p1.cache_read_cost_per_million == 0.3
    assert p1.cache_write_cost_per_million == 3.75

    # Per-token convention (e.g. OpenRouter API numbers)
    p2 = ModelPricing.from_dict(
        {
            "prompt": "0.000003",
            "completion": "0.000015",
            "input_cache_read": "0.0000003",
            "input_cache_write": "0.00000375",
        }
    )
    assert p2.input_cost_per_million == pytest.approx(3.0)
    assert p2.output_cost_per_million == pytest.approx(15.0)
    assert p2.cache_read_cost_per_million == pytest.approx(0.3)
    assert p2.cache_write_cost_per_million == pytest.approx(3.75)


def test_pricing_resolution_layered_override_wins(clite_home):
    profile = ProviderProfile(
        name="test-prov",
        model_pricing={
            "custom-model": ModelPricing(1.0, 2.0, 0.1, 0.2),
        },
    )
    register_provider(profile)

    cfg = {
        "pricing": {
            "overrides": {
                "custom-model": {
                    "input_cost_per_million": 10.0,
                    "output_cost_per_million": 20.0,
                    "cache_read_cost_per_million": 1.0,
                    "cache_write_cost_per_million": 2.0,
                }
            }
        }
    }
    pricing = resolve_model_pricing("custom-model", provider="test-prov", profile=profile, config=cfg)
    assert pricing is not None
    assert pricing.input_cost_per_million == 10.0
    assert pricing.output_cost_per_million == 20.0


def test_pricing_resolution_profile_fallback(clite_home):
    profile = ProviderProfile(
        name="test-prov-2",
        model_pricing={
            "my-model-v1": ModelPricing(2.0, 8.0, 0.2, 0.8),
        },
    )
    register_provider(profile)

    pricing = resolve_model_pricing("my-model-v1", provider="test-prov-2", profile=profile, config={})
    assert pricing is not None
    assert pricing.input_cost_per_million == 2.0
    assert pricing.output_cost_per_million == 8.0


def test_pricing_resolution_cached_catalog(clite_home):
    profile = ProviderProfile(name="aggregator-prov")
    register_provider(profile)

    cache_file = get_cache_dir() / "models" / "aggregator-prov.json"
    ensure_dir(cache_file.parent)
    atomic_write_json(
        cache_file,
        {
            "fetched_at": 1000000000.0,
            "models": [
                {
                    "id": "open-model-1",
                    "pricing": {
                        "prompt": "0.000002",
                        "completion": "0.000006",
                    },
                }
            ],
        },
    )

    pricing = resolve_model_pricing("open-model-1", provider="aggregator-prov", profile=profile, config={})
    assert pricing is not None
    assert pricing.input_cost_per_million == pytest.approx(2.0)
    assert pricing.output_cost_per_million == pytest.approx(6.0)


def test_pricing_resolution_unknown_model_returns_none(clite_home):
    pricing = get_model_pricing("unknown-nonexistent-model", provider="mock", config={})
    assert pricing is None


def test_anthropic_profile_has_official_pricing():
    from clite.providers.registry import get_provider

    profile = get_provider("anthropic")
    assert profile is not None

    sonnet = profile.get_model_pricing("claude-3-5-sonnet")
    assert sonnet is not None
    assert sonnet.input_cost_per_million == 3.0
    assert sonnet.output_cost_per_million == 15.0
    assert sonnet.cache_read_cost_per_million == 0.30
    assert sonnet.cache_write_cost_per_million == 3.75

    haiku = profile.get_model_pricing("claude-3-5-haiku")
    assert haiku is not None
    assert haiku.input_cost_per_million == 0.80
    assert haiku.output_cost_per_million == 4.0
    assert haiku.cache_read_cost_per_million == 0.08
    assert haiku.cache_write_cost_per_million == 1.00

    opus = profile.get_model_pricing("claude-3-opus")
    assert opus is not None
    assert opus.input_cost_per_million == 15.0
    assert opus.output_cost_per_million == 75.0
    assert opus.cache_read_cost_per_million == 1.50
    assert opus.cache_write_cost_per_million == 18.75
