"""Tests for the opt-in Codex provider (claude_usage.codex)."""

import time
from unittest.mock import patch

import claude_usage.codex as codex
from claude_usage.codex import _clamp_expired, parse_rate_limits


FUTURE = int(time.time()) + 3600


def _payload(primary=None, secondary=None):
    limits = {}
    if primary is not None:
        limits["primary"] = primary
    if secondary is not None:
        limits["secondary"] = secondary
    return {"rateLimits": limits}


def test_parse_both_windows():
    parsed = parse_rate_limits(_payload(
        primary={"usedPercent": 54.2, "resetsAt": FUTURE, "windowDurationMins": 300},
        secondary={"usedPercent": 12.0, "resetsAt": FUTURE + 86400},
    ))
    assert parsed == {
        "session_pct": 0.542,
        "session_reset": FUTURE,
        "weekly_pct": 0.12,
        "weekly_reset": FUTURE + 86400,
    }


def test_parse_single_window_and_clamping():
    parsed = parse_rate_limits(_payload(primary={"usedPercent": 250.0, "resetsAt": None}))
    assert parsed is not None
    assert parsed["session_pct"] == 1.0  # clamped to 0..1
    assert parsed["session_reset"] == 0
    assert parsed["weekly_pct"] == 0.0


def test_parse_millisecond_resets_normalised():
    parsed = parse_rate_limits(_payload(primary={"usedPercent": 10, "resetsAt": FUTURE * 1000}))
    assert parsed is not None
    assert parsed["session_reset"] == FUTURE


def test_parse_rejects_unusable_payloads():
    assert parse_rate_limits(None) is None
    assert parse_rate_limits({}) is None
    assert parse_rate_limits({"rateLimits": "nope"}) is None
    assert parse_rate_limits(_payload()) is None
    assert parse_rate_limits(_payload(primary={"usedPercent": None})) is None
    assert parse_rate_limits(_payload(primary={"usedPercent": "NaN%"})) is None


def test_clamp_expired_windows_roll_back_to_zero():
    now = time.time()
    parsed = {
        "session_pct": 0.9, "session_reset": int(now - 60),
        "weekly_pct": 0.4, "weekly_reset": int(now + 3600),
    }
    out = _clamp_expired(parsed, now)
    assert out["session_pct"] == 0.0 and out["session_reset"] == 0
    assert out["weekly_pct"] == 0.4 and out["weekly_reset"] == int(now + 3600)


# --- collect_codex cache / throttle / fallback path -----------------------

def test_collect_codex_non_posix_is_unavailable():
    with patch.object(codex.os, "name", "nt"):
        out = codex.collect_codex()
    assert out["available"] is False
    assert "POSIX" in out["error"]


def test_collect_codex_missing_binary_is_unavailable():
    with patch.object(codex.os, "name", "posix"), \
         patch.object(codex, "find_codex_bin", return_value=None):
        out = codex.collect_codex()
    assert out["available"] is False
    assert "not found" in out["error"]


def test_collect_codex_serves_fresh_cache_without_spawning_rpc():
    fresh = {"fetched_at": time.time(), "payload": _payload(
        primary={"usedPercent": 20, "resetsAt": FUTURE},
        secondary={"usedPercent": 30, "resetsAt": FUTURE})}
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        return None

    with patch.object(codex.os, "name", "posix"), \
         patch.object(codex, "find_codex_bin", return_value="/usr/bin/codex"), \
         patch.object(codex, "_load_cache", return_value=fresh), \
         patch.object(codex, "_rate_limits_rpc", boom):
        out = codex.collect_codex(poll_seconds=300)
    assert calls["n"] == 0                     # fresh cache → no RPC spawn
    assert out["available"] is True
    assert abs(out["session_pct"] - 0.20) < 1e-6
    assert abs(out["weekly_pct"] - 0.30) < 1e-6


def test_collect_codex_rpc_success_saves_cache():
    payload = _payload(primary={"usedPercent": 55, "resetsAt": FUTURE},
                       secondary={"usedPercent": 5, "resetsAt": FUTURE})
    saved = {}
    with patch.object(codex.os, "name", "posix"), \
         patch.object(codex, "find_codex_bin", return_value="/usr/bin/codex"), \
         patch.object(codex, "_load_cache", return_value=None), \
         patch.object(codex, "_rate_limits_rpc", return_value=payload), \
         patch.object(codex, "_save_cache", side_effect=lambda p: saved.update(p=p)):
        out = codex.collect_codex()
    assert out["available"] is True
    assert abs(out["session_pct"] - 0.55) < 1e-6
    assert saved.get("p") == payload           # fresh result cached


def test_collect_codex_rpc_failure_falls_back_to_stale_cache():
    stale = {"fetched_at": time.time() - 99999, "payload": _payload(
        primary={"usedPercent": 42, "resetsAt": FUTURE})}
    with patch.object(codex.os, "name", "posix"), \
         patch.object(codex, "find_codex_bin", return_value="/usr/bin/codex"), \
         patch.object(codex, "_load_cache", return_value=stale), \
         patch.object(codex, "_rate_limits_rpc", return_value=None):
        out = codex.collect_codex(poll_seconds=300)
    assert out["available"] is True
    assert "rpc failed" in out["error"]
    assert abs(out["session_pct"] - 0.42) < 1e-6
