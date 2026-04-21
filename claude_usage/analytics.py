"""Anomaly detection and cost-optimisation analysis over usage history.

Pure module — no I/O, no GUI, no network. Given a list of sample dicts from
history.py, produces structured reports the widget can render in the popup.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


MIN_SAMPLES = 7  # Need at least a week of data before we flag anomalies
Z_THRESHOLD = 2.0  # Standard deviations above the mean


@dataclass
class AnomalyReport:
    """Summary of a single-day anomaly check."""

    is_anomaly: bool = False
    today_usage: float = 0.0
    baseline: float = 0.0
    std_dev: float = 0.0
    z_score: float = 0.0
    ratio: float = 0.0
    reason: str = ""
    message: str = ""


def _daily_peaks(samples: list[dict], key: str = "session") -> list[float]:
    """Reduce a sample stream into one max value per calendar day."""
    by_day: dict[int, float] = {}
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts <= 0:
            continue
        day = int(ts // 86400)
        val = float(s.get(key, 0))
        if val > by_day.get(day, 0.0):
            by_day[day] = val
    return [by_day[d] for d in sorted(by_day)]


def detect_anomaly(
    samples: list[dict],
    today_usage: float,
    key: str = "session",
) -> AnomalyReport:
    """Return an AnomalyReport for today_usage against historical peaks."""
    rep = AnomalyReport(today_usage=today_usage)

    peaks = _daily_peaks(samples, key=key)
    history = peaks[:-1] if peaks else []

    if len(history) < MIN_SAMPLES:
        rep.reason = f"insufficient history ({len(history)} days < {MIN_SAMPLES})"
        return rep

    rep.baseline = statistics.fmean(history)
    rep.std_dev = statistics.pstdev(history) if len(history) > 1 else 0.0
    if rep.baseline > 0:
        rep.ratio = today_usage / rep.baseline
    if rep.std_dev > 0:
        rep.z_score = (today_usage - rep.baseline) / rep.std_dev

    # Flag anomaly: either z-score exceeds threshold, OR history is flat
    # (std_dev == 0) but today is >= 1.5x the baseline.
    is_spike = today_usage > rep.baseline and (
        rep.z_score >= Z_THRESHOLD
        or (rep.std_dev == 0 and rep.ratio >= 1.5)
    )
    if is_spike:
        rep.is_anomaly = True
        rep.message = (
            f"Today is {rep.ratio:.1f}x your {len(history)}-day average — "
            f"{int(today_usage * 100)}% vs {int(rep.baseline * 100)}% typical."
        )
    return rep


# ---------------------------------------------------------------------------
# Cost optimisation tips
# ---------------------------------------------------------------------------

LOW_CACHE_HIT_RATE = 0.60   # below this, suggest improving caching
OPUS_HEAVY_THRESHOLD = 0.80  # above this share of output from opus, suggest sonnet


def _cache_hit_rate(counts: dict) -> float:
    """Return cache_read / (cache_read + input) for one model's counts."""
    cr = float(counts.get("cache_read", 0) or 0)
    in_t = float(counts.get("input", 0) or 0)
    denom = cr + in_t
    return cr / denom if denom > 0 else 0.0


def generate_tips(
    by_model: dict,
    week_cost: float,
    cache_savings: float,
) -> list[str]:
    """Return 0-3 short actionable tips based on the week's usage profile."""
    tips: list[str] = []
    if not by_model:
        return tips

    total_output = sum(
        float(c.get("output", 0) or 0) for c in by_model.values()
    )

    # Tip 1: cache hit rate
    hit_rates = [
        _cache_hit_rate(c) for c in by_model.values()
        if float(c.get("input", 0) or 0) + float(c.get("cache_read", 0) or 0) > 10_000
    ]
    if hit_rates:
        avg_hit = sum(hit_rates) / len(hit_rates)
        if avg_hit < LOW_CACHE_HIT_RATE and week_cost > 0:
            potential = week_cost * (0.85 - avg_hit) * 0.9
            if potential >= 1.0:
                tips.append(
                    f"Cache hit rate is {int(avg_hit * 100)}%. "
                    f"Raising to ~85% could save ~${potential:.0f}/week."
                )

    # Tip 2: model mix
    if total_output > 100_000:
        opus_output = sum(
            float(c.get("output", 0) or 0)
            for m, c in by_model.items() if "opus" in m
        )
        opus_share = opus_output / total_output if total_output else 0.0
        if opus_share >= OPUS_HEAVY_THRESHOLD and week_cost > 20.0:
            potential = week_cost * 0.70 * (opus_share - 0.5) * 0.4
            if potential >= 1.0:
                tips.append(
                    f"Opus handles {int(opus_share * 100)}% of your output. "
                    f"Shifting easy tasks to Sonnet could save ~${potential:.0f}/week."
                )

    # Tip 3: celebrate savings
    if cache_savings > 0 and week_cost > 0 and cache_savings >= week_cost * 2:
        tips.append(
            f"Cache already saves ${cache_savings:.0f}/week — "
            f"{cache_savings / max(week_cost, 1):.1f}x your bill. Keep it up."
        )

    return tips[:3]
