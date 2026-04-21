"""Tests for the localhost JSON usage API server."""

from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock

from claude_usage.api_server import UsageAPIServer
from claude_usage.collector import UsageStats


def _get(url: str, timeout: float = 1.0) -> tuple[int, dict | str]:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class TestUsageAPIServer(unittest.TestCase):
    def setUp(self) -> None:
        self.get_stats = MagicMock(return_value=UsageStats(
            session_utilization=0.58, weekly_utilization=0.10,
            today_cost=42.0,
        ))
        self.server = UsageAPIServer(
            host="127.0.0.1", port=0, get_stats=self.get_stats,
        )
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self) -> None:
        self.server.stop()

    def test_healthz_returns_200(self):
        status, body = _get(self.base + "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("ok"), True)

    def test_usage_returns_stats_as_json(self):
        status, body = _get(self.base + "/usage")
        self.assertEqual(status, 200)
        self.assertEqual(body["session_utilization"], 0.58)
        self.assertEqual(body["today_cost"], 42.0)

    def test_unknown_path_404s(self):
        status, _ = _get(self.base + "/does-not-exist")
        self.assertEqual(status, 404)

    def test_only_binds_localhost(self):
        self.assertIn(self.server.host, ("127.0.0.1", "localhost"))

    def test_get_stats_callable_invoked_on_request(self):
        _get(self.base + "/usage")
        self.assertTrue(self.get_stats.called)


if __name__ == "__main__":
    unittest.main()
