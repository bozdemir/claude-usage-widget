"""Issue #25 — "Show cost ticker" must be honoured by the self-drawn skins.

Before the fix the toggle only worked for the 5 built-in themes: skins painted
``data.ticker_items`` unconditionally, and ``update_stats`` restarted the
marquee timer on the next refresh whenever the skin declared WANTS_TICKER —
so on terminal/dashboard/hud/receipt/brutalist the strip paused for a few
seconds and then scrolled on as if nothing happened.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from claude_usage.collector import UsageStats
from claude_usage.overlay import UsageOverlay
from claude_usage.skins import SKIN_MODULES
from claude_usage.skins._adapter import SkinData

_app = QApplication.instance() or QApplication([])

TICKER_SKINS = sorted(n for n, m in SKIN_MODULES.items() if getattr(m, "WANTS_TICKER", False))


def _stats_with_ticker() -> UsageStats:
    """A real UsageStats carrying three per-turn cost items."""
    items = [
        SimpleNamespace(cost_usd=0.012, tool="Read", ts=0.0),
        SimpleNamespace(cost_usd=0.156, tool="Bash", ts=1.0),
        SimpleNamespace(cost_usd=0.480, tool="Edit", ts=2.0),
    ]
    stats = UsageStats(session_utilization=0.4, weekly_utilization=0.7)
    stats.ticker_items = items
    return stats


def _render_bytes(mod, data: SkinData) -> bytes:
    w, h = int(mod.METRICS["osd_width"]), int(mod.METRICS["osd_height"])
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    mod.paint_osd(p, QRectF(0, 0, w, h), data, 1.0)
    p.end()
    return bytes(img.constBits())


@pytest.mark.parametrize("skin", TICKER_SKINS)
def test_refresh_does_not_restart_marquee_when_ticker_disabled(skin):
    """The exact #25 symptom: disable → pause → next refresh → scrolling again."""
    ov = UsageOverlay({"theme": skin, "show_ticker": True})
    ov.update_stats(_stats_with_ticker())
    assert ov._ticker_timer.isActive(), "sanity: enabled skin ticker animates"

    ov.set_ticker_enabled(False)
    assert not ov._ticker_timer.isActive()

    ov.update_stats(_stats_with_ticker())  # the periodic refresh
    assert not ov._ticker_timer.isActive(), (
        "update_stats restarted the marquee even though the ticker is off"
    )


@pytest.mark.parametrize("skin", TICKER_SKINS)
def test_disabled_ticker_hands_skin_no_items(skin):
    """With the ticker off, the SkinData the overlay builds must carry no
    ticker items — that's what makes every skin's marquee draw nothing."""
    ov = UsageOverlay({"theme": skin, "show_ticker": False})
    ov.update_stats(_stats_with_ticker())
    data = ov._skin_data_for_paint()
    assert data.ticker_items == []

    ov.set_ticker_enabled(True)
    data = ov._skin_data_for_paint()
    assert len(data.ticker_items) == 3


@pytest.mark.parametrize("skin", TICKER_SKINS)
def test_skin_paints_no_ticker_strip_when_given_no_items(skin):
    """Render-level guarantee: an empty ticker list paints byte-identically to
    a panel that never had a ticker — nothing leaks onto the strip."""
    mod = SKIN_MODULES[skin]
    base = SkinData(session_pct=0.4, weekly_pct=0.7, weekly_reset_hrs=3)
    empty = SkinData(session_pct=0.4, weekly_pct=0.7, weekly_reset_hrs=3,
                     ticker_items=[], ticker_offset=123.0)
    assert _render_bytes(mod, base) == _render_bytes(mod, empty)


def test_toggle_still_works_for_builtin_theme():
    """Regression guard for the classic path, which was already correct."""
    ov = UsageOverlay({"theme": "default", "show_ticker": True})
    ov.update_stats(_stats_with_ticker())
    assert ov._ticker_timer.isActive()
    ov.set_ticker_enabled(False)
    ov.update_stats(_stats_with_ticker())
    assert not ov._ticker_timer.isActive()
