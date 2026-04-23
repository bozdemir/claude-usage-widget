"""Bridge between :class:`claude_usage.collector.UsageStats` and the
field shape the handoff paint modules consume.

The handoff's `paint_osd(p, rect, data, scale)` reads fields like
``data.session_pct`` (0..1) and ``data.session_reset_min`` — a
bookkeeping shape, not our canonical ``UsageStats``. This module
produces a plain struct with exactly those names, plus the derived
values (live tokens in ``k``, ticker-tier quartile bucketing).
"""

from __future__ import annotations

import os
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
    # Pixels scrolled so far on the ticker marquee. Skins that animate
    # their ticker (terminal, strip, ...) modulo this against the total
    # strip width; static skins ignore it.
    ticker_offset: float = 0.0


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


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _plan_label(subscription_type: str) -> str:
    sub = (subscription_type or "").lower()
    if not sub:
        return "pay-as-you-go"
    return f"{sub.capitalize()} plan"


def _format_weekly_reset_label(ts: int) -> str:
    if ts <= 0:
        return ""
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%a %I:%M %p").lstrip("0")


def build_popup_data(stats, now: float | None = None):
    """Project ``UsageStats`` onto the handoff's PopupData schema.

    Avoids a top-level import of ``popup_data`` so callers that don't need
    the popup shape (e.g. the OSD-only paint dispatch) pay nothing for it.
    """
    from .popup_data import PopupData, CostRow, ProjectRow, TickerItem, ActiveSessionRow
    from claude_usage.pricing import MODEL_PRICING

    now_ts = now if now is not None else time.time()
    osd = from_usage_stats(stats, now=now_ts)

    by_model = dict(getattr(stats, "today_by_model_detailed", {}) or {})
    # Cost rows — one per (category) in the largest-spend model, mirroring
    # the layout the design lays out (input / output / cache read / cache write).
    cost_rows: list = []
    primary_model = ""
    if by_model:
        # Pick the model with the biggest total contribution so the cost
        # card shows the one the user is actually burning budget on.
        ranked = sorted(
            by_model.items(),
            key=lambda kv: sum(int(kv[1].get(k, 0) or 0) for k in ("input", "output", "cache_read", "cache_creation")),
            reverse=True,
        )
        primary_model, counts = ranked[0]
        rates = MODEL_PRICING.get(primary_model) or MODEL_PRICING["claude-sonnet-4-6"]
        per_m = 1_000_000.0
        spec = [
            ("input",        "input_tokens",           "input"),
            ("output",       "output_tokens",          "output"),
            ("cache read",   "cache_read_tokens",      "cache_read"),
            ("cache write",  "cache_creation_tokens",  "cache_creation"),
        ]
        for label, _legacy, key in spec:
            tokens = int(counts.get(key, 0) or 0)
            if tokens <= 0:
                continue
            rate = rates[key]
            value = tokens * rate / per_m
            cost_rows.append(CostRow(
                label=label,
                tokens=_fmt_tokens(tokens),
                rate=f"${rate:.2f}/M",
                value_usd=float(value),
            ))

    top_projects = [
        ProjectRow(name=name, tokens=_fmt_tokens(int(tok) if tok else 0))
        for name, tok in list((getattr(stats, "today_by_project", {}) or {}).items())[:5]
    ]

    # Ticker items for the popup are the same shape osd.ticker_items has,
    # but handoff's popup module imports its own TickerItem dataclass. Copy
    # across so the popup painter's isinstance/field access is happy.
    popup_ticker = [
        TickerItem(cost_usd=it.cost_usd, tool_label=it.tool_label, tier=it.tier)
        for it in osd.ticker_items
    ]

    forecast = getattr(stats, "session_forecast", {}) or {}
    forecast_text = ""
    if isinstance(forecast, dict) and forecast.get("eta_seconds"):
        secs = int(forecast["eta_seconds"])
        hours, rem = divmod(max(secs, 0), 3600)
        minutes = rem // 60
        if hours:
            forecast_text = f"limit in {hours}h {minutes}m"
        else:
            forecast_text = f"limit in {minutes}m"

    return PopupData(
        session_pct=osd.session_pct,
        weekly_pct=osd.weekly_pct,
        session_reset_min=osd.session_reset_min,
        weekly_reset_hrs=osd.weekly_reset_hrs,
        weekly_reset_min=osd.weekly_reset_min,
        subagent_count=osd.subagent_count,
        is_live=osd.is_live,
        live_tok_per_min=osd.live_tok_per_min,
        ticker_items=popup_ticker,
        plan=_plan_label(getattr(stats, "subscription_type", "")),
        weekly_reset_label=_format_weekly_reset_label(int(getattr(stats, "weekly_reset", 0))),
        session_forecast=forecast_text,
        spark_5h=list(getattr(stats, "session_history", []) or []),
        spark_7d=list(getattr(stats, "weekly_history", []) or []),
        heat_90d=list(getattr(stats, "daily_heatmap", []) or []),
        heat_52w=list(getattr(stats, "yearly_heatmap", []) or []),
        cost_today_usd=float(getattr(stats, "today_cost", 0.0) or 0.0),
        cache_saved_usd=float(getattr(stats, "cache_savings", 0.0) or 0.0),
        cost_model=primary_model or "unknown",
        cost_rows=cost_rows,
        top_projects=top_projects,
        tips=list(getattr(stats, "tips", []) or []),
        weekly_report=str(getattr(stats, "weekly_report_text", "") or ""),
        active_sessions=[
            ActiveSessionRow(
                cwd=str(s.get("cwd", "?")).replace(os.path.expanduser("~"), "~"),
                duration=_format_session_duration(s, now_ts),
            )
            for s in (getattr(stats, "active_sessions", []) or [])
        ],
    )


def _format_session_duration(session: dict, now_ts: float) -> str:
    started = session.get("startedAt", 0) or 0
    if started <= 0:
        return ""
    # startedAt is in milliseconds — convert and compute elapsed seconds.
    elapsed = max(0, int(now_ts - started / 1000))
    hours, rem = divmod(elapsed, 3600)
    minutes = rem // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def from_usage_stats(
    stats, now: float | None = None, ticker_offset: float = 0.0,
) -> SkinData:
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
        ticker_offset=float(ticker_offset),
    )
