"""Anthropic weekday reduced-limit "peak" window awareness.

Anthropic applies a stricter session limit during a weekday morning window
(roughly 5-11 AM US Pacific). This module reports whether a given instant falls
inside that window and, if so, produces a short human hint plus the time until
the window's next boundary.

Pure module — no GUI, no network, no file I/O, and no reading of the real clock:
the caller passes in `now`. It is also dependency-free. For the default Pacific
zone the UTC offset is computed by a self-contained US-DST implementation that
never imports ``zoneinfo`` (Windows ships no system tz database). Only a custom
``peak_timezone`` falls back to stdlib ``zoneinfo``, and any failure there
degrades gracefully to "not in peak" rather than raising.

All config is read off a plain dict with ``.get(key, default)`` so the module
stays decoupled from ``claude_usage.config``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass
class PeakStatus:
    """Result of a peak-window evaluation.

    Attributes:
        in_peak: True iff ``now`` is inside the reduced-limit window.
        hint: Short human string when in peak (e.g. "Reduced 5h limit until
            11 AM PT"); empty string otherwise or when disabled/unavailable.
        minutes_until_change: Whole minutes until the window's next boundary —
            the current window's end when in peak, else the next window's start.
            0 when the feature is disabled or the timezone is unavailable.
        next_change_local: The local (timezone-aware) datetime of that boundary,
            or None when disabled/unavailable.
    """

    in_peak: bool
    hint: str
    minutes_until_change: int
    next_change_local: datetime | None


_DEFAULT_TZ = "America/Los_Angeles"


def _nth_sunday(year: int, month: int, n: int) -> int:
    """Return the day-of-month of the ``n``-th Sunday of ``month``."""
    first = date(year, month, 1)
    # date.weekday(): Monday=0 .. Sunday=6. Days to first Sunday:
    first_sunday = 1 + (6 - first.weekday()) % 7
    return first_sunday + (n - 1) * 7


def _pacific_utcoffset(dt: datetime) -> timedelta:
    """US Pacific UTC offset for the instant ``dt`` (self-contained, no tz db).

    DST (-07:00) runs from the 2nd Sunday of March at 02:00 local (== 10:00
    UTC) up to the 1st Sunday of November at 02:00 local daylight time (==
    09:00 UTC); standard time (-08:00) applies otherwise. ``dt`` is treated as
    UTC (a naive value is assumed to already be UTC).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    year = dt.year
    spring = datetime(year, 3, _nth_sunday(year, 3, 2), 10, 0, tzinfo=timezone.utc)
    fall = datetime(year, 11, _nth_sunday(year, 11, 1), 9, 0, tzinfo=timezone.utc)
    if spring <= dt < fall:
        return timedelta(hours=-7)
    return timedelta(hours=-8)


def _as_utc(now: datetime) -> datetime:
    """Normalize ``now`` to a timezone-aware UTC datetime.

    A naive value is interpreted as UTC (matching the collector, which passes
    ``datetime.now(timezone.utc)``); an aware value is converted.
    """
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _localize(now: datetime, tzname: str):
    """Convert ``now`` to local time for ``tzname``.

    Returns a ``(local_datetime, tz_token)`` tuple, or None if the timezone is
    unavailable. The default Pacific zone uses the self-contained offset and
    never touches ``zoneinfo``; any other zone resolves through stdlib
    ``zoneinfo`` with all failures swallowed.
    """
    try:
        utc = _as_utc(now)
    except Exception:
        return None

    if tzname == _DEFAULT_TZ:
        off = _pacific_utcoffset(utc)
        return utc.astimezone(timezone(off)), "PT"

    try:
        from zoneinfo import ZoneInfo

        local = utc.astimezone(ZoneInfo(tzname))
        return local, (local.tzname() or "local")
    except Exception:
        return None


def _fmt_hour(hour: int) -> str:
    """Render a 24-hour ``hour`` as a 12-hour label, e.g. 11 -> "11 AM"."""
    period = "AM" if hour < 12 else "PM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    return f"{h12} {period}"


def is_peak_window(
    now: datetime,
    *,
    timezone: str,
    start_hour: int,
    end_hour: int,
    weekdays: list[int],
) -> bool:
    """Return True iff ``now`` falls inside the configured peak window.

    ``end_hour`` is exclusive. ``weekdays`` uses ``datetime.weekday()``
    convention (Monday=0 .. Sunday=6). Returns False if the timezone is
    unavailable.
    """
    localized = _localize(now, timezone)
    if localized is None:
        return False
    local, _ = localized
    return local.weekday() in weekdays and start_hour <= local.hour < end_hour


def _next_change(local: datetime, in_peak: bool, start_hour: int,
                 end_hour: int, weekdays: list[int]):
    """Compute the next boundary datetime for ``local``.

    When in peak the boundary is today's window end; otherwise it is the start
    of the next window at or after ``local``. Returns None if no future start
    exists (e.g. an empty ``weekdays`` list).
    """
    if in_peak:
        return local.replace(hour=end_hour, minute=0, second=0, microsecond=0)

    for offset in range(0, 8):
        day = local + timedelta(days=offset)
        cand = day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if cand > local and cand.weekday() in weekdays:
            return cand
    return None


def peak_status(now: datetime, config: dict) -> PeakStatus:
    """Evaluate the peak window for ``now`` using values from ``config``.

    Config keys (with defaults): ``peak_awareness_enabled`` (True),
    ``peak_timezone`` ('America/Los_Angeles'), ``peak_start_hour`` (5),
    ``peak_end_hour`` (11, exclusive), ``peak_weekdays`` ([0,1,2,3,4]).
    """
    if not config.get("peak_awareness_enabled", True):
        return PeakStatus(False, "", 0, None)

    tzname = config.get("peak_timezone", _DEFAULT_TZ)
    start_hour = config.get("peak_start_hour", 5)
    end_hour = config.get("peak_end_hour", 11)
    weekdays = config.get("peak_weekdays", [0, 1, 2, 3, 4])

    localized = _localize(now, tzname)
    if localized is None:
        return PeakStatus(False, "", 0, None)
    local, token = localized

    in_peak = local.weekday() in weekdays and start_hour <= local.hour < end_hour

    nxt = _next_change(local, in_peak, start_hour, end_hour, weekdays)
    if nxt is None:
        minutes = 0
    else:
        minutes = int((nxt - local).total_seconds() // 60)
        if minutes < 0:
            minutes = 0

    if in_peak:
        hint = f"Reduced 5h limit until {_fmt_hour(end_hour)} {token}"
    else:
        hint = ""

    return PeakStatus(in_peak, hint, minutes, nxt)
