"""Tests for anomaly detection and cost optimisation analysis."""

from __future__ import annotations

import unittest

from claude_usage.analytics import AnomalyReport, detect_anomaly


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


if __name__ == "__main__":
    unittest.main()
