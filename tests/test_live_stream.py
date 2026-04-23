"""Tests for claude_usage.live_stream."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from claude_usage.live_stream import (
    ACTIVE_CUTOFF_SECONDS,
    LIVE_WINDOW_SECONDS,
    LiveActivity,
    detect_live_activity,
)


_COUNTER = [0]


def _assistant_entry(ts: datetime, out_tokens: int, msg_id: str | None = None) -> dict:
    if msg_id is None:
        _COUNTER[0] += 1
        msg_id = f"msg_{_COUNTER[0]}"
    return {
        "timestamp": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": {
            "role": "assistant",
            "id": msg_id,
            "usage": {"output_tokens": out_tokens},
        },
    }


def _write(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_no_projects_dir_returns_default(tmp_path):
    result = detect_live_activity(str(tmp_path))
    assert isinstance(result, LiveActivity)
    assert result.is_live is False
    assert result.tokens_per_minute == 0.0


def test_detects_live_session(tmp_path):
    now = datetime.now(timezone.utc)
    # 3 assistant turns in the last minute — 300 output tokens total.
    entries = [
        _assistant_entry(now - timedelta(seconds=20), 100),
        _assistant_entry(now - timedelta(seconds=40), 100),
        _assistant_entry(now - timedelta(seconds=60), 100),
    ]
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), entries)
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.is_live is True
    assert result.output_tokens_last_window == 300
    expected_tpm = 300 / (LIVE_WINDOW_SECONDS / 60.0)
    assert result.tokens_per_minute == pytest.approx(expected_tpm)


def test_marks_not_live_when_last_activity_is_older_than_active_cutoff(tmp_path):
    # Activity from 150s ago — inside the 5-min rate window but outside the
    # 90s "is_live" cutoff. Expect is_live=False but a non-zero rate.
    now = datetime.now(timezone.utc)
    old_ts = now - timedelta(seconds=ACTIVE_CUTOFF_SECONDS + 60)
    assert old_ts.timestamp() >= now.timestamp() - LIVE_WINDOW_SECONDS  # guard
    path = tmp_path / "projects" / "p" / "s.jsonl"
    _write(str(path), [_assistant_entry(old_ts, 500)])
    os.utime(str(path), (now.timestamp(), now.timestamp()))
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.is_live is False
    assert result.tokens_per_minute > 0
    assert result.output_tokens_last_window == 500


def test_marks_not_live_when_activity_is_outside_rate_window(tmp_path):
    # Activity from 10 min ago — past the rate window entirely.
    now = datetime.now(timezone.utc)
    old_ts = now - timedelta(seconds=LIVE_WINDOW_SECONDS + 300)
    path = tmp_path / "projects" / "p" / "s.jsonl"
    _write(str(path), [_assistant_entry(old_ts, 500)])
    os.utime(str(path), (now.timestamp(), now.timestamp()))
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.is_live is False
    assert result.tokens_per_minute == 0.0
    assert result.output_tokens_last_window == 0


def test_deduplicates_replays_by_msg_id(tmp_path):
    """Claude Code rewrites prior assistant turns as context; we must not
    count the same message three times."""
    now = datetime.now(timezone.utc)
    replay = _assistant_entry(now - timedelta(seconds=20), 100, msg_id="dup")
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [replay, replay, replay])
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.output_tokens_last_window == 100


def test_entries_without_msg_id_are_skipped(tmp_path):
    """Without an id we can't safely dedupe — drop to avoid double-counting."""
    now = datetime.now(timezone.utc)
    entry = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "message": {"role": "assistant", "usage": {"output_tokens": 500}},
    }
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [entry])
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.output_tokens_last_window == 0


def test_future_timestamps_are_ignored(tmp_path):
    # Clock-skewed entry dated 5 min in the future — must not pollute the rate.
    now = datetime.now(timezone.utc)
    future_ts = now + timedelta(seconds=300)
    path = tmp_path / "projects" / "p" / "s.jsonl"
    _write(str(path), [_assistant_entry(future_ts, 9999)])
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.tokens_per_minute == 0.0
    assert result.output_tokens_last_window == 0


def test_skips_user_messages(tmp_path):
    now = datetime.now(timezone.utc)
    entries = [{
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "message": {"role": "user", "content": "hi"},
    }]
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), entries)
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.tokens_per_minute == 0.0
    assert result.is_live is False


def test_skips_subagent_sessions(tmp_path):
    now = datetime.now(timezone.utc)
    entries = [_assistant_entry(now - timedelta(seconds=10), 500)]
    _write(str(tmp_path / "projects" / "p" / "subagents" / "s.jsonl"), entries)
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.is_live is False
    assert result.tokens_per_minute == 0.0


def test_malformed_lines_are_skipped(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "projects" / "p" / "s.jsonl"
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n")  # blank
        f.write("{not json}\n")
        f.write(json.dumps(_assistant_entry(now - timedelta(seconds=10), 50)) + "\n")
    result = detect_live_activity(str(tmp_path), now=now.timestamp())
    assert result.output_tokens_last_window == 50
