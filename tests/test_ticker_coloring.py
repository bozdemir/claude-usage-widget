"""Unit tests for the OSD ticker's quartile-based colour thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from claude_usage.overlay import _ticker_quartile_thresholds
from claude_usage.ticker import TickerItem


def _item(cost: float) -> TickerItem:
    return TickerItem(
        ts=0.0, msg_id=f"m{cost}", cost_usd=cost, tool="", output_tokens=1,
        model="claude-sonnet-4-6",
    )


def test_returns_sentinels_for_short_buffers():
    # Fewer than 4 items — quartile math isn't meaningful; collapse to cool.
    cool, warm, hot = _ticker_quartile_thresholds([_item(0.1), _item(0.5), _item(1.0)])
    assert cool == 0.0
    assert warm == float("inf")
    assert hot == float("inf")


def test_empty_buffer_collapses_cleanly():
    cool, warm, hot = _ticker_quartile_thresholds([])
    assert cool == 0.0
    assert warm == float("inf")
    assert hot == float("inf")


def test_quartile_thresholds_on_uniform_spread():
    # 8 items from 0.01 .. 0.08 — quartiles land at indices 2, 4, 6.
    items = [_item(c / 100) for c in range(1, 9)]
    cool, warm, hot = _ticker_quartile_thresholds(items)
    assert cool == 0.03  # items[2]
    assert warm == 0.05  # items[4]
    assert hot == 0.07   # items[6]


def test_quartile_splits_narrow_band_into_four_buckets():
    """Opus Claude Code reality: all turns cluster in a narrow dollar band.
    Quartile thresholds still split them so the tape is visually varied."""
    items = [_item(c) for c in (0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.22)]
    cool, warm, hot = _ticker_quartile_thresholds(items)
    # With fixed $0.10/$1.00 tiers every item would be 'warm'. Quartiles
    # spread them across four tiers.
    assert cool < warm < hot
    # And the range is tight.
    assert (hot - cool) < 0.10
