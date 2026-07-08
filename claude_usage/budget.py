"""Monthly budget cap and linear end-of-month spend projection.

Pure module — no I/O, no network, no GUI, no direct clock access. The caller
supplies both the already-computed month-to-date spend (`month_spend`, a float
in USD) and the reference `now` datetime; this module does only calendar math
and linear pro-rata projection on top of them.

The projection is deliberately simple: assume spend continues at the average
rate observed so far this month, and extrapolate to the month's final second.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BudgetStatus:
    """Snapshot of month-to-date spend against a configured monthly cap."""

    month_spend: float
    budget: float
    projected_eom: float
    pct_of_budget: float
    projected_pct: float
    over_projected: bool
    remaining: float
    days_elapsed: int
    days_in_month: int
    active: bool


def month_bounds(now_dt: datetime) -> tuple:
    """Return calendar bounds for the month containing `now_dt`.

    Returns a 4-tuple::

        (month_start_dt, days_in_month, seconds_elapsed, seconds_in_month)

    - ``month_start_dt`` is midnight on the 1st of the month.
    - ``days_in_month`` comes from :func:`calendar.monthrange`.
    - ``seconds_elapsed`` is the number of seconds from ``month_start_dt`` to
      ``now_dt``.
    - ``seconds_in_month`` is ``days_in_month * 86400``.
    """
    days_in_month = calendar.monthrange(now_dt.year, now_dt.month)[1]
    month_start = now_dt.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    seconds_elapsed = (now_dt - month_start).total_seconds()
    seconds_in_month = days_in_month * 86400
    return month_start, days_in_month, seconds_elapsed, seconds_in_month


def project_month_end(
    month_spend: float,
    seconds_elapsed: float,
    seconds_in_month: float,
) -> float:
    """Linearly extrapolate month-to-date spend to the month's end.

    Assumes spend continues at the observed average rate::

        projected = month_spend * (seconds_in_month / seconds_elapsed)

    Guards against division by zero: when ``seconds_elapsed <= 0`` (the very
    first moment of a month) we have no rate to project, so we return
    ``month_spend`` unchanged.
    """
    if seconds_elapsed <= 0:
        return month_spend
    return month_spend * (seconds_in_month / seconds_elapsed)


def evaluate_budget(
    month_spend: float,
    monthly_budget_usd: float,
    now_dt: datetime,
    notify_ratio: float = 1.0,
) -> BudgetStatus:
    """Build a :class:`BudgetStatus` from month-to-date spend and a cap.

    When ``monthly_budget_usd <= 0`` the feature is disabled: the returned
    status has ``active=False`` and all ratio/projection-derived fields zeroed.

    ``over_projected`` is True when the projected end-of-month spend reaches or
    exceeds ``monthly_budget_usd * notify_ratio`` (``notify_ratio`` below 1.0
    trips the warning earlier than the full cap).
    """
    month_start, days_in_month, seconds_elapsed, seconds_in_month = month_bounds(
        now_dt
    )
    days_elapsed = now_dt.day

    if monthly_budget_usd <= 0:
        return BudgetStatus(
            month_spend=month_spend,
            budget=monthly_budget_usd if monthly_budget_usd > 0 else 0.0,
            projected_eom=0.0,
            pct_of_budget=0.0,
            projected_pct=0.0,
            over_projected=False,
            remaining=0.0,
            days_elapsed=days_elapsed,
            days_in_month=days_in_month,
            active=False,
        )

    projected_eom = project_month_end(
        month_spend, seconds_elapsed, seconds_in_month
    )
    pct_of_budget = month_spend / monthly_budget_usd
    projected_pct = projected_eom / monthly_budget_usd
    over_projected = projected_eom >= monthly_budget_usd * notify_ratio

    return BudgetStatus(
        month_spend=month_spend,
        budget=monthly_budget_usd,
        projected_eom=projected_eom,
        pct_of_budget=pct_of_budget,
        projected_pct=projected_pct,
        over_projected=over_projected,
        remaining=monthly_budget_usd - month_spend,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        active=True,
    )


def format_budget_line(status: BudgetStatus) -> str:
    """Render a one-line budget summary, or ``""`` when the feature is off.

    Example::

        "$12.40 / $50.00 this month · projected $47.10"
    """
    if not status.active:
        return ""
    return (
        f"${status.month_spend:.2f} / ${status.budget:.2f} this month "
        f"· projected ${status.projected_eom:.2f}"
    )


def should_notify(
    status: BudgetStatus,
    already_notified_month: str,
    current_month_key: str,
) -> bool:
    """Pure debounce for the once-per-month budget notification.

    Returns True only when the budget is active, the projection is over the
    (ratio-adjusted) cap, and we have not already notified for this month
    (``already_notified_month != current_month_key``).
    """
    if not status.active or not status.over_projected:
        return False
    return already_notified_month != current_month_key
