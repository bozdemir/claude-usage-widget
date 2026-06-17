"""Tests for the OSD refresh-status dot (green / grey / red).

Uses Qt's offscreen platform so the tests run headless on CI.
"""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from claude_usage.collector import UsageStats
from claude_usage.overlay import (
    VIEW_MODE_BARS,
    VIEW_MODE_GAUGE,
    UsageOverlay,
    _hex_to_qcolor,
)

_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


class TestStatusDot(unittest.TestCase):
    def setUp(self) -> None:
        _get_app()

    def test_starts_in_updating_state(self) -> None:
        ov = UsageOverlay({})
        self.assertEqual(ov._status, "updating")

    def test_set_updating(self) -> None:
        ov = UsageOverlay({})
        ov.update_stats(UsageStats())  # -> ok
        self.assertEqual(ov._status, "ok")
        ov.set_updating()
        self.assertEqual(ov._status, "updating")

    def test_clean_poll_is_ok(self) -> None:
        ov = UsageOverlay({})
        ov.update_stats(UsageStats(session_utilization=0.3))
        self.assertEqual(ov._status, "ok")

    def test_errored_poll_is_error(self) -> None:
        ov = UsageOverlay({})
        ov.update_stats(UsageStats(rate_limit_error="Rate limited -- using last known values"))
        self.assertEqual(ov._status, "error")

    def test_recovers_from_error_on_next_clean_poll(self) -> None:
        ov = UsageOverlay({})
        ov.update_stats(UsageStats(rate_limit_error="boom"))
        self.assertEqual(ov._status, "error")
        ov.update_stats(UsageStats(session_utilization=0.1))
        self.assertEqual(ov._status, "ok")

    def test_status_color_maps_to_theme(self) -> None:
        ov = UsageOverlay({})
        theme = ov._theme

        ov._status = "error"
        self.assertEqual(ov._status_color().name(), _hex_to_qcolor(theme["crit"]).name())
        ov._status = "updating"
        self.assertEqual(ov._status_color().name(), _hex_to_qcolor(theme["text_dim"]).name())
        ov._status = "ok"
        expected = _hex_to_qcolor(theme.get("live_indicator", "#4ade80")).name()
        self.assertEqual(ov._status_color().name(), expected)

    def test_paint_does_not_crash_in_either_view(self) -> None:
        # grab() runs the full paintEvent (incl. _draw_status_dot) to a pixmap.
        for mode in (VIEW_MODE_BARS, VIEW_MODE_GAUGE):
            ov = UsageOverlay({"osd_view_mode": mode})
            ov.update_stats(UsageStats(rate_limit_error="x"))  # error -> red dot
            pm = ov.grab()
            self.assertFalse(pm.isNull())


if __name__ == "__main__":
    unittest.main()
