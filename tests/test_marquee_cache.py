"""Scrolling marquees over a cached static layer.

The cost ticker and the news strip scroll at 25 fps. Repainting the whole
OSD for every frame cost ~1 s of CPU a minute on the GUI thread, almost all
of it redrawing parts that don't move. The overlay now paints the static
scene once into an image, and each frame only blits it and draws the
marquees at their current offset. These tests hold that to what a full
repaint shows, and check the static layer is redrawn whenever something on
it changes.

Uses Qt's offscreen platform so the tests run headless on CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtWidgets import QApplication

import claude_usage.overlay as overlay_mod
from claude_usage.collector import UsageStats
from claude_usage.news_fetcher import NewsItem
from claude_usage.overlay import VIEW_MODE_BARS, VIEW_MODE_GAUGE, UsageOverlay
from claude_usage.themes import THEMES
from claude_usage.ticker import TickerItem

_app = QApplication.instance() or QApplication([])

NOW = int(time.time())


def _stats(session: float = 0.3) -> UsageStats:
    items = [
        TickerItem(ts=NOW - i * 30, msg_id=f"m{i}", cost_usd=0.01 * (i % 7 + 1),
                   tool="Read+2" if i % 3 else "Bash", output_tokens=100 + i,
                   model="claude-opus-5-5")
        for i in range(40)
    ]
    st = UsageStats(session_utilization=session, session_reset=NOW + 3600,
                    weekly_utilization=0.6, weekly_reset=NOW + 86400,
                    ticker_items=items)
    st.news_items = [NewsItem(ts=NOW - 3600, url="https://example.com",
                              title="Claude Opus 5.5 is now available in the API and Claude Code")]
    return st


def _overlay(theme: str, mode: str, session: float = 0.3) -> UsageOverlay:
    ov = UsageOverlay({"theme": theme, "show_ticker": True, "show_news": True})
    ov.set_view_mode(mode)
    ov.update_stats(_stats(session))
    return ov


def _frame(ov: UsageOverlay) -> bytes:
    img = ov.grab().toImage()
    return bytes(img.constBits())


def _cached(ov: UsageOverlay) -> UsageOverlay:
    """Paint once in full, then let the static layer be built (it is, right
    after a full repaint, on the next event-loop turn)."""
    _frame(ov)
    _app.processEvents()
    assert ov._static_layer is not None
    return ov


VIEWS = [(t, VIEW_MODE_BARS) for t in sorted(THEMES)] + [("default", VIEW_MODE_GAUGE)]


@pytest.mark.parametrize("theme,mode", VIEWS)
def test_animated_frames_match_a_full_repaint(theme, mode):
    ov = _cached(_overlay(theme, mode))
    for _ in range(37):
        ov._advance_ticker()
    # A fresh overlay's first frame is a full repaint: what every frame was
    # before the cache.
    fresh = _overlay(theme, mode)
    fresh._ticker_offset, fresh._news_offset = ov._ticker_offset, ov._news_offset
    assert _frame(ov) == _frame(fresh)


def test_animation_frames_do_not_repaint_the_scene(monkeypatch):
    ov = _cached(_overlay("default", VIEW_MODE_BARS))
    calls = []
    real = ov._paint_scene
    monkeypatch.setattr(ov, "_paint_scene", lambda p: (calls.append(1), real(p))[1])
    for _ in range(10):
        ov._advance_ticker()
        _frame(ov)
        _app.processEvents()
    assert calls == []


def test_new_numbers_replace_the_cached_layer():
    ov = _cached(_overlay("default", VIEW_MODE_BARS, session=0.3))
    ov.update_stats(_stats(session=0.9))
    fresh = _overlay("default", VIEW_MODE_BARS, session=0.9)
    fresh._ticker_offset, fresh._news_offset = ov._ticker_offset, ov._news_offset
    assert _frame(ov) == _frame(fresh)


def test_static_layer_is_refreshed_for_countdowns(monkeypatch):
    # Reset countdowns ("2h 9m") are drawn on the static layer; it must not
    # stay cached for minutes while only the marquee moves.
    clock = [1000.0]
    monkeypatch.setattr(overlay_mod.time, "monotonic", lambda: clock[0])
    ov = _cached(_overlay("default", VIEW_MODE_BARS))
    calls = []
    real = ov._paint_scene
    monkeypatch.setattr(ov, "_paint_scene", lambda p: (calls.append(1), real(p))[1])
    clock[0] += overlay_mod.STATIC_LAYER_MAX_AGE_S - 1
    ov._advance_ticker()
    _frame(ov)
    assert calls == []
    clock[0] += 2
    ov._advance_ticker()
    _frame(ov)
    assert calls == [1]           # a full repaint...
    _app.processEvents()
    assert len(calls) == 2        # ...then the layer is rebuilt
    ov._advance_ticker()
    _frame(ov)
    assert len(calls) == 2
