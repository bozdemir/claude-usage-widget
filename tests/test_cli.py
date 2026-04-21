"""Tests for the CLI argument parser and dispatch."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import asdict
from io import StringIO
from unittest.mock import patch

from claude_usage import __version__
from claude_usage.cli import build_parser, run_cli
from claude_usage.collector import UsageStats


def _fake_stats() -> UsageStats:
    return UsageStats(
        session_utilization=0.58,
        weekly_utilization=0.10,
        today_tokens=1_234_567,
        today_cost=12.34,
    )


class TestBuildParser(unittest.TestCase):
    def test_has_version_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--version"])
        self.assertTrue(ns.version)

    def test_json_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--json"])
        self.assertTrue(ns.json)

    def test_field_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--field", "session_utilization"])
        self.assertEqual(ns.field, "session_utilization")

    def test_once_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--once"])
        self.assertTrue(ns.once)

    def test_no_args_is_gui_mode(self):
        parser = build_parser()
        ns = parser.parse_args([])
        self.assertFalse(ns.json)
        self.assertIsNone(ns.field)


class TestRunCli(unittest.TestCase):
    def test_version_prints_version(self):
        out = StringIO()
        with patch("sys.stdout", out):
            rc = run_cli(["--version"])
        self.assertEqual(rc, 0)
        self.assertIn(__version__, out.getvalue())

    def test_json_emits_valid_json(self):
        out = StringIO()
        with patch("claude_usage.cli.collect_all", return_value=_fake_stats()), \
             patch("sys.stdout", out):
            rc = run_cli(["--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["session_utilization"], 0.58)
        self.assertEqual(data["today_cost"], 12.34)

    def test_field_emits_single_value(self):
        out = StringIO()
        with patch("claude_usage.cli.collect_all", return_value=_fake_stats()), \
             patch("sys.stdout", out):
            rc = run_cli(["--field", "session_utilization"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "0.58")

    def test_unknown_field_returns_error(self):
        err = StringIO()
        with patch("claude_usage.cli.collect_all", return_value=_fake_stats()), \
             patch("sys.stderr", err):
            rc = run_cli(["--field", "bogus_field"])
        self.assertEqual(rc, 2)
        self.assertIn("bogus_field", err.getvalue())


if __name__ == "__main__":
    unittest.main()
