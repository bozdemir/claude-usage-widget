"""Data shape the popup painter expects.

This module is a DOCUMENTATION + TYPE reference. Nothing here needs to
be imported at runtime — but Claude Code should extend the existing
`claude_usage.collector.UsageStats` to include these fields (or adapt
them in an adapter function before passing to `paint_popup`).

The existing OSD painter already works with the legacy `UsageStats`
shape. Only the POPUP needs the richer fields below.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostRow:
    label: str         # "INPUT", "OUTPUT", "CACHE READ", "CACHE WRITE"
    tokens: str        # human-readable token count, e.g. "120K", "4.2M"
    rate: str          # cost rate as string, e.g. "$3/M"
    value_usd: float   # dollar value of this row


@dataclass
class ProjectRow:
    name: str          # project identifier
    tokens: str        # human-readable, e.g. "2.1M"


@dataclass
class ActiveSessionRow:
    """One live Claude Code session shown under the Active Sessions section."""
    cwd: str           # project directory (may be "[redacted]" for screenshots)
    duration: str      # human-readable time-since-start ("47m", "2h 14m")


@dataclass
class TickerItem:
    cost_usd: float
    tool_label: str
    tier: int          # 0..3 quartile (dim, link, warn, crit)


@dataclass
class PopupData:
    # --- OSD fields (already in existing UsageStats) --------------
    session_pct: float              # 0..1
    weekly_pct: float               # 0..1
    session_reset_min: int
    weekly_reset_hrs: int
    weekly_reset_min: int
    subagent_count: int = 0
    is_live: bool = False
    live_tok_per_min: float = 0.0
    ticker_items: list[TickerItem] = field(default_factory=list)

    # --- POPUP-only fields (add to UsageStats or build adapter) ---
    plan: str = "Pro · $17/mo"
    weekly_reset_label: str = "Mon 9:00"    # human-readable

    # forecast / projection line shown under session bar
    session_forecast: str = "limit at 3:14pm"

    # sparkline series — 60 values for 5h (5-min buckets), 7 for 7d
    spark_5h: list[float] = field(default_factory=list)
    spark_7d: list[float] = field(default_factory=list)

    # 90-day daily heat (values 0..1)
    heat_90d: list[float] = field(default_factory=list)
    # 52-week × 7-day heat (52*7 = 364 values, 0..1)
    heat_52w: list[float] = field(default_factory=list)

    # cost section
    cost_today_usd: float = 0.0
    cache_saved_usd: float = 0.0
    cost_model: str = "claude-sonnet-4"
    cost_rows: list[CostRow] = field(default_factory=list)

    # lists
    top_projects: list[ProjectRow] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    weekly_report: str = ""
    active_sessions: list[ActiveSessionRow] = field(default_factory=list)


def adapt_from_usage_stats(stats, extra: dict | None = None) -> PopupData:
    """Build a PopupData from the existing UsageStats + a dict of extras
    the collector now provides (sparklines, heatmaps, cost breakdown).

    Implement this in claude_usage/collector.py so the popup widget can
    simply do:

        data = adapt_from_usage_stats(self._stats, self._popup_extras)
        direction.paint_popup(painter, self.rect(), data, self._scale)
    """
    extra = extra or {}
    return PopupData(
        session_pct=stats.session_pct,
        weekly_pct=stats.weekly_pct,
        session_reset_min=stats.session_reset_min,
        weekly_reset_hrs=stats.weekly_reset_hrs,
        weekly_reset_min=stats.weekly_reset_min,
        subagent_count=getattr(stats, "subagent_count", 0),
        is_live=getattr(stats, "is_live", False),
        live_tok_per_min=getattr(stats, "live_tok_per_min", 0.0),
        ticker_items=getattr(stats, "ticker_items", []),
        **extra,
    )
