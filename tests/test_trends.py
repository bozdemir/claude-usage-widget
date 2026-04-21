"""Tests for trend aggregation (heatmap, monthly, hourly)."""

from __future__ import annotations

import time
import unittest

from claude_usage.trends import daily_heatmap, hourly_histogram, monthly_summary


def _s(ts: float, session: float = 0.5, weekly: float = 0.1) -> dict:
    return {"ts": ts, "session": session, "weekly": weekly}


class TestDailyHeatmap(unittest.TestCase):
    def test_heatmap_length_is_n_days(self):
        now = 1_000_000.0
        result = daily_heatmap([], now=now, n_days=30)
        self.assertEqual(len(result), 30)
        self.assertTrue(all(v == 0.0 for v in result))

    def test_heatmap_stores_daily_peak(self):
        now = 100 * 86400.0
        samples = [
            _s(now - 0.5 * 86400, session=0.3),
            _s(now - 0.3 * 86400, session=0.7),
            _s(now - 1.5 * 86400, session=0.2),
        ]
        result = daily_heatmap(samples, now=now, n_days=3)
        self.assertEqual(result[-1], 0.7)
        self.assertEqual(result[-2], 0.2)

    def test_old_samples_ignored(self):
        now = 100 * 86400.0
        samples = [_s(now - 500 * 86400, session=0.9)]
        result = daily_heatmap(samples, now=now, n_days=30)
        self.assertTrue(all(v == 0.0 for v in result))


class TestMonthlySummary(unittest.TestCase):
    def test_empty_samples_returns_empty(self):
        self.assertEqual(monthly_summary([], now=time.time(), n_months=3), [])

    def test_bucket_by_calendar_month(self):
        jan_15 = time.mktime((2026, 1, 15, 12, 0, 0, 0, 0, -1))
        jan_20 = time.mktime((2026, 1, 20, 12, 0, 0, 0, 0, -1))
        feb_10 = time.mktime((2026, 2, 10, 12, 0, 0, 0, 0, -1))
        samples = [
            _s(jan_15, session=0.3),
            _s(jan_20, session=0.5),
            _s(feb_10, session=0.7),
        ]
        result = monthly_summary(samples, now=feb_10, n_months=3)
        months = {m["month"]: m for m in result}
        self.assertIn("2026-01", months)
        self.assertEqual(months["2026-01"]["peak"], 0.5)
        self.assertEqual(months["2026-01"]["count"], 2)
        self.assertEqual(months["2026-02"]["peak"], 0.7)
        self.assertEqual(months["2026-02"]["count"], 1)


class TestHourlyHistogram(unittest.TestCase):
    def test_always_24_buckets(self):
        self.assertEqual(len(hourly_histogram([], now=time.time())), 24)

    def test_average_utilization_per_hour(self):
        base_day = 100 * 86400.0
        hour_10 = base_day + 10 * 3600
        samples = [
            _s(hour_10, session=0.2),
            _s(hour_10 + 86400, session=0.4),
            _s(hour_10 + 2 * 86400, session=0.6),
        ]
        buckets = hourly_histogram(samples, now=hour_10 + 3 * 86400)
        self.assertAlmostEqual(buckets[10], 0.4, places=5)
        for i, v in enumerate(buckets):
            if i != 10:
                self.assertEqual(v, 0.0)


if __name__ == "__main__":
    unittest.main()
