"""Bridge between :class:`claude_usage.collector.UsageStats` and the
field shape the handoff paint modules consume.

The handoff's `paint_osd(p, rect, data, scale)` reads fields like
``data.session_pct`` (0..1) and ``data.session_reset_min`` — a
bookkeeping shape, not our canonical ``UsageStats``. This module
produces a plain struct with exactly those names, plus the derived
values (live tokens in ``k``, ticker-tier quartile bucketing).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class SkinTickerItem:
    """Ticker entry shaped for the skin painters (tier + short label)."""

    cost_usd: float
    tool_label: str
    tier: int  # 0 = dim, 1 = link, 2 = warn, 3 = crit


@dataclass
class SkinData:
    """The field layout every ``paint_osd`` in :mod:`claude_usage.skins` expects."""

    session_pct: float = 0.0
    session_reset_min: int = 0
    weekly_pct: float = 0.0
    weekly_reset_hrs: int = 0
    weekly_reset_min: int = 0
    live_tok_per_min: float = 0.0  # in thousands (e.g. 10.5 means 10.5k)
    is_live: bool = False
    subagent_count: int = 0
    ticker_items: list[SkinTickerItem] = field(default_factory=list)


def _quartile_thresholds(items: Sequence) -> tuple[float, float, float]:
    """Re-implement the overlay.py quartile bucketing here to avoid an
    import cycle (skins package is loaded by overlay.py itself).
    """
    if len(items) < 4:
        return (0.0, float("inf"), float("inf"))
    costs = sorted(float(it.cost_usd) for it in items)
    n = len(costs)
    return (costs[n // 4], costs[n // 2], costs[3 * n // 4])


def _tier_for(cost: float, thresholds: tuple[float, float, float]) -> int:
    cool, warm, hot = thresholds
    if cost >= hot:
        return 3
    if cost >= warm:
        return 2
    if cost >= cool:
        return 1
    return 0


def from_usage_stats(stats, now: float | None = None) -> SkinData:
    """Project a ``UsageStats`` snapshot onto the handoff's field layout."""
    now_ts = now if now is not None else time.time()

    session_reset_min = 0
    if getattr(stats, "session_reset", 0) > 0:
        s_left = max(0, int(stats.session_reset - now_ts))
        session_reset_min = s_left // 60

    weekly_reset_hrs = 0
    weekly_reset_min = 0
    if getattr(stats, "weekly_reset", 0) > 0:
        w_left = max(0, int(stats.weekly_reset - now_ts))
        weekly_reset_hrs = w_left // 3600
        weekly_reset_min = (w_left % 3600) // 60

    live = getattr(stats, "live_activity", None)
    tpm = float(getattr(live, "tokens_per_minute", 0.0) or 0.0)
    is_live = bool(getattr(live, "is_live", False))

    ticker_raw = list(getattr(stats, "ticker_items", []) or [])
    thresholds = _quartile_thresholds(ticker_raw)
    ticker_items = [
        SkinTickerItem(
            cost_usd=float(it.cost_usd),
            tool_label=str(it.tool) or "turn",
            tier=_tier_for(float(it.cost_usd), thresholds),
        )
        for it in ticker_raw
    ]

    return SkinData(
        session_pct=max(0.0, min(1.0, float(getattr(stats, "session_utilization", 0.0)))),
        session_reset_min=session_reset_min,
        weekly_pct=max(0.0, min(1.0, float(getattr(stats, "weekly_utilization", 0.0)))),
        weekly_reset_hrs=weekly_reset_hrs,
        weekly_reset_min=weekly_reset_min,
        live_tok_per_min=tpm / 1000.0,
        is_live=is_live,
        subagent_count=int(getattr(stats, "active_subagent_count", 0) or 0),
        ticker_items=ticker_items,
    )
