"""Tests for the OSD view-mode switch (bars ↔ gauge).

Uses Qt's offscreen platform so the tests run headless on CI.
"""

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtCore import Qt
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


class TestAlwaysOnTop(unittest.TestCase):
    """The OSD can be unpinned to act as a background desktop widget (#13)."""

    def setUp(self) -> None:
        _get_app()

    def test_default_is_on_top(self) -> None:
        ov = UsageOverlay({})
        self.assertTrue(ov.is_always_on_top())
        self.assertTrue(ov.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(ov.windowFlags() & Qt.BypassWindowManagerHint)

    def test_config_can_disable(self) -> None:
        ov = UsageOverlay({"osd_always_on_top": False})
        self.assertFalse(ov.is_always_on_top())
        # Both the stays-on-top and the WM-bypass hints are dropped so the WM
        # can stack it behind focused windows.
        self.assertFalse(ov.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertFalse(ov.windowFlags() & Qt.BypassWindowManagerHint)

    def test_toggle_round_trips(self) -> None:
        ov = UsageOverlay({})
        ov.set_always_on_top(False)
        self.assertFalse(ov.is_always_on_top())
        self.assertFalse(ov.windowFlags() & Qt.WindowStaysOnTopHint)
        ov.set_always_on_top(True)
        self.assertTrue(ov.is_always_on_top())
        self.assertTrue(ov.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_frameless_and_tool_always_present(self) -> None:
        for on in (True, False):
            ov = UsageOverlay({"osd_always_on_top": on})
            self.assertTrue(ov.windowFlags() & Qt.FramelessWindowHint)
            self.assertTrue(ov.windowFlags() & Qt.Tool)

    def test_window_type_follows_pin_state(self) -> None:
        """_NET_WM_WINDOW_TYPE_NOTIFICATION makes X11 WMs stack a window above
        normal ones, so it has to track the pin state. Setting it
        unconditionally kept the OSD on top even when unpinned — dropping the
        StaysOnTop/Bypass flags alone was not enough."""
        pinned = UsageOverlay({"osd_always_on_top": True})
        self.assertTrue(
            pinned.testAttribute(Qt.WA_X11NetWmWindowTypeNotification)
        )
        unpinned = UsageOverlay({"osd_always_on_top": False})
        self.assertFalse(
            unpinned.testAttribute(Qt.WA_X11NetWmWindowTypeNotification)
        )

    def test_toggle_round_trips_window_type(self) -> None:
        ov = UsageOverlay({})
        ov.set_always_on_top(False)
        self.assertFalse(ov.testAttribute(Qt.WA_X11NetWmWindowTypeNotification))
        ov.set_always_on_top(True)
        self.assertTrue(ov.testAttribute(Qt.WA_X11NetWmWindowTypeNotification))

    def test_toggle_keeps_translucency_and_mac_hint(self) -> None:
        """setWindowFlags re-creates the native window and can drop attributes
        with native effects — losing translucency paints an opaque black box."""
        ov = UsageOverlay({})
        ov.set_always_on_top(False)
        self.assertTrue(ov.testAttribute(Qt.WA_TranslucentBackground))
        self.assertTrue(ov.testAttribute(Qt.WA_MacAlwaysShowToolWindow))


if __name__ == "__main__":
    unittest.main()
