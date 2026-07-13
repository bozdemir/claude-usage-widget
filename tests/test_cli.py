"""Tests for the CLI argument parser and dispatch."""

from __future__ import annotations

import json
import os
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

    def test_statusline_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--statusline"])
        self.assertTrue(ns.statusline)

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


class TestStatusline(unittest.TestCase):
    """`--statusline` — one compact line for Claude Code's statusLine setting."""

    def _run(self, stats):
        out = StringIO()
        with patch("claude_usage.cli.collect_all", return_value=stats), \
             patch("sys.stdout", out):
            rc = run_cli(["--statusline"])
        return rc, out.getvalue()

    def test_basic_line_shape(self):
        rc, out = self._run(_fake_stats())
        self.assertEqual(rc, 0)
        # exactly one line, no trailing blank lines
        self.assertEqual(out.count("\n"), 1)
        self.assertRegex(out, r"^S \d+% · W \d+% · \$\d+\.\d{2}")

    def test_rounding_matches_osd_truncation(self):
        # OSD renders int(pct*100) (truncation, not round) — mirror it.
        rc, out = self._run(UsageStats(session_utilization=0.589,
                                       weekly_utilization=0.101,
                                       today_cost=1.0))
        self.assertTrue(out.startswith("S 58% · W 10% · "))

    def test_cost_two_decimals(self):
        _, out = self._run(UsageStats(session_utilization=0.0,
                                      weekly_utilization=0.0,
                                      today_cost=3.2))
        self.assertIn("· $3.20", out)

    def test_scoped_bar_present_only_when_labelled(self):
        _, with_scoped = self._run(UsageStats(
            session_utilization=0.4, weekly_utilization=0.2, today_cost=1.0,
            scoped_utilization=0.55, scoped_label="Fable"))
        self.assertIn(" · Fable 55%", with_scoped)

        _, without = self._run(UsageStats(
            session_utilization=0.4, weekly_utilization=0.2, today_cost=1.0,
            scoped_utilization=0.0, scoped_label=""))
        self.assertNotIn("Fable", without)
        self.assertNotIn(" · ", without.strip()[without.strip().rindex("$"):])

    def test_graceful_degradation_no_last_known(self):
        # Rate-limited AND no last-known sample (session=weekly=0) -> '--%'
        # placeholders, but the locally-computed cost is still shown.
        rc, out = self._run(UsageStats(
            session_utilization=0.0, weekly_utilization=0.0, today_cost=2.5,
            rate_limit_error="Rate limited -- using last known values"))
        self.assertEqual(rc, 0)
        self.assertIn("S --% · W --%", out)
        self.assertIn("$2.50", out)

    def test_rate_limited_with_last_known_shows_numbers(self):
        # Rate-limited but restored last-known values -> real numbers, no '--'.
        _, out = self._run(UsageStats(
            session_utilization=0.42, weekly_utilization=0.18, today_cost=1.0,
            rate_limit_error="Rate limited -- using last known values"))
        self.assertIn("S 42% · W 18%", out)
        self.assertNotIn("--", out)

    def test_never_raises_and_returns_zero_on_empty_stats(self):
        rc, out = self._run(UsageStats())
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip())

    def test_statusline_does_not_launch_gui(self):
        import claude_usage.cli as cli
        with patch.object(cli, "collect_all", return_value=_fake_stats()), \
             patch.object(cli, "_launch_gui") as gui, \
             patch.object(cli, "_detach_into_background") as detach, \
             patch("sys.stdout", StringIO()), \
             patch("sys.argv", ["claude-usage", "--statusline"]):
            rc = cli.main()
        self.assertEqual(rc, 0)
        gui.assert_not_called()
        detach.assert_not_called()

    def test_statusline_ascii_fallback_on_unencodable_stdout(self):
        # A piped stream on a non-Latin Windows code page (e.g. cp932) can't
        # encode '·'. _print_statusline must degrade to ASCII, never raise.
        from claude_usage.cli import _print_statusline

        class _StrictStream:
            encoding = "cp932"

            def __init__(self):
                self.buf = []

            def write(self, s):
                s.encode(self.encoding)  # raises UnicodeEncodeError on '·'
                self.buf.append(s)

            def flush(self):
                pass

        stream = _StrictStream()
        data = {"session_utilization": 0.42, "weekly_utilization": 0.18,
                "today_cost": 3.2, "scoped_label": "", "rate_limit_error": ""}
        with patch("sys.stdout", stream):
            _print_statusline(data)  # must not raise
        out = "".join(stream.buf)
        self.assertNotIn("·", out)     # the middle dot is gone
        self.assertIn("|", out)             # ASCII separator used instead
        self.assertIn("$3.20", out)

    def test_statusline_with_detach_does_not_background(self):
        # --statusline --detach must print the line, not fork the GUI.
        import claude_usage.cli as cli
        with patch.object(cli, "collect_all", return_value=_fake_stats()), \
             patch.object(cli, "_launch_gui") as gui, \
             patch.object(cli, "_detach_into_background") as detach, \
             patch("sys.stdout", StringIO()), \
             patch("sys.argv", ["claude-usage", "--statusline", "--detach"]):
            rc = cli.main()
        self.assertEqual(rc, 0)
        detach.assert_not_called()
        gui.assert_not_called()


class TestInstanceLockPath(unittest.TestCase):
    """The single-instance guard lock must be per-user (not a shared /tmp name
    that lets one user block — or, after a hard kill, wedge — other users)."""

    def test_path_is_per_user_and_dot_lock(self):
        import getpass
        from claude_usage.cli import _instance_lock_path
        p = _instance_lock_path()
        self.assertTrue(p.endswith(".lock"))
        # Disambiguated by the current username (or pid as a last resort).
        user = "".join(c if c.isalnum() or c in "-_." else "_"
                       for c in getpass.getuser()) or "user"
        self.assertIn(user, os.path.basename(p))

    def test_prefers_xdg_runtime_dir_when_present(self):
        import tempfile
        from claude_usage.cli import _instance_lock_path
        runtime = tempfile.mkdtemp()
        try:
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}):
                self.assertTrue(_instance_lock_path().startswith(runtime))
        finally:
            os.rmdir(runtime)

    def test_falls_back_to_tempdir_when_xdg_missing(self):
        import tempfile
        from claude_usage.cli import _instance_lock_path
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(_instance_lock_path().startswith(tempfile.gettempdir()))


if __name__ == "__main__":
    unittest.main()
