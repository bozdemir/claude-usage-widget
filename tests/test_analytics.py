"""Tests for anomaly detection and cost optimisation analysis."""

from __future__ import annotations

import unittest

from claude_usage.analytics import AnomalyReport, detect_anomaly, generate_tips


def _samples(daily_totals: list[float], now_ts: float = 86400 * 30) -> list[dict]:
    """Build one max-per-day history sample from a list of daily session peaks."""
    return [
        {"ts": now_ts - (len(daily_totals) - i) * 86400, "session": v, "weekly": v}
        for i, v in enumerate(daily_totals)
    ]


class TestDetectAnomaly(unittest.TestCase):
    def test_flat_usage_no_anomaly(self):
        hist = _samples([0.5] * 30)
        rep = detect_anomaly(hist, today_usage=0.5)
        self.assertIsInstance(rep, AnomalyReport)
        self.assertFalse(rep.is_anomaly)

    def test_spike_beyond_two_sigma_is_anomaly(self):
        hist = _samples([0.45, 0.5, 0.55, 0.5, 0.48, 0.52, 0.5] * 4)
        rep = detect_anomaly(hist, today_usage=0.9)
        self.assertTrue(rep.is_anomaly)
        self.assertGreater(rep.z_score, 2.0)
        self.assertGreater(rep.ratio, 1.0)

    def test_below_average_not_anomaly(self):
        hist = _samples([0.5] * 30)
        rep = detect_anomaly(hist, today_usage=0.1)
        self.assertFalse(rep.is_anomaly)

    def test_too_few_samples_returns_no_anomaly(self):
        hist = _samples([0.5, 0.6])
        rep = detect_anomaly(hist, today_usage=0.95)
        self.assertFalse(rep.is_anomaly)
        self.assertIn("insufficient", rep.reason.lower())

    def test_message_formats_ratio(self):
        hist = _samples([0.5] * 30)
        rep = detect_anomaly(hist, today_usage=1.0)
        self.assertTrue(rep.is_anomaly)
        self.assertIn("2.0x", rep.message)


class TestGenerateTips(unittest.TestCase):
    def test_low_cache_hit_rate_generates_tip(self):
        by_model = {
            "claude-opus-4-7": {
                "input": 1_000_000, "output": 100_000,
                "cache_read": 500_000, "cache_creation": 0,
            }
        }
        tips = generate_tips(by_model, week_cost=200.0, cache_savings=10.0)
        self.assertTrue(any("cache" in t.lower() for t in tips))

    def test_high_cache_hit_rate_no_cache_tip(self):
        by_model = {
            "claude-opus-4-7": {
                "input": 100_000, "output": 50_000,
                "cache_read": 9_000_000, "cache_creation": 0,
            }
        }
        tips = generate_tips(by_model, week_cost=50.0, cache_savings=2000.0)
        self.assertFalse(any("cache hit rate" in t.lower() for t in tips))

    def test_opus_heavy_model_mix_suggests_downgrade(self):
        by_model = {
            "claude-opus-4-7":  {"input": 0, "output": 9_000_000, "cache_read": 0, "cache_creation": 0},
            "claude-sonnet-4-6": {"input": 0, "output": 1_000_000, "cache_read": 0, "cache_creation": 0},
        }
        tips = generate_tips(by_model, week_cost=400.0, cache_savings=0.0)
        self.assertTrue(any("sonnet" in t.lower() for t in tips))

    def test_empty_input_returns_empty_tips(self):
        self.assertEqual(generate_tips({}, week_cost=0.0, cache_savings=0.0), [])


if __name__ == "__main__":
    unittest.main()
