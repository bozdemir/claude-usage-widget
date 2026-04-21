"""Long-range trend aggregations over the history.jsonl sample stream.

All functions are pure: they take a sample list and a reference timestamp,
and return primitive Python types. The widget and CLI render these into UI
/ JSON; the logic lives here so unit tests are easy.
"""

from __future__ import annotations

from datetime import datetime


def daily_heatmap(
    samples: list[dict],
    now: float,
    n_days: int = 90,
    key: str = "session",
) -> list[float]:
    """Return a fixed-length list of per-day peak utilization values.

    Index 0 is the oldest day, index -1 is today. Empty days are 0.0.
    """
    if n_days <= 0:
        return []
    buckets = [0.0] * n_days
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts <= 0 or ts > now:
            continue
        days_ago = int((now - ts) / 86400)
        if days_ago >= n_days:
            continue
        idx = n_days - 1 - days_ago  # today at the last index
        val = float(s.get(key, 0))
        if val > buckets[idx]:
            buckets[idx] = val
    return buckets


def monthly_summary(
    samples: list[dict],
    now: float,
    n_months: int = 6,
    key: str = "session",
) -> list[dict]:
    """Aggregate samples into the last n_months calendar months.

    Each entry: {"month": "YYYY-MM", "peak": float, "count": int}.
    Returned newest last; empty months are omitted.
    """
    if n_months <= 0 or not samples:
        return []

    ref = datetime.fromtimestamp(now)
    earliest_year = ref.year
    earliest_month = ref.month - n_months + 1
    while earliest_month <= 0:
        earliest_year -= 1
        earliest_month += 12

    buckets: dict[str, dict] = {}
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts <= 0:
            continue
        dt = datetime.fromtimestamp(ts)
        if (dt.year, dt.month) < (earliest_year, earliest_month):
            continue
        if (dt.year, dt.month) > (ref.year, ref.month):
            continue
        label = f"{dt.year:04d}-{dt.month:02d}"
        b = buckets.setdefault(label, {"month": label, "peak": 0.0, "count": 0})
        b["count"] += 1
        val = float(s.get(key, 0))
        if val > b["peak"]:
            b["peak"] = val

    return [buckets[k] for k in sorted(buckets)]


def hourly_histogram(
    samples: list[dict],
    now: float,
    key: str = "session",
) -> list[float]:
    """Return a 24-bucket list: average utilization at each hour of day.

    Only samples from the last 7 days are considered. Buckets with no
    samples are 0.0.
    """
    cutoff = now - 7 * 86400
    sums = [0.0] * 24
    counts = [0] * 24
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts < cutoff:
            continue
        # Use UTC hour directly from the timestamp to keep the bucketing
        # timezone-independent (tests supply synthetic timestamps).
        hour = int((ts // 3600) % 24)
        sums[hour] += float(s.get(key, 0))
        counts[hour] += 1
    return [
        sums[h] / counts[h] if counts[h] > 0 else 0.0
        for h in range(24)
    ]
