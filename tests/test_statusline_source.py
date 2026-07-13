"""Tests for the statusLine-dumped rate-limit source (claude_usage.collector)."""

import json
import time
from datetime import datetime, timezone

from claude_usage.collector import _load_statusline_rate_limits


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
