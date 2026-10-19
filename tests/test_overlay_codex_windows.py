"""Codex accounts with only one rate-limit window (PR #33).

Plans without a 5h limit report just the weekly window. The OSD must then
draw and size for that single Codex row in every view and theme, follow the
window set as it changes live, and in gauge view keep each Codex ring under
the Claude ring it mirrors (5h under Session, 7d under Weekly).

Uses Qt's offscreen platform so the tests run headless on CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtWidgets import QApplication

from claude_usage.collector import UsageStats
from claude_usage.overlay import (
    CODEX_GAUGE_ROW_HEIGHT,
    VIEW_MODE_BARS,
    VIEW_MODE_GAUGE,
    UsageOverlay,
)
from claude_usage.skins import SKIN_MODULES

_app = QApplication.instance() or QApplication([])

WINDOWS = {
    "both": dict(codex_available=True),
    "weekly": dict(codex_available=True, codex_has_session=False),
    "session": dict(codex_available=True, codex_has_weekly=False),
    "off": dict(codex_available=False),
}

VIEWS = [("default", VIEW_MODE_BARS), ("default", VIEW_MODE_GAUGE)] + [
    (name, VIEW_MODE_BARS) for name in sorted(SKIN_MODULES)
]


def _stats(windows: str) -> UsageStats:
    now = int(time.time())
    return UsageStats(
        session_utilization=0.24, weekly_utilization=0.70,
        session_reset=now + 3 * 3600, weekly_reset=now + 71 * 3600,
        codex_session_utilization=0.61, codex_session_reset=now + 179 * 60,
        codex_weekly_utilization=0.48, codex_weekly_reset=now + 119 * 3600,
        **WINDOWS[windows],
    )


def _overlay(theme: str, mode: str, windows: str) -> UsageOverlay:
    ov = UsageOverlay({"theme": theme})
    ov.set_view_mode(mode)
    ov.update_stats(_stats(windows))
    return ov


@pytest.mark.parametrize("theme,mode", VIEWS)
def test_single_window_reserves_one_codex_row(theme, mode):
    off = _overlay(theme, mode, "off").height()
    both = _overlay(theme, mode, "both").height()
    weekly = _overlay(theme, mode, "weekly").height()
    session = _overlay(theme, mode, "session").height()
    assert weekly == session
    if mode == VIEW_MODE_GAUGE:
        # Gauge puts both Codex rings in one row, so one window costs the same.
        assert weekly == both > off
    else:
        assert weekly == off + (both - off) // 2


@pytest.mark.parametrize("theme,mode", VIEWS)
def test_window_set_changes_resize_the_live_overlay(theme, mode):
    ov = _overlay(theme, mode, "off")
    for windows in ("both", "weekly", "session", "both", "off", "weekly", "off"):
        ov.update_stats(_stats(windows))
        assert ov.height() == _overlay(theme, mode, windows).height(), windows


def _distinct_colours(img, x0: int, x1: int, y0: int, y1: int) -> int:
    return len({img.pixel(x, y) for x in range(x0, x1) for y in range(y0, y1)})


def _codex_gauge_halves(windows: str) -> tuple[int, int]:
    """Distinct colours in the left / right column of the Codex ring row."""
    img = _overlay("default", VIEW_MODE_GAUGE, windows).grab().toImage()
    w, h = img.width(), img.height()
    top = CODEX_GAUGE_ROW_HEIGHT + 10
    return (
        _distinct_colours(img, 12, w // 2 - 4, top, h - 12),
        _distinct_colours(img, w // 2 + 4, w - 12, top, h - 12),
    )


def test_gauge_draws_both_codex_rings():
    left, right = _codex_gauge_halves("both")
    assert left > 1 and right > 1


def test_gauge_puts_lone_weekly_ring_under_weekly():
    left, right = _codex_gauge_halves("weekly")
    assert left == 1, "left column (under Session) should be empty"
    assert right > 1


def test_gauge_puts_lone_session_ring_under_session():
    left, right = _codex_gauge_halves("session")
    assert left > 1
    assert right == 1, "right column (under Weekly) should be empty"
