import unittest
from unittest.mock import patch

from claude_usage.forecast import (
    calculate_burn_rate,
    forecast_time_to_limit,
    format_forecast,
)


class TestCalculateBurnRate(unittest.TestCase):
    def test_rising_utilization_returns_positive_rate(self):
        # 10% increase over 100 seconds = 0.001 per second
        samples = [
            {"ts": 1000.0, "session": 0.50, "weekly": 0.10},
            {"ts": 1050.0, "session": 0.55, "weekly": 0.10},
            {"ts": 1100.0, "session": 0.60, "weekly": 0.10},
        ]
        rate = calculate_burn_rate(samples, "session", window_seconds=900)
        self.assertAlmostEqual(rate, 0.001, places=6)

    def test_falling_utilization_returns_zero(self):
        samples = [
            {"ts": 1000.0, "session": 0.80, "weekly": 0.10},
            {"ts": 1050.0, "session": 0.70, "weekly": 0.10},
            {"ts": 1100.0, "session": 0.60, "weekly": 0.10},
        ]
        self.assertEqual(calculate_burn_rate(samples, "session"), 0.0)

    def test_flat_utilization_returns_zero(self):
        samples = [
            {"ts": 1000.0, "session": 0.42, "weekly": 0.10},
            {"ts": 1050.0, "session": 0.42, "weekly": 0.10},
            {"ts": 1100.0, "session": 0.42, "weekly": 0.10},
        ]
        self.assertEqual(calculate_burn_rate(samples, "session"), 0.0)

    def test_empty_samples_returns_zero(self):
        self.assertEqual(calculate_burn_rate([], "session"), 0.0)

    def test_single_sample_returns_zero(self):
        samples = [{"ts": 1000.0, "session": 0.5, "weekly": 0.1}]
        self.assertEqual(calculate_burn_rate(samples, "session"), 0.0)

    def test_bad_scope_returns_zero(self):
        samples = [
            {"ts": 1000.0, "session": 0.1, "weekly": 0.1},
            {"ts": 1100.0, "session": 0.2, "weekly": 0.2},
        ]
        self.assertEqual(calculate_burn_rate(samples, "bogus"), 0.0)

    def test_weekly_scope_independent_of_session(self):
        samples = [
            {"ts": 1000.0, "session": 0.90, "weekly": 0.10},
            {"ts": 1100.0, "session": 0.50, "weekly": 0.20},
        ]
        # Session is falling, should be 0. Weekly rising, should be positive.
        self.assertEqual(calculate_burn_rate(samples, "session"), 0.0)
        weekly = calculate_burn_rate(samples, "weekly")
        self.assertAlmostEqual(weekly, 0.001, places=6)

    def test_samples_outside_window_ignored(self):
        # Window looks at last 100s. Older samples should be dropped.
        samples = [
            {"ts": 0.0, "session": 0.99, "weekly": 0.0},  # ancient
            {"ts": 1000.0, "session": 0.10, "weekly": 0.0},
            {"ts": 1100.0, "session": 0.20, "weekly": 0.0},
        ]
        rate = calculate_burn_rate(samples, "session", window_seconds=100)
        self.assertAlmostEqual(rate, 0.001, places=6)

    def test_zero_timespan_returns_zero(self):
        samples = [
            {"ts": 1000.0, "session": 0.1, "weekly": 0.1},
            {"ts": 1000.0, "session": 0.5, "weekly": 0.1},
        ]
        self.assertEqual(calculate_burn_rate(samples, "session"), 0.0)

    def test_unsorted_samples_handled(self):
        samples = [
            {"ts": 1100.0, "session": 0.60, "weekly": 0.0},
            {"ts": 1000.0, "session": 0.50, "weekly": 0.0},
            {"ts": 1050.0, "session": 0.55, "weekly": 0.0},
        ]
        rate = calculate_burn_rate(samples, "session", window_seconds=900)
        self.assertAlmostEqual(rate, 0.001, places=6)


class TestForecastTimeToLimit(unittest.TestCase):
    def test_rising_projects_hit_time(self):
        # At 50% with 0.001/s burn, should hit 100% in ~500s.
        with patch("claude_usage.forecast.time.time", return_value=1000.0):
            result = forecast_time_to_limit(0.5, 0.001, reset_ts=2000)
        self.assertEqual(result["hits_limit_in_seconds"], 500)
        self.assertTrue(result["will_hit_before_reset"])

    def test_already_at_limit_returns_none(self):
        result = forecast_time_to_limit(1.0, 0.001, reset_ts=2000)
        self.assertIsNone(result["hits_limit_in_seconds"])
        self.assertFalse(result["will_hit_before_reset"])

    def test_over_limit_returns_none(self):
        result = forecast_time_to_limit(1.2, 0.001, reset_ts=2000)
        self.assertIsNone(result["hits_limit_in_seconds"])

    def test_zero_burn_rate_returns_none(self):
        result = forecast_time_to_limit(0.5, 0.0, reset_ts=2000)
        self.assertIsNone(result["hits_limit_in_seconds"])
        self.assertFalse(result["will_hit_before_reset"])

    def test_negative_burn_rate_returns_none(self):
        result = forecast_time_to_limit(0.5, -0.01, reset_ts=2000)
        self.assertIsNone(result["hits_limit_in_seconds"])

    def test_hits_after_reset(self):
        # 500s to limit, but reset is in 100s → after reset.
        with patch("claude_usage.forecast.time.time", return_value=1000.0):
            result = forecast_time_to_limit(0.5, 0.001, reset_ts=1100)
        self.assertEqual(result["hits_limit_in_seconds"], 500)
        self.assertFalse(result["will_hit_before_reset"])

    def test_hits_exactly_at_reset_counts_as_after(self):
        # 500s to limit, reset in exactly 500s → strict < check should be False.
        with patch("claude_usage.forecast.time.time", return_value=1000.0):
            result = forecast_time_to_limit(0.5, 0.001, reset_ts=1500)
        self.assertEqual(result["hits_limit_in_seconds"], 500)
        self.assertFalse(result["will_hit_before_reset"])

    def test_low_utilization_with_slow_burn(self):
        # 10% used, 0.0001/s → 90% remaining / 0.0001 = 9000 seconds.
        with patch("claude_usage.forecast.time.time", return_value=0.0):
            result = forecast_time_to_limit(0.1, 0.0001, reset_ts=20000)
        self.assertEqual(result["hits_limit_in_seconds"], 9000)
        self.assertTrue(result["will_hit_before_reset"])


class TestFormatForecast(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(format_forecast(None), "")

    def test_empty_dict_returns_empty(self):
        self.assertEqual(format_forecast({}), "")

    def test_no_hit_returns_empty(self):
        forecast = {"hits_limit_in_seconds": None, "will_hit_before_reset": False}
        self.assertEqual(format_forecast(forecast), "")

    def test_hours_and_minutes_before_reset(self):
        forecast = {"hits_limit_in_seconds": 2 * 3600 + 30 * 60, "will_hit_before_reset": True}
        self.assertEqual(format_forecast(forecast), "At current rate: 2h 30m to limit (before reset)")

    def test_exact_hours_omit_minutes(self):
        forecast = {"hits_limit_in_seconds": 3 * 3600, "will_hit_before_reset": True}
        self.assertEqual(format_forecast(forecast), "At current rate: 3h to limit (before reset)")

    def test_minutes_only(self):
        forecast = {"hits_limit_in_seconds": 45 * 60, "will_hit_before_reset": False}
        self.assertEqual(format_forecast(forecast), "At current rate: 45m to limit (after reset)")

    def test_seconds_only(self):
        forecast = {"hits_limit_in_seconds": 42, "will_hit_before_reset": True}
        self.assertEqual(format_forecast(forecast), "At current rate: 42s to limit (before reset)")


class TestAlreadyAtLimit(unittest.TestCase):
    """Integration: end-to-end covering the "already at limit" user story."""

    def test_end_to_end_at_limit_produces_no_forecast_text(self):
        samples = [
            {"ts": 1000.0, "session": 0.98, "weekly": 0.5},
            {"ts": 1100.0, "session": 1.00, "weekly": 0.5},
        ]
        rate = calculate_burn_rate(samples, "session")
        forecast = forecast_time_to_limit(1.00, rate, reset_ts=9999)
        self.assertIsNone(forecast["hits_limit_in_seconds"])
        self.assertEqual(format_forecast(forecast), "")


if __name__ == "__main__":
    unittest.main()
