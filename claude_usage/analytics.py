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
