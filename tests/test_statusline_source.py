"""Tests for the statusLine-dumped rate-limit source (claude_usage.collector)."""

import json
import os
import time
from datetime import datetime, timezone

import claude_usage.collector as collector
from claude_usage.collector import _load_statusline_rate_limits, collect_all


NOW = time.time()
FUTURE = int(NOW) + 3600


def _write(tmp_path, captured_at=None, five_hour=..., seven_day=...):
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).isoformat()
    limits = {}
    if five_hour is not ...:
        limits["five_hour"] = five_hour
    if seven_day is not ...:
        limits["seven_day"] = seven_day
    path = tmp_path / "statusline.json"
    path.write_text(json.dumps({"captured_at": captured_at, "rate_limits": limits}))
    return str(path)


def _cfg(path):
    return {"statusline_cache_path": path}


def test_fresh_file_both_windows(tmp_path):
    path = _write(
        tmp_path,
        five_hour={"used_percentage": 54, "resets_at": FUTURE},
        seven_day={"used_percentage": 46, "resets_at": FUTURE + 86400},
    )
    out = _load_statusline_rate_limits(_cfg(path), NOW)
    assert out == {
        "session": (0.54, FUTURE),
        "weekly": (0.46, FUTURE + 86400),
    }


def test_expired_window_clamps_to_zero(tmp_path):
    path = _write(
        tmp_path,
        five_hour={"used_percentage": 90, "resets_at": int(NOW) - 60},
        seven_day={"used_percentage": 46, "resets_at": FUTURE},
    )
    out = _load_statusline_rate_limits(_cfg(path), NOW)
    assert out is not None
    assert out["session"] == (0.0, 0)
    assert out["weekly"] == (0.46, FUTURE)


def test_stale_and_future_files_rejected(tmp_path):
    old = datetime.fromtimestamp(NOW - 3600, tz=timezone.utc).isoformat()
    path = _write(tmp_path, captured_at=old,
                  five_hour={"used_percentage": 10, "resets_at": FUTURE},
                  seven_day={"used_percentage": 10, "resets_at": FUTURE})
    assert _load_statusline_rate_limits(_cfg(path), NOW) is None
    # But a caller-supplied larger max age accepts it:
    assert _load_statusline_rate_limits(_cfg(path), NOW, max_age_seconds=7200) is not None
    ahead = datetime.fromtimestamp(NOW + 3600, tz=timezone.utc).isoformat()
    path = _write(tmp_path, captured_at=ahead,
                  five_hour={"used_percentage": 10, "resets_at": FUTURE},
                  seven_day={"used_percentage": 10, "resets_at": FUTURE})
    assert _load_statusline_rate_limits(_cfg(path), NOW) is None


def test_missing_window_or_file_or_config_rejected(tmp_path):
    path = _write(tmp_path, five_hour={"used_percentage": 10, "resets_at": FUTURE})
    assert _load_statusline_rate_limits(_cfg(path), NOW) is None
    assert _load_statusline_rate_limits(_cfg(str(tmp_path / "nope.json")), NOW) is None
    assert _load_statusline_rate_limits({}, NOW) is None


def test_garbage_payload_rejected(tmp_path):
    path = tmp_path / "statusline.json"
    path.write_text("not json {")
    assert _load_statusline_rate_limits(_cfg(str(path)), NOW) is None
    path.write_text(json.dumps({"captured_at": "yesterday-ish", "rate_limits": {}}))
    assert _load_statusline_rate_limits(_cfg(str(path)), NOW) is None


def test_zulu_captured_at_parses(tmp_path):
    # Python 3.10's fromisoformat rejects a trailing 'Z' — the loader must
    # normalize it so statusline scripts emitting Zulu timestamps still work.
    z = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    path = _write(tmp_path, captured_at=z,
                  five_hour={"used_percentage": 50, "resets_at": FUTURE},
                  seven_day={"used_percentage": 50, "resets_at": FUTURE})
    out = _load_statusline_rate_limits(_cfg(path), NOW)
    assert out is not None
    assert out["session"] == (0.5, FUTURE)


def _seed_claude_dir(tmp_path, sample_age_s):
    """A minimal claude_dir with a usage-history.jsonl whose mtime is
    `sample_age_s` seconds old (the last-successful-endpoint-fetch marker)."""
    cdir = tmp_path / "claude"
    cdir.mkdir()
    samples = cdir / "usage-history.jsonl"
    samples.write_text(json.dumps(
        {"ts": NOW - 10, "session": 0.9, "weekly": 0.9}) + "\n")
    os.utime(samples, (NOW - sample_age_s, NOW - sample_age_s))
    return cdir


def test_collect_all_skips_endpoint_when_statusline_fresh(tmp_path, monkeypatch):
    cdir = _seed_claude_dir(tmp_path, sample_age_s=10)  # well within endpoint_min
    dump = _write(tmp_path,
                  five_hour={"used_percentage": 30, "resets_at": FUTURE},
                  seven_day={"used_percentage": 40, "resets_at": FUTURE})
    calls = {"n": 0}
    monkeypatch.setattr(collector, "fetch_rate_limits",
                        lambda cd: calls.__setitem__("n", calls["n"] + 1) or {})
    stats = collect_all({
        "claude_dir": str(cdir), "statusline_cache_path": dump,
        "refresh_seconds": 60, "usage_endpoint_min_seconds": 300,
    })
    assert calls["n"] == 0                      # endpoint skipped
    assert abs(stats.session_utilization - 0.30) < 1e-6
    assert abs(stats.weekly_utilization - 0.40) < 1e-6


def test_collect_all_forces_endpoint_when_last_fetch_stale(tmp_path, monkeypatch):
    cdir = _seed_claude_dir(tmp_path, sample_age_s=400)  # older than endpoint_min
    dump = _write(tmp_path,
                  five_hour={"used_percentage": 30, "resets_at": FUTURE},
                  seven_day={"used_percentage": 40, "resets_at": FUTURE})
    calls = {"n": 0}
    monkeypatch.setattr(collector, "fetch_rate_limits",
                        lambda cd: calls.__setitem__("n", calls["n"] + 1) or {"error": "x"})
    collect_all({
        "claude_dir": str(cdir), "statusline_cache_path": dump,
        "refresh_seconds": 60, "usage_endpoint_min_seconds": 300,
    })
    assert calls["n"] == 1                      # endpoint forced through
