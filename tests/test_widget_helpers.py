"""Tests for pure helper functions in claude_usage.widget.

Only tests helpers that don't need a QApplication — the full-widget tests
would require Qt's offscreen platform plugin and a ton of scaffolding.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from claude_usage.widget import _format_tokens, _prettify_project_name, _short_model_name


class TestFormatTokens(unittest.TestCase):
    def test_small(self):
        self.assertEqual(_format_tokens(42), "42")

    def test_thousands(self):
        self.assertEqual(_format_tokens(5400), "5.4K")

    def test_millions(self):
        self.assertEqual(_format_tokens(1_234_567), "1.2M")


class TestShortModelName(unittest.TestCase):
    def test_strips_prefix(self):
        self.assertEqual(_short_model_name("claude-opus-4-7"), "opus-4-7")

    def test_strips_date_suffix(self):
        self.assertEqual(_short_model_name("claude-haiku-4-5-20251001"), "haiku-4-5")


class TestPrettifyProjectName(unittest.TestCase):
    def test_empty_returns_placeholder(self):
        self.assertEqual(_prettify_project_name(""), "?")

    def test_unix_home_dashed_becomes_tilde(self):
        with patch("os.path.expanduser", return_value="/home/alice"):
            self.assertEqual(
                _prettify_project_name("-home-alice-project-x"),
                "~/project-x",
            )

    def test_unix_home_exact_match(self):
        with patch("os.path.expanduser", return_value="/home/alice"):
            self.assertEqual(_prettify_project_name("-home-alice"), "~")

    def test_windows_home_dashed_becomes_tilde(self):
        # Real Claude Code encoding on Windows: every non-alphanumeric path
        # component character (colon AND backslash) becomes a dash, so
        # "C:\\Users\\alice\\project-x" → "C--Users-alice-project-x".
        with patch("os.path.expanduser", return_value="C:\\Users\\alice"):
            out = _prettify_project_name("C--Users-alice-project-x")
            self.assertEqual(out, "~/project-x")

    def test_windows_home_exact_match(self):
        with patch("os.path.expanduser", return_value="C:\\Users\\alice"):
            self.assertEqual(_prettify_project_name("C--Users-alice"), "~")

    def test_unrelated_path_passes_through(self):
        with patch("os.path.expanduser", return_value="/home/alice"):
            self.assertEqual(
                _prettify_project_name("-tmp-scratch"),
                "-tmp-scratch",
            )


if __name__ == "__main__":
    unittest.main()
