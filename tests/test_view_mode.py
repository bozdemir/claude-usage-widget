"""Tests for the OSD view-mode switch (bars ↔ gauge).

Uses Qt's offscreen platform so the tests run headless on CI.
"""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from claude_usage.overlay import (
    BASE_HEIGHT,
    GAUGE_HEIGHT,
    TICKER_STRIP_HEIGHT,
    VIEW_MODE_BARS,
    VIEW_MODE_GAUGE,
    VIEW_MODES,
    UsageOverlay,
)


_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


class TestViewMode(unittest.TestCase):
    def setUp(self) -> None:
        _get_app()

    def test_default_is_bars(self) -> None:
        ov = UsageOverlay({})
        self.assertEqual(ov.view_mode(), VIEW_MODE_BARS)

    def test_config_can_preselect_gauge(self) -> None:
        ov = UsageOverlay({"osd_view_mode": VIEW_MODE_GAUGE})
        self.assertEqual(ov.view_mode(), VIEW_MODE_GAUGE)

    def test_invalid_config_value_falls_back_to_bars(self) -> None:
        ov = UsageOverlay({"osd_view_mode": "nonsense"})
        self.assertEqual(ov.view_mode(), VIEW_MODE_BARS)

    def test_set_view_mode_resizes_widget(self) -> None:
        ov = UsageOverlay({"show_ticker": True})
        bars_h = ov.height()
        # Bars + ticker height ≈ BASE_HEIGHT + TICKER_STRIP_HEIGHT.
        self.assertEqual(bars_h, BASE_HEIGHT + TICKER_STRIP_HEIGHT)
        ov.set_view_mode(VIEW_MODE_GAUGE)
        self.assertEqual(ov.height(), GAUGE_HEIGHT)
        ov.set_view_mode(VIEW_MODE_BARS)
        self.assertEqual(ov.height(), bars_h)

    def test_set_view_mode_ignores_invalid(self) -> None:
        ov = UsageOverlay({})
        ov.set_view_mode("rainbow")
        self.assertEqual(ov.view_mode(), VIEW_MODE_BARS)

    def test_all_modes_are_in_public_tuple(self) -> None:
        self.assertIn(VIEW_MODE_BARS, VIEW_MODES)
        self.assertIn(VIEW_MODE_GAUGE, VIEW_MODES)


if __name__ == "__main__":
    unittest.main()
