"""Tests for the pure monthly-budget projection module (claude_usage/budget.py)."""

from __future__ import annotations

import calendar
from datetime import datetime

import pytest

from claude_usage.budget import (
    BudgetStatus,
    evaluate_budget,
    format_budget_line,
    month_bounds,
    project_month_end,
    should_notify,
)


# ---------------------------------------------------------------------------
# 1. inactive when no budget configured
# ---------------------------------------------------------------------------

def test_inactive_when_budget_zero():
    now = datetime(2026, 7, 8, 12, 0, 0)
    status = evaluate_budget(month_spend=12.40, monthly_budget_usd=0.0, now_dt=now)
    assert status.active is False
    assert status.budget == 0.0
    assert status.pct_of_budget == 0.0
    assert status.projected_pct == 0.0
    assert status.over_projected is False
    assert format_budget_line(status) == ""


def test_inactive_when_budget_negative():
    now = datetime(2026, 7, 8, 12, 0, 0)
    status = evaluate_budget(month_spend=5.0, monthly_budget_usd=-10.0, now_dt=now)
    assert status.active is False
    assert format_budget_line(status) == ""


# ---------------------------------------------------------------------------
# 2. linear projection: half the month, $25 -> ~$50
# ---------------------------------------------------------------------------

def test_project_month_end_half_month():
    seconds_in_month = 30 * 86400
    seconds_elapsed = seconds_in_month / 2
    projected = project_month_end(25.0, seconds_elapsed, seconds_in_month)
    assert projected == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# 3. guard seconds_elapsed <= 0 (no ZeroDivision)
# ---------------------------------------------------------------------------

def test_project_month_end_zero_elapsed():
    assert project_month_end(13.0, 0.0, 30 * 86400) == 13.0


def test_project_month_end_negative_elapsed():
    assert project_month_end(13.0, -5.0, 30 * 86400) == 13.0


# ---------------------------------------------------------------------------
# 4. over_projected threshold + notify_ratio
# ---------------------------------------------------------------------------

def test_over_projected_true_when_projected_exceeds_budget():
    # Jan 1 noon: half a day into a 31-day month -> huge projection.
    now = datetime(2026, 1, 1, 12, 0, 0)
    status = evaluate_budget(month_spend=5.0, monthly_budget_usd=50.0, now_dt=now)
    assert status.projected_eom > 50.0
    assert status.over_projected is True


def test_over_projected_false_when_under_budget():
    # Halfway through the month, spent $10, budget $50 -> projected ~$20.
    now = datetime(2026, 4, 16, 0, 0, 0)  # April has 30 days; 15 days elapsed
    status = evaluate_budget(month_spend=10.0, monthly_budget_usd=50.0, now_dt=now)
    assert status.projected_eom < 50.0
    assert status.over_projected is False


def test_notify_ratio_trips_earlier():
    # Projected just under budget but above 0.9 * budget.
    now = datetime(2026, 4, 16, 0, 0, 0)  # 15 of 30 days elapsed
    # spend such that projected ~= 0.95 * budget = 47.5 -> month_spend ~= 23.75
    status_full = evaluate_budget(23.75, 50.0, now, notify_ratio=1.0)
    status_early = evaluate_budget(23.75, 50.0, now, notify_ratio=0.9)
    assert status_full.projected_eom == pytest.approx(47.5, rel=1e-3)
    assert status_full.over_projected is False  # below full budget
    assert status_early.over_projected is True  # above 0.9 * budget = 45


# ---------------------------------------------------------------------------
# 5. month_bounds uses calendar.monthrange (28/29/30/31)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "year,month,expected_days",
    [
        (2026, 2, 28),   # non-leap Feb
        (2024, 2, 29),   # leap Feb
        (2026, 4, 30),   # 30-day month
        (2026, 1, 31),   # 31-day month
    ],
)
def test_month_bounds_days_in_month(year, month, expected_days):
    now = datetime(year, month, 10, 6, 0, 0)
    month_start, days_in_month, seconds_elapsed, seconds_in_month = month_bounds(now)
    assert days_in_month == expected_days
    assert days_in_month == calendar.monthrange(year, month)[1]
    assert month_start == datetime(year, month, 1, 0, 0, 0)
    assert seconds_in_month == expected_days * 86400
    # 9 full days + 6 hours elapsed
    assert seconds_elapsed == pytest.approx(9 * 86400 + 6 * 3600)


def test_month_bounds_days_elapsed_field():
    now = datetime(2026, 7, 8, 12, 0, 0)
    status = evaluate_budget(10.0, 50.0, now)
    assert status.days_in_month == 31
    assert status.days_elapsed == 8  # July 8th


# ---------------------------------------------------------------------------
# 6. format_budget_line rendering
# ---------------------------------------------------------------------------

def test_format_budget_line_two_decimals():
    now = datetime(2026, 4, 16, 0, 0, 0)  # 15 of 30 days
    status = evaluate_budget(12.40, 50.0, now)
    line = format_budget_line(status)
    assert line == "$12.40 / $50.00 this month · projected $24.80"


def test_format_budget_line_rounds_money():
    now = datetime(2026, 4, 16, 0, 0, 0)
    status = evaluate_budget(10.0, 33.333, now)
    line = format_budget_line(status)
    assert line.startswith("$10.00 / $33.33 this month · projected $")


# ---------------------------------------------------------------------------
# 7. should_notify debounce
# ---------------------------------------------------------------------------

def test_should_notify_first_time_in_month():
    now = datetime(2026, 1, 1, 12, 0, 0)
    status = evaluate_budget(5.0, 50.0, now)
    assert status.over_projected is True
    assert should_notify(status, already_notified_month="", current_month_key="2026-01") is True


def test_should_notify_false_when_already_notified():
    now = datetime(2026, 1, 1, 12, 0, 0)
    status = evaluate_budget(5.0, 50.0, now)
    assert should_notify(status, already_notified_month="2026-01", current_month_key="2026-01") is False


def test_should_notify_true_new_month_after_prior():
    now = datetime(2026, 1, 1, 12, 0, 0)
    status = evaluate_budget(5.0, 50.0, now)
    assert should_notify(status, already_notified_month="2025-12", current_month_key="2026-01") is True


def test_should_notify_false_when_not_over_projected():
    now = datetime(2026, 4, 16, 0, 0, 0)
    status = evaluate_budget(10.0, 50.0, now)
    assert status.over_projected is False
    assert should_notify(status, already_notified_month="", current_month_key="2026-04") is False


def test_should_notify_false_when_inactive():
    now = datetime(2026, 4, 16, 0, 0, 0)
    status = evaluate_budget(10.0, 0.0, now)
    assert status.active is False
    assert should_notify(status, already_notified_month="", current_month_key="2026-04") is False


# ---------------------------------------------------------------------------
# extra: BudgetStatus fields wired sanely
# ---------------------------------------------------------------------------

def test_budget_status_fields():
    now = datetime(2026, 4, 16, 0, 0, 0)  # 15 of 30 days
    status = evaluate_budget(12.40, 50.0, now)
    assert isinstance(status, BudgetStatus)
    assert status.month_spend == 12.40
    assert status.budget == 50.0
    assert status.active is True
    assert status.remaining == pytest.approx(50.0 - 12.40)
    assert status.pct_of_budget == pytest.approx(12.40 / 50.0)
    assert status.projected_pct == pytest.approx(status.projected_eom / 50.0)
