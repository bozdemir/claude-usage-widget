"""Tests for claude_usage.cache_analyzer."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pytest

from claude_usage.cache_analyzer import (
    MIN_CACHEABLE_TOKENS,
    MIN_OCCURRENCES,
    TOP_N,
    _compute_savings,
    _estimate_tokens,
    analyze_cache_opportunities,
)


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _make_entry(text: str, ts: datetime, model: str = "claude-sonnet-4-6") -> dict:
    return {
        "timestamp": ts.isoformat() + "Z",
        "message": {"role": "user", "content": text, "model": model},
    }


def test_estimate_tokens_matches_rough_quarter_of_chars():
    assert _estimate_tokens("a" * 4000) == 1000
    assert _estimate_tokens("") == 1  # clamps to 1 minimum


def test_compute_savings_is_positive_for_repeated_prefix():
    # 10k tokens × 5 occurrences — caching saves meaningful money.
    saved = _compute_savings(tokens=10_000, occurrences=5, model="claude-sonnet-4-6")
    assert saved > 0


def test_compute_savings_falls_back_for_unknown_model(recwarn):
    saved = _compute_savings(tokens=10_000, occurrences=5, model="nonexistent")
    assert saved > 0


def test_returns_empty_when_projects_dir_missing(tmp_path):
    # No projects/ subdir — gracefully returns empty.
    result = analyze_cache_opportunities(str(tmp_path))
    assert result == []


def test_finds_single_repeated_prefix(tmp_path):
    now = datetime.now()
    # One project with a large repeated prompt — above the MIN_OCCURRENCES bar.
    prefix = "You are an expert Python engineer. " * 400  # ~1400 tokens
    entries = [
        _make_entry(prefix, now - timedelta(hours=i))
        for i in range(MIN_OCCURRENCES + 1)
    ]
    _write_jsonl(str(tmp_path / "projects" / "proj-a" / "session.jsonl"), entries)

    result = analyze_cache_opportunities(str(tmp_path), days=7, now=now.timestamp())
    assert len(result) == 1
    opp = result[0]
    assert opp.project == "proj-a"
    assert opp.occurrences == MIN_OCCURRENCES + 1
    assert opp.potential_savings_usd > 0
    assert opp.token_count >= MIN_CACHEABLE_TOKENS


def test_ranks_multiple_projects_by_savings_descending(tmp_path):
    """With 3 projects of different (tokens × occurrences), result must be sorted."""
    now = datetime.now()
    # Each block is 20 chars → 1 char × 20 = 20, × N blocks → 20N chars → 5N tokens.
    # Small: 2000 tokens × 4 uses, Medium: 4000 × 6, Large: 8000 × 10.
    small_prefix = "Small prefix block. " * 400
    medium_prefix = "Medium prefix block. " * 800
    large_prefix = "Large prefix block. " * 1600

    _write_jsonl(
        str(tmp_path / "projects" / "proj-small" / "s.jsonl"),
        [_make_entry(small_prefix, now - timedelta(hours=i)) for i in range(4)],
    )
    _write_jsonl(
        str(tmp_path / "projects" / "proj-medium" / "s.jsonl"),
        [_make_entry(medium_prefix, now - timedelta(hours=i)) for i in range(6)],
    )
    _write_jsonl(
        str(tmp_path / "projects" / "proj-large" / "s.jsonl"),
        [_make_entry(large_prefix, now - timedelta(hours=i)) for i in range(10)],
    )

    result = analyze_cache_opportunities(str(tmp_path), days=7, now=now.timestamp())
    assert len(result) == 3
    savings = [o.potential_savings_usd for o in result]
    assert savings == sorted(savings, reverse=True)
    assert result[0].project == "proj-large"
    assert result[-1].project == "proj-small"


def test_skips_short_prefixes(tmp_path):
    now = datetime.now()
    entries = [
        _make_entry("short prompt" * 20, now - timedelta(hours=i))  # ~240 chars, ~60 tokens
        for i in range(5)
    ]
    _write_jsonl(str(tmp_path / "projects" / "proj" / "session.jsonl"), entries)

    result = analyze_cache_opportunities(str(tmp_path), days=7, now=now.timestamp())
    # Below the 1024-token cache floor — excluded.
    assert result == []


def test_skips_subagent_sessions(tmp_path):
    now = datetime.now()
    prefix = "Big repeated context " * 400
    entries = [_make_entry(prefix, now - timedelta(minutes=i)) for i in range(5)]
    _write_jsonl(str(tmp_path / "projects" / "proj" / "subagents" / "a.jsonl"), entries)
    result = analyze_cache_opportunities(str(tmp_path), days=7, now=now.timestamp())
    assert result == []


def test_respects_top_n_cap(tmp_path):
    now = datetime.now()
    for i in range(TOP_N + 3):
        prefix = f"Unique prefix #{i} " + ("x" * 5000)
        entries = [_make_entry(prefix, now - timedelta(minutes=m)) for m in range(5)]
        _write_jsonl(str(tmp_path / "projects" / f"p{i}" / "s.jsonl"), entries)
    result = analyze_cache_opportunities(str(tmp_path), days=7, now=now.timestamp())
    assert len(result) <= TOP_N
    # Sorted descending by savings.
    assert result == sorted(result, key=lambda o: o.potential_savings_usd, reverse=True)


def test_malformed_lines_are_ignored_but_valid_entries_still_surface(tmp_path):
    """Corruption-tolerance: bad lines are skipped, valid surrounding entries count."""
    now = datetime.now()
    path = tmp_path / "projects" / "p" / "s.jsonl"
    os.makedirs(path.parent, exist_ok=True)
    prefix = "Valid prefix for cache " * 400
    with open(path, "w") as f:
        f.write("{not json}\n")
        for i in range(MIN_OCCURRENCES + 1):
            f.write(json.dumps(_make_entry(prefix, now - timedelta(hours=i))) + "\n")
            f.write("\n")  # interleaved blank lines
        f.write("garbage at end\n")
    result = analyze_cache_opportunities(str(tmp_path), days=7, now=now.timestamp())
    # Positive control: the valid entries must still be detected.
    assert len(result) == 1
    assert result[0].occurrences == MIN_OCCURRENCES + 1
