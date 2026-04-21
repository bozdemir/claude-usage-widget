"""Unit tests for claude_usage.pricing."""

from __future__ import annotations

import math
import warnings

import pytest

from claude_usage.pricing import (
    MODEL_PRICING,
    calculate_cost,
    calculate_stats_cost,
)


def _approx(value: float, expected: float) -> bool:
    return math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12)


class TestMODEL_PRICING:
    def test_opus_4_6_rates(self):
        p = MODEL_PRICING["claude-opus-4-6"]
        assert p["input"] == 15.0
        assert p["output"] == 75.0
        assert p["cache_read"] == 1.50
        assert p["cache_creation"] == 18.75

    def test_opus_4_7_matches_4_6(self):
        assert MODEL_PRICING["claude-opus-4-7"] == MODEL_PRICING["claude-opus-4-6"]

    def test_sonnet_4_6_rates(self):
        p = MODEL_PRICING["claude-sonnet-4-6"]
        assert p["input"] == 3.0
        assert p["output"] == 15.0
        assert p["cache_read"] == 0.30
        assert p["cache_creation"] == 3.75

    def test_haiku_4_5_rates(self):
        p = MODEL_PRICING["claude-haiku-4-5-20251001"]
        assert p["input"] == 1.0
        assert p["output"] == 5.0
        assert p["cache_read"] == 0.10
        assert p["cache_creation"] == 1.25


class TestCalculateCostKnownModels:
    def test_opus_million_tokens_input_only(self):
        result = calculate_cost("claude-opus-4-6", 1_000_000, 0)
        assert _approx(result["input"], 15.0)
        assert _approx(result["output"], 0.0)
        assert _approx(result["total"], 15.0)
        assert _approx(result["cache_savings"], 0.0)

    def test_opus_million_tokens_output_only(self):
        result = calculate_cost("claude-opus-4-6", 0, 1_000_000)
        assert _approx(result["output"], 75.0)
        assert _approx(result["total"], 75.0)

    def test_sonnet_mixed_usage(self):
        # 500k input, 200k output, 100k cache_read, 50k cache_creation
        result = calculate_cost(
            "claude-sonnet-4-6",
            input_tokens=500_000,
            output_tokens=200_000,
            cache_read=100_000,
            cache_creation=50_000,
        )
        assert _approx(result["input"], 500_000 * 3.0 / 1_000_000)  # 1.50
        assert _approx(result["output"], 200_000 * 15.0 / 1_000_000)  # 3.00
        assert _approx(result["cache_read"], 100_000 * 0.30 / 1_000_000)  # 0.03
        assert _approx(result["cache_creation"], 50_000 * 3.75 / 1_000_000)  # 0.1875
        assert _approx(
            result["total"],
            result["input"]
            + result["output"]
            + result["cache_read"]
            + result["cache_creation"],
        )

    def test_haiku_small_call(self):
        result = calculate_cost("claude-haiku-4-5-20251001", 1000, 500)
        # 1000 * 1 / 1e6 + 500 * 5 / 1e6 = 0.001 + 0.0025 = 0.0035
        assert _approx(result["total"], 0.0035)

    def test_opus_4_7_priced_like_opus_4_6(self):
        a = calculate_cost("claude-opus-4-7", 100_000, 50_000, 10_000, 5_000)
        b = calculate_cost("claude-opus-4-6", 100_000, 50_000, 10_000, 5_000)
        assert a == b


class TestCalculateCostUnknownModel:
    def test_unknown_model_falls_back_silently_with_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = calculate_cost("claude-imaginary-9", 1_000_000, 0)
        # Fallback to sonnet pricing ($3/M input).
        assert _approx(result["input"], 3.0)
        assert _approx(result["total"], 3.0)
        assert any(issubclass(w.category, UserWarning) for w in caught)
        assert any("claude-imaginary-9" in str(w.message) for w in caught)

    def test_unknown_model_does_not_crash(self):
        # Must not raise even with garbage identifiers.
        calculate_cost("", 0, 0)
        calculate_cost("totally-made-up", 1, 2, 3, 4)


class TestCalculateCostZero:
    def test_all_zero_tokens(self):
        result = calculate_cost("claude-sonnet-4-6", 0, 0, 0, 0)
        assert result["total"] == 0.0
        assert result["input"] == 0.0
        assert result["output"] == 0.0
        assert result["cache_read"] == 0.0
        assert result["cache_creation"] == 0.0
        assert result["cache_savings"] == 0.0

    def test_defaults_cache_args_to_zero(self):
        r1 = calculate_cost("claude-opus-4-6", 100, 50)
        r2 = calculate_cost("claude-opus-4-6", 100, 50, 0, 0)
        assert r1 == r2

    def test_negative_tokens_clamped(self):
        result = calculate_cost("claude-opus-4-6", -100, -50, -10, -5)
        assert result["total"] == 0.0


class TestCacheSavings:
    def test_opus_cache_savings(self):
        # Reading 1M tokens from cache on opus: paid 1.50, would've paid 15.
        result = calculate_cost("claude-opus-4-6", 0, 0, cache_read=1_000_000)
        assert _approx(result["cache_read"], 1.50)
        assert _approx(result["cache_savings"], 15.0 - 1.50)

    def test_sonnet_cache_savings(self):
        result = calculate_cost(
            "claude-sonnet-4-6", 0, 0, cache_read=2_000_000
        )
        # paid: 2M * 0.30 / 1M = 0.60 ; would've: 2M * 3 / 1M = 6.00 ; saved 5.40
        assert _approx(result["cache_read"], 0.60)
        assert _approx(result["cache_savings"], 5.40)

    def test_cache_creation_does_not_contribute_to_savings(self):
        result = calculate_cost(
            "claude-opus-4-6", 0, 0, cache_read=0, cache_creation=1_000_000
        )
        assert _approx(result["cache_savings"], 0.0)
        assert _approx(result["cache_creation"], 18.75)

    def test_zero_cache_read_zero_savings(self):
        result = calculate_cost("claude-opus-4-6", 1_000_000, 1_000_000)
        assert result["cache_savings"] == 0.0


class TestCalculateStatsCost:
    def test_empty_breakdown(self):
        result = calculate_stats_cost({})
        assert result["total"] == 0.0
        assert result["by_model"] == {}

    def test_single_model_matches_calculate_cost(self):
        breakdown = {
            "claude-opus-4-6": {
                "input": 100_000,
                "output": 50_000,
                "cache_read": 20_000,
                "cache_creation": 10_000,
            }
        }
        stats = calculate_stats_cost(breakdown)
        direct = calculate_cost("claude-opus-4-6", 100_000, 50_000, 20_000, 10_000)
        assert _approx(stats["total"], direct["total"])
        assert _approx(stats["cache_savings"], direct["cache_savings"])
        assert "claude-opus-4-6" in stats["by_model"]
        assert stats["by_model"]["claude-opus-4-6"] == direct

    def test_multi_model_aggregation(self):
        breakdown = {
            "claude-opus-4-6": {"input": 1_000_000, "output": 0},
            "claude-sonnet-4-6": {"input": 1_000_000, "output": 0},
        }
        stats = calculate_stats_cost(breakdown)
        # opus: $15, sonnet: $3 => $18 total input
        assert _approx(stats["input"], 18.0)
        assert _approx(stats["total"], 18.0)
        assert set(stats["by_model"].keys()) == {
            "claude-opus-4-6",
            "claude-sonnet-4-6",
        }

    def test_missing_keys_default_to_zero(self):
        stats = calculate_stats_cost(
            {"claude-sonnet-4-6": {"input": 1_000_000}}  # no output/cache keys
        )
        assert _approx(stats["input"], 3.0)
        assert _approx(stats["output"], 0.0)
        assert _approx(stats["total"], 3.0)

    def test_none_values_treated_as_zero(self):
        stats = calculate_stats_cost(
            {"claude-opus-4-6": {"input": 1_000_000, "output": None}}
        )
        assert _approx(stats["total"], 15.0)

    def test_aggregates_cache_savings(self):
        breakdown = {
            "claude-opus-4-6": {
                "input": 0,
                "output": 0,
                "cache_read": 1_000_000,
                "cache_creation": 0,
            },
            "claude-sonnet-4-6": {
                "input": 0,
                "output": 0,
                "cache_read": 1_000_000,
                "cache_creation": 0,
            },
        }
        stats = calculate_stats_cost(breakdown)
        # opus savings: 15 - 1.5 = 13.5 ; sonnet: 3 - 0.3 = 2.7 ; total 16.2
        assert _approx(stats["cache_savings"], 16.2)

    def test_unknown_model_in_breakdown_does_not_crash(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stats = calculate_stats_cost(
                {"claude-nope": {"input": 1_000_000, "output": 0}}
            )
        # fallback sonnet: $3
        assert _approx(stats["total"], 3.0)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
