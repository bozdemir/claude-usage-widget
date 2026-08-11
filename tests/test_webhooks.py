"""Tests for webhook dispatch logic."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from claude_usage.webhooks import WebhookDispatcher


class TestWebhookDispatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.sender = MagicMock(side_effect=lambda url, payload: self.sent.append((url, payload)))
        self.cfg = {
            "threshold_crossed": "https://example.com/threshold",
            "daily_report":      "https://example.com/daily",
            "anomaly":           "https://example.com/anomaly",
        }

    def _wait_for_dispatch(self) -> None:
        # The dispatcher fires in a daemon thread; give it a moment to run.
        for _ in range(20):
            if self.sent:
                return
            time.sleep(0.01)

    def test_threshold_event_posts_to_threshold_url(self):
        d = WebhookDispatcher(self.cfg, sender=self.sender)
        d.fire("threshold_crossed", {"scope": "session", "value": 0.85})
        self._wait_for_dispatch()
        self.assertEqual(len(self.sent), 1)
        url, payload = self.sent[0]
        self.assertEqual(url, "https://example.com/threshold")
        self.assertEqual(payload["event"], "threshold_crossed")
        self.assertEqual(payload["value"], 0.85)

    def test_unknown_event_is_noop(self):
        d = WebhookDispatcher(self.cfg, sender=self.sender)
        d.fire("not_a_real_event", {})
        self._wait_for_dispatch()
        self.assertFalse(self.sent)

    def test_event_without_url_is_noop(self):
        d = WebhookDispatcher({"daily_report": "https://x/"}, sender=self.sender)
        d.fire("threshold_crossed", {})
        self._wait_for_dispatch()
        self.assertFalse(self.sent)

    def test_every_advertised_event_actually_fires(self):
        """Every event the widget fires anywhere must pass the KNOWN_EVENTS
        gate. budget_projection and burn_alert shipped in 0.11.0 but were
        never added to KNOWN_EVENTS, so fire() silently dropped them and the
        advertised webhooks never sent a single request."""
        advertised = (
            "threshold_crossed",
            "daily_report",
            "anomaly",
            "budget_projection",
            "burn_alert",
        )
        cfg = {ev: f"https://example.com/{ev}" for ev in advertised}
        d = WebhookDispatcher(cfg, sender=self.sender)
        for ev in advertised:
            d.fire(ev, {"probe": ev})
        for _ in range(50):
            if len(self.sent) >= len(advertised):
                break
            time.sleep(0.01)
        fired = sorted(payload["event"] for _, payload in self.sent)
        self.assertEqual(fired, sorted(advertised))

    def test_sender_failure_does_not_raise(self):
        bad_sender = MagicMock(side_effect=RuntimeError("network down"))
        d = WebhookDispatcher(self.cfg, sender=bad_sender)
        # Must swallow the exception — UI shouldn't crash on webhook failure
        d.fire("threshold_crossed", {"value": 1})
        # Give the thread a moment — shouldn't raise
        time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
