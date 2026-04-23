"""Tests for claude_usage.ai_report."""

from __future__ import annotations

import json
import os
import time

import pytest

from claude_usage.ai_report import (
    CACHE_TTL_SECONDS,
    WeeklyReport,
    build_prompt,
    generate_report,
    load_cached_report,
    save_cached_report,
)


def test_weekly_report_freshness():
    r = WeeklyReport(text="hi", generated_at=time.time())
    assert r.is_fresh()
    r_old = WeeklyReport(text="hi", generated_at=time.time() - CACHE_TTL_SECONDS - 100)
    assert not r_old.is_fresh()


def test_save_and_load_round_trip(tmp_path):
    report = WeeklyReport(text="test report", generated_at=time.time())
    save_cached_report(str(tmp_path), report)
    loaded = load_cached_report(str(tmp_path))
    assert loaded is not None
    assert loaded.text == "test report"


def test_load_returns_none_when_missing(tmp_path):
    assert load_cached_report(str(tmp_path)) is None


def test_load_returns_none_when_stale(tmp_path):
    report = WeeklyReport(text="old", generated_at=time.time() - CACHE_TTL_SECONDS - 100)
    save_cached_report(str(tmp_path), report)
    assert load_cached_report(str(tmp_path)) is None


def test_load_returns_none_for_malformed_cache(tmp_path):
    path = tmp_path / "widget-cache" / "weekly-report.json"
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w") as f:
        f.write("{not json}")
    assert load_cached_report(str(tmp_path)) is None


def test_build_prompt_includes_core_numbers():
    summary = {
        "week_cost": 12.34,
        "week_tokens": 150000,
        "week_messages": 420,
        "subscription_type": "max",
        "top_projects": [("~/project-a", 80000), ("~/project-b", 40000)],
        "by_model": {"claude-opus-4-7": {"input": 10000, "output": 5000}},
    }
    prompt = build_prompt(summary)
    assert "420" in prompt
    assert "150000" in prompt
    assert "12.34" in prompt
    assert "~/project-a" in prompt
    assert "Max" in prompt or "max" in prompt
    assert "claude-opus-4-7" in prompt


def test_generate_returns_cached_first(tmp_path):
    # Pre-populate cache with a fresh entry — the token_loader must not be called.
    cached = WeeklyReport(text="from cache", generated_at=time.time())
    save_cached_report(str(tmp_path), cached)

    def fail_loader():
        raise AssertionError("token loader should not be called when cache is fresh")

    result = generate_report(str(tmp_path), {}, token_loader=fail_loader)
    assert result is not None
    assert result.text == "from cache"


def test_generate_returns_none_without_token(tmp_path):
    # Empty cache, no token — should not attempt network.
    result = generate_report(str(tmp_path), {}, token_loader=lambda: None)
    assert result is None


def test_generate_swallows_token_loader_exceptions(tmp_path):
    def bad_loader():
        raise RuntimeError("boom")
    result = generate_report(str(tmp_path), {}, token_loader=bad_loader)
    assert result is None
