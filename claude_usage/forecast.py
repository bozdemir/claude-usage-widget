"""Burn-rate estimation and usage forecasting.

Pure module: given history samples (from `history.py`) and a current utilization
value, estimate how fast utilization is rising and when it would reach 100%.
All functions are side-effect free and do not touch the filesystem or clock
directly (the caller supplies `reset_ts`; we use `time.time()` only inside
`forecast_time_to_limit` for "now" and this can be patched in tests).
"""

import time


def calculate_burn_rate(
    samples: list[dict],
    scope: str,
    window_seconds: float = 900,
) -> float:
    """Average change in utilization per second over the last `window_seconds`.

    Uses a simple linear fit between the first and last sample in the window:
    (last_util - first_util) / (last_ts - first_ts). This is robust to
    irregular sampling and noisy intermediate points while still tracking
    the overall trend.

    Returns a fraction per second. For example 0.0001 means utilization is
    rising by +0.01% per second (≈ +0.36 percentage points per hour).

    Returns 0.0 if:
      - scope is not "session" or "weekly"
      - fewer than 2 samples fall inside the window
      - the span between first and last sample in the window is non-positive
      - utilization is flat or decreasing (we only care about burn, not cool-down)
    """
    if scope not in ("session", "weekly"):
        return 0.0
    if not samples or window_seconds <= 0:
        return 0.0

    # Samples may be unsorted; sort by timestamp so "first"/"last" are meaningful.
    try:
        ordered = sorted(samples, key=lambda s: float(s.get("ts", 0.0)))
    except (TypeError, ValueError):
        return 0.0

    if not ordered:
        return 0.0

    newest_ts = float(ordered[-1].get("ts", 0.0))
    cutoff = newest_ts - window_seconds
    in_window = [s for s in ordered if float(s.get("ts", 0.0)) >= cutoff]
    if len(in_window) < 2:
        return 0.0

    first, last = in_window[0], in_window[-1]
    try:
        t0 = float(first["ts"])
        t1 = float(last["ts"])
        u0 = float(first.get(scope, 0.0))
        u1 = float(last.get(scope, 0.0))
    except (KeyError, TypeError, ValueError):
        return 0.0

    dt = t1 - t0
    if dt <= 0:
        return 0.0

    rate = (u1 - u0) / dt
    if rate <= 0:
        return 0.0
    return rate


def forecast_time_to_limit(
    current_util: float,
    burn_rate: float,
    reset_ts: int,
) -> dict:
    """Estimate seconds until utilization reaches 1.0 at the given burn rate.

    Returns a dict with:
      - "hits_limit_in_seconds": int seconds until limit, or None if we can't
        project (no burn, already at/over limit, or bad inputs).
      - "will_hit_before_reset": True iff the projected hit-time is strictly
        before the window reset at `reset_ts`. False if we won't hit or if
        we'd hit exactly at or after reset.
    """
    result = {"hits_limit_in_seconds": None, "will_hit_before_reset": False}

    try:
        current_util = float(current_util)
        burn_rate = float(burn_rate)
        reset_ts = int(reset_ts)
    except (TypeError, ValueError):
        return result

    if burn_rate <= 0 or current_util >= 1.0:
        return result

    remaining = 1.0 - current_util
    seconds_to_limit = remaining / burn_rate
    if seconds_to_limit < 0:
        return result

    hits_in = int(seconds_to_limit)
    result["hits_limit_in_seconds"] = hits_in

    seconds_to_reset = reset_ts - time.time()
    result["will_hit_before_reset"] = hits_in < seconds_to_reset
    return result


def format_forecast(forecast: dict) -> str:
    """Human-readable summary of a `forecast_time_to_limit` result.

    Examples:
      "At current rate: 2h 30m to limit (before reset)"
      "At current rate: 45m to limit (after reset)"
      "At current rate: 12s to limit (before reset)"

    Returns "" if the forecast is None, missing data, or indicates no hit.
    """
    if not forecast:
        return ""
    hits_in = forecast.get("hits_limit_in_seconds")
    if hits_in is None:
        return ""
    try:
        secs = int(hits_in)
    except (TypeError, ValueError):
        return ""
    if secs < 0:
        return ""

    when = "before reset" if forecast.get("will_hit_before_reset") else "after reset"
    return f"At current rate: {_format_duration(secs)} to limit ({when})"


def _format_duration(seconds: int) -> str:
    """Format an integer second count as a compact H/M/S string.

    - >= 1h: "Xh Ym" (minutes omitted if zero, e.g. "3h")
    - >= 1m: "Xm"
    - else:  "Xs"
    """
    if seconds < 0:
        seconds = 0
    if seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"
