"""Tests for the opt-in Codex provider (claude_usage.codex)."""

import time

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
