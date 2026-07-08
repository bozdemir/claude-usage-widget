"""Tests for the claude_usage.collector module.

Covers history parsing, token aggregation, session detection, subagent
filtering, rate-limit header parsing, and the collect_all integration path.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from claude_usage.collector import (
    UsageStats,
    _collect_month_tokens,
    _collect_tokens_single_pass,
    _fetch_oauth_usage,
    _parse_rate_limit_headers,
    _parse_retry_after,
    collect_all,
    collect_tokens_from_conversations,
    fetch_rate_limits,
    get_active_sessions,
    parse_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history_file(entries: list[dict[str, Any]]) -> str:
    """Write *entries* as newline-delimited JSON to a temp file and return its path.

    The caller is responsible for unlinking the file after the test.
    """
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for entry in entries:
        f.write(json.dumps(entry) + "\n")
    f.close()
    return f.name


def _now_ms() -> int:
    """Return the current time as a millisecond-precision Unix timestamp."""
    return int(datetime.now().timestamp() * 1000)


def _days_ago_ms(days: int) -> int:
    """Return a millisecond timestamp for *days* calendar days before now."""
    return int((datetime.now() - timedelta(days=days)).timestamp() * 1000)


def _make_conversation_dir(
    tmpdir: str,
    project_slug: str = "-home-test",
    *,
    subagent: bool = False,
) -> str:
    """Create a ``projects/<slug>/`` directory tree inside *tmpdir*.

    When *subagent* is True the directory is placed under a ``subagents/``
    sub-path so the token collector will skip it.

    Returns the path to the created directory.
    """
    if subagent:
        proj_dir = os.path.join(tmpdir, "projects", project_slug, "subagents")
    else:
        proj_dir = os.path.join(tmpdir, "projects", project_slug)
    os.makedirs(proj_dir, exist_ok=True)
    return proj_dir


def _write_conversation(
    directory: str,
    messages: list[dict[str, Any]],
    filename: str = "session-abc.jsonl",
) -> str:
    """Write *messages* as JSONL into *directory*/*filename* and return the path."""
    path = os.path.join(directory, filename)
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


def _assistant_entry(
    timestamp: str,
    *,
    model: str = "claude-opus-4-6",
    output_tokens: int = 100,
    input_tokens: int = 50,
    cache_read: int = 0,
    cache_create: int = 0,
) -> dict[str, Any]:
    """Build a minimal assistant-type conversation entry with the given token counts."""
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_create,
            },
        },
    }


# ---------------------------------------------------------------------------
# UsageStats defaults
# ---------------------------------------------------------------------------


class TestUsageStatsDefaults(unittest.TestCase):
    """Verify that UsageStats fields initialise to safe zero/empty values."""

    def test_all_numeric_fields_default_to_zero(self) -> None:
        """Every numeric field on a freshly created UsageStats should be zero."""
        stats = UsageStats()
        self.assertEqual(stats.today_messages, 0)
        self.assertEqual(stats.today_sessions, 0)
        self.assertEqual(stats.week_messages, 0)
        self.assertEqual(stats.week_sessions, 0)
        self.assertEqual(stats.today_tokens, 0)
        self.assertEqual(stats.week_tokens, 0)
        self.assertAlmostEqual(stats.session_utilization, 0.0)
        self.assertEqual(stats.session_reset, 0)
        self.assertAlmostEqual(stats.weekly_utilization, 0.0)
        self.assertEqual(stats.weekly_reset, 0)

    def test_collection_fields_default_to_empty(self) -> None:
        """List and dict fields on a fresh UsageStats should be empty containers."""
        stats = UsageStats()
        self.assertEqual(stats.active_sessions, [])
        self.assertEqual(stats.today_model_tokens, {})
        self.assertEqual(stats.today_hourly, {})
        self.assertEqual(stats.overage_status, "")
        self.assertEqual(stats.fallback_status, "")
        self.assertEqual(stats.rate_limit_error, "")


# ---------------------------------------------------------------------------
# parse_history
# ---------------------------------------------------------------------------


class TestParseHistory(unittest.TestCase):
    """Tests for parse_history covering counting, filtering, and edge cases."""

    def test_counts_messages_for_today(self) -> None:
        """Only messages timestamped today are counted in today_messages."""
        now = _now_ms()
        yesterday = _days_ago_ms(1)
        entries = [
            {"display": "msg1", "timestamp": now, "sessionId": "s1", "project": "/p"},
            {"display": "msg2", "timestamp": now + 1000, "sessionId": "s1", "project": "/p"},
            {"display": "old", "timestamp": yesterday, "sessionId": "s2", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 2)
        finally:
            os.unlink(path)

    def test_counts_weekly_messages(self) -> None:
        """Messages within the past 7-day window are counted; older ones are excluded."""
        now = _now_ms()
        three_days_ago = _days_ago_ms(3)
        ten_days_ago = _days_ago_ms(10)
        entries = [
            {"display": "m1", "timestamp": now, "sessionId": "s1", "project": "/p"},
            {"display": "m2", "timestamp": three_days_ago, "sessionId": "s2", "project": "/p"},
            {"display": "m3", "timestamp": ten_days_ago, "sessionId": "s3", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.week_messages, 2)
        finally:
            os.unlink(path)

    def test_counts_unique_sessions_today(self) -> None:
        """today_sessions reflects the number of distinct session IDs seen today."""
        now = _now_ms()
        entries = [
            {"display": "m1", "timestamp": now, "sessionId": "s1", "project": "/p"},
            {"display": "m2", "timestamp": now + 1, "sessionId": "s1", "project": "/p"},
            {"display": "m3", "timestamp": now + 2, "sessionId": "s2", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_sessions, 2)
        finally:
            os.unlink(path)

    def test_counts_unique_sessions_this_week(self) -> None:
        """week_sessions reflects distinct session IDs across the 7-day window."""
        now = _now_ms()
        two_days_ago = _days_ago_ms(2)
        entries = [
            {"display": "m1", "timestamp": now, "sessionId": "s1", "project": "/p"},
            {"display": "m2", "timestamp": two_days_ago, "sessionId": "s2", "project": "/p"},
            {"display": "m3", "timestamp": two_days_ago + 1, "sessionId": "s2", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.week_sessions, 2)
        finally:
            os.unlink(path)

    def test_empty_file(self) -> None:
        """An empty history file yields zero counts for all stats."""
        path = _make_history_file([])
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 0)
            self.assertEqual(stats.week_messages, 0)
            self.assertEqual(stats.today_sessions, 0)
            self.assertEqual(stats.week_sessions, 0)
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_empty_stats(self) -> None:
        """A path that does not exist on disk returns a zero-valued UsageStats."""
        stats = parse_history("/no/such/file.jsonl")
        self.assertEqual(stats.today_messages, 0)
        self.assertEqual(stats.week_messages, 0)

    def test_timestamp_zero_is_skipped(self) -> None:
        """Entries with timestamp=0 are treated as invalid and ignored."""
        entries = [
            {"display": "zeroed", "timestamp": 0, "sessionId": "s1", "project": "/p"},
            {"display": "ok", "timestamp": _now_ms(), "sessionId": "s1", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 1)
        finally:
            os.unlink(path)

    def test_negative_timestamp_is_skipped(self) -> None:
        """Entries with a negative timestamp are treated as invalid and ignored."""
        entries = [
            {"display": "neg", "timestamp": -100, "sessionId": "s1", "project": "/p"},
            {"display": "ok", "timestamp": _now_ms(), "sessionId": "s1", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 1)
        finally:
            os.unlink(path)

    def test_missing_timestamp_key_is_skipped(self) -> None:
        """An entry that lacks the 'timestamp' key entirely is silently skipped."""
        entries = [
            {"display": "no-ts", "sessionId": "s1", "project": "/p"},
            {"display": "ok", "timestamp": _now_ms(), "sessionId": "s1", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 1)
        finally:
            os.unlink(path)

    def test_malformed_json_lines_are_skipped(self) -> None:
        """Lines that are not valid JSON are silently skipped without crashing."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write("not valid json\n")
        f.write(json.dumps({"display": "ok", "timestamp": _now_ms(), "sessionId": "s1", "project": "/p"}) + "\n")
        f.write("{truncated\n")
        f.close()
        try:
            stats = parse_history(f.name)
            self.assertEqual(stats.today_messages, 1)
        finally:
            os.unlink(f.name)

    def test_blank_lines_are_skipped(self) -> None:
        """Blank or whitespace-only lines in the JSONL file are harmlessly ignored."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write("\n")
        f.write("   \n")
        f.write(json.dumps({"display": "ok", "timestamp": _now_ms(), "sessionId": "s1", "project": "/p"}) + "\n")
        f.write("\n")
        f.close()
        try:
            stats = parse_history(f.name)
            self.assertEqual(stats.today_messages, 1)
        finally:
            os.unlink(f.name)

    def test_hourly_histogram_is_populated(self) -> None:
        """today_hourly maps each hour to the number of messages sent during that hour."""
        now = datetime.now()
        # Craft a timestamp for hour 14 today
        fixed = now.replace(hour=14, minute=30, second=0, microsecond=0)
        ts_ms = int(fixed.timestamp() * 1000)
        # Only test if the crafted time is still today (avoids failures near midnight)
        if fixed.date() == now.date() and fixed <= now:
            entries = [
                {"display": "a", "timestamp": ts_ms, "sessionId": "s1", "project": "/p"},
                {"display": "b", "timestamp": ts_ms + 1000, "sessionId": "s1", "project": "/p"},
            ]
            path = _make_history_file(entries)
            try:
                stats = parse_history(path)
                self.assertEqual(stats.today_hourly.get(14, 0), 2)
            finally:
                os.unlink(path)

    def test_week_boundary_exactly_six_days_ago_is_included(self) -> None:
        """A message timestamped at the start of 6 days ago falls within the 7-day window."""
        now = datetime.now()
        boundary = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
        # One second into that boundary day
        ts_ms = int((boundary + timedelta(seconds=1)).timestamp() * 1000)
        entries = [
            {"display": "boundary", "timestamp": ts_ms, "sessionId": "s1", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.week_messages, 1)
        finally:
            os.unlink(path)

    def test_message_exactly_seven_days_ago_is_excluded(self) -> None:
        """A message from 7 full days ago (before the rolling window) is excluded."""
        now = datetime.now()
        boundary = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
        ts_ms = int(boundary.timestamp() * 1000)
        entries = [
            {"display": "too old", "timestamp": ts_ms, "sessionId": "s1", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.week_messages, 0)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Token collection (legacy API)
# ---------------------------------------------------------------------------


class TestTokenCollection(unittest.TestCase):
    """Tests for collect_tokens_from_conversations (the legacy entry point)."""

    def test_collects_tokens_from_conversation_file(self) -> None:
        """Token counts are correctly summed across multiple assistant messages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            now_iso = datetime.now().isoformat()
            messages = [
                {"type": "user", "timestamp": now_iso},
                _assistant_entry(now_iso, output_tokens=500, input_tokens=100, cache_read=1000, cache_create=200),
                _assistant_entry(now_iso, output_tokens=300, input_tokens=50, cache_read=500, cache_create=100),
            ]
            _write_conversation(proj_dir, messages)

            tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
            self.assertEqual(tokens["total_output"], 800)
            self.assertEqual(tokens["total_input"], 150)
            self.assertEqual(tokens["by_model"]["claude-opus-4-6"]["output"], 800)
            self.assertEqual(tokens["by_model"]["claude-opus-4-6"]["input"], 150)

    def test_skips_subagent_conversations(self) -> None:
        """Conversations inside a subagents/ directory are excluded to avoid double-counting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Normal conversation
            normal_dir = _make_conversation_dir(tmpdir)
            now_iso = datetime.now().isoformat()
            _write_conversation(normal_dir, [
                _assistant_entry(now_iso, output_tokens=100),
            ])

            # Subagent conversation (should be skipped)
            sub_dir = _make_conversation_dir(tmpdir, subagent=True)
            _write_conversation(sub_dir, [
                _assistant_entry(now_iso, output_tokens=9999),
            ])

            tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
            self.assertEqual(tokens["total_output"], 100)

    def test_no_projects_directory_returns_zeroes(self) -> None:
        """When the projects/ directory does not exist, totals are all zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tokens = collect_tokens_from_conversations(tmpdir, [datetime.now().isoformat()[:10]])
            self.assertEqual(tokens["total_output"], 0)
            self.assertEqual(tokens["total_input"], 0)
            self.assertEqual(tokens["by_model"], {})

    def test_skips_user_type_entries(self) -> None:
        """Only assistant-type entries contribute tokens; user entries are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            now_iso = datetime.now().isoformat()
            messages = [
                {"type": "user", "timestamp": now_iso, "message": {"usage": {"output_tokens": 999}}},
                _assistant_entry(now_iso, output_tokens=42),
            ]
            _write_conversation(proj_dir, messages)

            tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
            self.assertEqual(tokens["total_output"], 42)

    def test_skips_entries_with_non_dict_message(self) -> None:
        """An assistant entry whose 'message' is not a dict is safely skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            now_iso = datetime.now().isoformat()
            messages = [
                {"type": "assistant", "timestamp": now_iso, "message": "just a string"},
                _assistant_entry(now_iso, output_tokens=10),
            ]
            _write_conversation(proj_dir, messages)

            tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
            self.assertEqual(tokens["total_output"], 10)

    def test_skips_entries_with_missing_usage_block(self) -> None:
        """An assistant entry without a 'usage' dict contributes zero tokens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            now_iso = datetime.now().isoformat()
            messages = [
                {"type": "assistant", "timestamp": now_iso, "message": {"model": "claude-opus-4-6"}},
                _assistant_entry(now_iso, output_tokens=10),
            ]
            _write_conversation(proj_dir, messages)

            tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
            self.assertEqual(tokens["total_output"], 10)

    def test_entries_outside_date_prefix_are_excluded(self) -> None:
        """Only entries whose timestamp starts with a listed date prefix are counted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            messages = [
                _assistant_entry("2025-01-01T12:00:00", output_tokens=100),
                _assistant_entry("2025-01-02T12:00:00", output_tokens=200),
            ]
            _write_conversation(proj_dir, messages)

            tokens = collect_tokens_from_conversations(tmpdir, ["2025-01-01"])
            self.assertEqual(tokens["total_output"], 100)

    def test_malformed_json_lines_are_skipped(self) -> None:
        """Corrupt lines in a conversation file are skipped without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            now_iso = datetime.now().isoformat()
            path = os.path.join(proj_dir, "session-bad.jsonl")
            with open(path, "w") as f:
                f.write("NOT JSON\n")
                f.write(json.dumps(_assistant_entry(now_iso, output_tokens=77)) + "\n")

            tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
            self.assertEqual(tokens["total_output"], 77)

    def test_multiple_models_tracked_separately(self) -> None:
        """Token counts are bucketed per model name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            now_iso = datetime.now().isoformat()
            messages = [
                _assistant_entry(now_iso, model="claude-opus-4-6", output_tokens=100, input_tokens=10),
                _assistant_entry(now_iso, model="claude-sonnet-4-20250514", output_tokens=200, input_tokens=20),
            ]
            _write_conversation(proj_dir, messages)

            tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
            self.assertEqual(tokens["by_model"]["claude-opus-4-6"]["output"], 100)
            self.assertEqual(tokens["by_model"]["claude-sonnet-4-20250514"]["output"], 200)
            self.assertEqual(tokens["total_output"], 300)


# ---------------------------------------------------------------------------
# Token collection (single-pass API)
# ---------------------------------------------------------------------------


class TestCollectTokensSinglePass(unittest.TestCase):
    """Tests for _collect_tokens_single_pass (the optimised one-pass path)."""

    def test_splits_today_and_week_totals(self) -> None:
        """Tokens from today appear in both today_output and week_output; older ones only in week_output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            today_str = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1))
            yesterday_str = yesterday.strftime("%Y-%m-%d")
            week_prefixes = [today_str, yesterday_str]

            messages = [
                _assistant_entry(f"{today_str}T10:00:00", output_tokens=100),
                _assistant_entry(f"{yesterday_str}T10:00:00", output_tokens=200),
            ]
            _write_conversation(proj_dir, messages)

            result = _collect_tokens_single_pass(tmpdir, today_str, week_prefixes)
            self.assertEqual(result["today_output"], 100)
            self.assertEqual(result["week_output"], 300)

    def test_today_by_model_tracks_per_model(self) -> None:
        """today_by_model breaks down today's tokens per model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = _make_conversation_dir(tmpdir)
            today_str = datetime.now().strftime("%Y-%m-%d")

            messages = [
                _assistant_entry(f"{today_str}T10:00:00", model="model-a", output_tokens=50),
                _assistant_entry(f"{today_str}T11:00:00", model="model-b", output_tokens=75),
            ]
            _write_conversation(proj_dir, messages)

            result = _collect_tokens_single_pass(tmpdir, today_str, [today_str])
            self.assertEqual(result["today_by_model"]["model-a"], 50)
            self.assertEqual(result["today_by_model"]["model-b"], 75)

    def test_skips_subagent_paths(self) -> None:
        """Files under a subagents/ directory are excluded from the single-pass scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            normal_dir = _make_conversation_dir(tmpdir)
            sub_dir = _make_conversation_dir(tmpdir, subagent=True)
            today_str = datetime.now().strftime("%Y-%m-%d")

            _write_conversation(normal_dir, [
                _assistant_entry(f"{today_str}T10:00:00", output_tokens=100),
            ])
            _write_conversation(sub_dir, [
                _assistant_entry(f"{today_str}T10:00:00", output_tokens=5000),
            ], filename="subagent-session.jsonl")

            result = _collect_tokens_single_pass(tmpdir, today_str, [today_str])
            self.assertEqual(result["today_output"], 100)

    def test_no_projects_directory_returns_zeroes(self) -> None:
        """Returns zero totals when the projects/ directory is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            today_str = datetime.now().strftime("%Y-%m-%d")
            result = _collect_tokens_single_pass(tmpdir, today_str, [today_str])
            self.assertEqual(result["today_output"], 0)
            self.assertEqual(result["week_output"], 0)
            self.assertEqual(result["today_by_model"], {})


# ---------------------------------------------------------------------------
# Active sessions
# ---------------------------------------------------------------------------


class TestActiveSessions(unittest.TestCase):
    """Tests for get_active_sessions covering live/dead PIDs and edge cases."""

    def test_reads_session_files_for_live_pid(self) -> None:
        """A session file whose PID matches a running process is returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sess_dir)

            my_pid = os.getpid()
            sess: dict[str, Any] = {
                "pid": my_pid,
                "sessionId": "test-session",
                "cwd": "/home/test",
                "startedAt": _now_ms(),
            }
            with open(os.path.join(sess_dir, f"{my_pid}.json"), "w") as f:
                json.dump(sess, f)

            sessions = get_active_sessions(tmpdir)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["sessionId"], "test-session")

    def test_skips_dead_sessions(self) -> None:
        """Session files whose PID no longer exists are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sess_dir)

            sess: dict[str, Any] = {
                "pid": 999999999,
                "sessionId": "dead-session",
                "cwd": "/tmp",
                "startedAt": _now_ms(),
            }
            with open(os.path.join(sess_dir, "999999999.json"), "w") as f:
                json.dump(sess, f)

            sessions = get_active_sessions(tmpdir)
            self.assertEqual(len(sessions), 0)

    def test_skips_sessions_with_zero_pid(self) -> None:
        """A session file with pid=0 is skipped as invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sess_dir)

            sess: dict[str, Any] = {"pid": 0, "sessionId": "zero-pid", "cwd": "/tmp", "startedAt": _now_ms()}
            with open(os.path.join(sess_dir, "0.json"), "w") as f:
                json.dump(sess, f)

            sessions = get_active_sessions(tmpdir)
            self.assertEqual(len(sessions), 0)

    def test_skips_sessions_with_negative_pid(self) -> None:
        """A session file with a negative pid is skipped as invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sess_dir)

            sess: dict[str, Any] = {"pid": -1, "sessionId": "neg-pid", "cwd": "/tmp", "startedAt": _now_ms()}
            with open(os.path.join(sess_dir, "neg.json"), "w") as f:
                json.dump(sess, f)

            sessions = get_active_sessions(tmpdir)
            self.assertEqual(len(sessions), 0)

    def test_skips_malformed_json_session_files(self) -> None:
        """Session files containing invalid JSON are silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sess_dir)

            with open(os.path.join(sess_dir, "bad.json"), "w") as f:
                f.write("{not valid json")

            sessions = get_active_sessions(tmpdir)
            self.assertEqual(len(sessions), 0)

    def test_ignores_non_json_files_in_sessions_dir(self) -> None:
        """Files that do not end in .json are ignored even if present in the sessions/ directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sess_dir)

            with open(os.path.join(sess_dir, "notes.txt"), "w") as f:
                f.write("some random text")

            sessions = get_active_sessions(tmpdir)
            self.assertEqual(len(sessions), 0)

    def test_no_sessions_directory_returns_empty_list(self) -> None:
        """When the sessions/ directory does not exist, an empty list is returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions = get_active_sessions(tmpdir)
            self.assertEqual(sessions, [])

    def test_session_missing_pid_key_is_skipped(self) -> None:
        """A session file that lacks the 'pid' key entirely is skipped (defaults to 0)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sess_dir = os.path.join(tmpdir, "sessions")
            os.makedirs(sess_dir)

            sess: dict[str, Any] = {"sessionId": "no-pid", "cwd": "/tmp", "startedAt": _now_ms()}
            with open(os.path.join(sess_dir, "nopid.json"), "w") as f:
                json.dump(sess, f)

            sessions = get_active_sessions(tmpdir)
            self.assertEqual(len(sessions), 0)


# ---------------------------------------------------------------------------
# Rate-limit header parsing
# ---------------------------------------------------------------------------

# Header prefix used by all rate-limit tests
_RL_PREFIX: str = "anthropic-ratelimit-unified-"


class TestRateLimitParsing(unittest.TestCase):
    """Tests for _parse_rate_limit_headers covering valid data and edge cases."""

    def _make_headers(self, overrides: dict[str, str] | None = None) -> dict[str, str]:
        """Return a minimal valid set of rate-limit headers, with optional overrides."""
        headers: dict[str, str] = {
            _RL_PREFIX + "5h-utilization": "0.42",
            _RL_PREFIX + "5h-reset": "1800000000",
            _RL_PREFIX + "7d-utilization": "0.75",
            _RL_PREFIX + "7d-reset": "1800000001",
            _RL_PREFIX + "overage-status": "allowed",
            _RL_PREFIX + "fallback": "available",
        }
        if overrides:
            headers.update(overrides)
        return headers

    def test_normal_headers_parsed_correctly(self) -> None:
        """All fields are returned with correct types and values from well-formed headers."""
        result = _parse_rate_limit_headers(self._make_headers())

        self.assertNotIn("error", result)
        self.assertAlmostEqual(result["session_utilization"], 0.42, places=5)
        self.assertEqual(result["session_reset"], 1800000000)
        self.assertAlmostEqual(result["weekly_utilization"], 0.75, places=5)
        self.assertEqual(result["weekly_reset"], 1800000001)
        self.assertEqual(result["overage_status"], "allowed")
        self.assertEqual(result["fallback_status"], "available")

    def test_missing_headers_returns_error(self) -> None:
        """A completely empty dict returns an error key."""
        result = _parse_rate_limit_headers({})
        self.assertIn("error", result)

    def test_missing_headers_with_unrelated_keys_returns_error(self) -> None:
        """Headers that contain no anthropic-ratelimit-unified- prefix return an error."""
        result = _parse_rate_limit_headers(
            {"content-type": "application/json", "x-request-id": "abc123"}
        )
        self.assertIn("error", result)

    def test_nan_utilization_falls_back_to_default(self) -> None:
        """A NaN string for a utilization header is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "nan"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_inf_utilization_falls_back_to_default(self) -> None:
        """An 'inf' string for a utilization header is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "inf"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_negative_inf_utilization_falls_back_to_default(self) -> None:
        """A '-inf' string for a utilization header is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "7d-utilization": "-inf"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["weekly_utilization"], 0.0)

    def test_negative_utilization_is_clamped_to_zero(self) -> None:
        """A negative utilization value is clamped to 0.0."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "-0.5"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_negative_reset_timestamp_is_clamped_to_zero(self) -> None:
        """A negative reset timestamp is clamped to 0."""
        headers = self._make_headers({_RL_PREFIX + "5h-reset": "-1000"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], 0)

    def test_empty_string_utilization_falls_back_to_default(self) -> None:
        """An empty string for a utilization header is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": ""})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_empty_string_reset_timestamp_falls_back_to_default(self) -> None:
        """An empty string for a reset timestamp is treated as 0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-reset": ""})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], 0)

    def test_millisecond_timestamp_is_divided_by_1000(self) -> None:
        """A reset timestamp above the year-2100 threshold (milliseconds) is divided by 1000."""
        ms_timestamp = 4_102_444_801_000
        expected_seconds = ms_timestamp // 1000
        headers = self._make_headers({_RL_PREFIX + "5h-reset": str(ms_timestamp)})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], expected_seconds)

    def test_utilization_above_one_is_clamped_to_one(self) -> None:
        """A utilization value above 1.0 is clamped to 1.0."""
        headers = self._make_headers({_RL_PREFIX + "7d-utilization": "1.5"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["weekly_utilization"], 1.0)

    def test_non_numeric_utilization_falls_back_to_default(self) -> None:
        """A non-numeric string for utilization is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "not-a-number"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_non_numeric_reset_falls_back_to_default(self) -> None:
        """A non-numeric string for a reset timestamp is treated as 0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-reset": "tomorrow"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], 0)

    def test_utilization_exactly_zero(self) -> None:
        """A utilization value of exactly '0' parses correctly to 0.0."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "0"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_utilization_exactly_one(self) -> None:
        """A utilization value of exactly '1.0' parses correctly and is not clamped."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "1.0"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 1.0)

    def test_float_format_reset_timestamp(self) -> None:
        """The API may send a reset timestamp as '1234567890.0'; it should be parsed as int."""
        headers = self._make_headers({_RL_PREFIX + "5h-reset": "1800000000.0"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], 1800000000)

    def test_overage_status_rejected(self) -> None:
        """The overage_status field correctly reflects a 'rejected' value."""
        headers = self._make_headers({_RL_PREFIX + "overage-status": "rejected"})
        result = _parse_rate_limit_headers(headers)
        self.assertEqual(result["overage_status"], "rejected")

    def test_fallback_status_empty_string(self) -> None:
        """When fallback header is an empty string, fallback_status is empty."""
        headers = self._make_headers({_RL_PREFIX + "fallback": ""})
        result = _parse_rate_limit_headers(headers)
        self.assertEqual(result["fallback_status"], "")

    def test_missing_optional_fields_use_defaults(self) -> None:
        """When only the prefix is present (triggering detection) but individual fields are missing, defaults are used."""
        headers: dict[str, str] = {_RL_PREFIX + "5h-utilization": "0.5"}
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertAlmostEqual(result["session_utilization"], 0.5)
        self.assertEqual(result["session_reset"], 0)
        self.assertAlmostEqual(result["weekly_utilization"], 0.0)
        self.assertEqual(result["weekly_reset"], 0)
        self.assertEqual(result["overage_status"], "")
        self.assertEqual(result["fallback_status"], "")


# ---------------------------------------------------------------------------
# Credential loading (macOS blank-usage hardening)
# ---------------------------------------------------------------------------


class TestLoadCredentials(unittest.TestCase):
    """The token lookup mirrors Claude Code's order: env var -> flat file ->
    macOS Keychain. Empty tokens count as 'not logged in'. Hardened after a
    macOS audit traced always-blank session/weekly to silent credential
    failures (the Keychain path being the only source on macOS)."""

    def setUp(self) -> None:
        from claude_usage.collector import _extract_token, _load_credentials
        self._extract = _extract_token
        self._load = _load_credentials
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    def tearDown(self) -> None:
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    def test_extract_valid(self) -> None:
        blob = json.dumps({"claudeAiOauth": {"accessToken": "sk-tok"}})
        self.assertEqual(self._extract(blob), "sk-tok")

    def test_extract_empty_token_is_none(self) -> None:
        blob = json.dumps({"claudeAiOauth": {"accessToken": "   "}})
        self.assertIsNone(self._extract(blob))

    def test_extract_missing_key_is_none(self) -> None:
        self.assertIsNone(self._extract(json.dumps({"foo": 1})))

    def test_extract_bad_json_is_none(self) -> None:
        self.assertIsNone(self._extract("not json"))

    def test_env_var_takes_priority(self) -> None:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "env-tok"
        # No file at this path, but the env var wins regardless.
        self.assertEqual(self._load("/nonexistent-dir"), "env-tok")

    def test_flat_file_token(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".credentials.json"), "w") as f:
                f.write(json.dumps({"claudeAiOauth": {"accessToken": "file-tok"}}))
            self.assertEqual(self._load(d), "file-tok")

    def test_empty_file_token_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".credentials.json"), "w") as f:
                f.write(json.dumps({"claudeAiOauth": {"accessToken": ""}}))
            # No env var, empty file token, non-macOS -> None.
            with patch("claude_usage.collector.sys.platform", "linux"):
                self.assertIsNone(self._load(d))

    def test_missing_everything_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch("claude_usage.collector.sys.platform", "linux"):
                self.assertIsNone(self._load(d))


# ---------------------------------------------------------------------------
# OAuth usage 429 handling (issue #11)
# ---------------------------------------------------------------------------


class TestOAuthUsage429(unittest.TestCase):
    """A 429 from /api/oauth/usage must surface a calm 'rate limited' state —
    never mislabeled 'credentials expired', never falling through to the
    x-api-key path. A budget-based 429 (no/zero Retry-After) must NOT be
    retried in-poll: this endpoint replies 'Retry-After: 0' once its quota is
    spent, and a retry burst there just burns the budget and keeps us
    throttled. Only an explicit positive Retry-After is worth waiting out."""

    def _http_error(self, code: int, retry_after: str | None = None):
        from urllib.error import HTTPError
        hdrs = {"Retry-After": retry_after} if retry_after is not None else {}
        return HTTPError("https://api", code, "err", hdrs, io.BytesIO(b"{}"))

    def test_429_zero_retry_after_returns_without_burst(self) -> None:
        # Retry-After: 0 means the budget is gone — return immediately, exactly
        # one request, no multi-request burst per poll.
        import claude_usage.collector as c
        calls = {"n": 0}

        def always_429(req, timeout=10, **kw):
            calls["n"] += 1
            raise self._http_error(429, retry_after="0")

        with patch.object(c, "urlopen", always_429), \
             patch.object(c.time, "sleep", lambda s: None):
            result = _fetch_oauth_usage("valid-token")

        self.assertTrue(result.get("rate_limited"))
        self.assertNotIn("expired", result["error"].lower())
        self.assertEqual(calls["n"], 1)  # no burst

    def test_429_no_retry_after_returns_without_burst(self) -> None:
        # Missing Retry-After header is treated the same as zero.
        import claude_usage.collector as c
        calls = {"n": 0}

        def always_429(req, timeout=10, **kw):
            calls["n"] += 1
            raise self._http_error(429)  # no Retry-After

        with patch.object(c, "urlopen", always_429), \
             patch.object(c.time, "sleep", lambda s: None):
            result = _fetch_oauth_usage("valid-token")

        self.assertTrue(result.get("rate_limited"))
        self.assertEqual(calls["n"], 1)

    def test_429_positive_retry_after_is_retried(self) -> None:
        # An explicit positive Retry-After IS honoured and retried.
        import claude_usage.collector as c
        calls = {"n": 0}

        def always_429(req, timeout=10, **kw):
            calls["n"] += 1
            raise self._http_error(429, retry_after="1")

        with patch.object(c, "urlopen", always_429), \
             patch.object(c.time, "sleep", lambda s: None):
            result = _fetch_oauth_usage("valid-token")

        self.assertTrue(result.get("rate_limited"))
        self.assertGreater(calls["n"], 1)  # actually retried

    def test_429_recovers_on_retry(self) -> None:
        import claude_usage.collector as c
        # Fail once with a positive Retry-After (so we retry), then succeed.
        seq = [self._http_error(429, retry_after="1"), None]

        def flaky(req, timeout=10, **kw):
            item = seq.pop(0)
            if item is not None:
                raise item
            return _CtxResp(json.dumps({
                "five_hour": {"utilization": 30.0, "resets_at": "2099-01-01T00:00:00+00:00"},
                "seven_day": {"utilization": 10.0, "resets_at": "2099-01-02T00:00:00+00:00"},
            }).encode())

        with patch.object(c, "urlopen", flaky), \
             patch.object(c.time, "sleep", lambda s: None):
            result = _fetch_oauth_usage("valid-token")

        self.assertNotIn("error", result)
        self.assertAlmostEqual(result["session_utilization"], 0.30, places=5)

    def test_401_still_reports_credentials_expired(self) -> None:
        import claude_usage.collector as c

        def always_401(req, timeout=10, **kw):
            raise self._http_error(401)

        with patch.object(c, "urlopen", always_401):
            result = _fetch_oauth_usage("bad-token")
        self.assertIn("expired", result["error"].lower())

    def test_fetch_rate_limits_skips_xapikey_on_429(self) -> None:
        """When the OAuth path is rate-limited, fetch_rate_limits must NOT try
        the /v1/messages x-api-key fallback (it can't auth an OAuth token and
        would mislabel the throttle as 'credentials expired')."""
        import claude_usage.collector as c

        def boom(*a, **k):
            raise AssertionError("x-api-key fallback must not run on 429")

        with patch.object(c, "_load_credentials", lambda d: "tok"), \
             patch.object(c, "_fetch_oauth_usage",
                          lambda t: {"error": "Rate limited", "rate_limited": True}), \
             patch.object(c, "urlopen", boom):
            result = fetch_rate_limits("/fake/dir")
        self.assertTrue(result.get("rate_limited"))

    def test_parse_retry_after(self) -> None:
        self.assertEqual(_parse_retry_after({"Retry-After": "5"}), 5.0)
        self.assertEqual(_parse_retry_after({"retry-after": "2.5"}), 2.5)
        self.assertIsNone(_parse_retry_after({}))
        self.assertIsNone(_parse_retry_after({"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}))
        self.assertIsNone(_parse_retry_after(None))


class TestScopedWeeklyLimit(unittest.TestCase):
    """The model-scoped weekly cap (e.g. Fable) is parsed from the `limits`
    array's weekly_scoped entry, labelled by scope.model.display_name, and
    auto-hides when the API stops reporting it (it's a temporary limit that
    Anthropic moves to credits after the Fable free window)."""

    def _usage_payload(self, limits):
        return {
            "five_hour": {"utilization": 12.0, "resets_at": "2099-01-01T00:00:00+00:00"},
            "seven_day": {"utilization": 61.0, "resets_at": "2099-01-02T00:00:00+00:00"},
            "extra_usage": {"is_enabled": False},
            "limits": limits,
        }

    def _fetch(self, payload):
        import claude_usage.collector as c

        def ok(req, timeout=10, **kw):
            return _CtxResp(json.dumps(payload).encode())

        with patch.object(c, "urlopen", ok):
            return _fetch_oauth_usage("tok")

    def test_scoped_weekly_extracted_and_labeled(self) -> None:
        r = self._fetch(self._usage_payload([
            {"kind": "weekly_all", "percent": 61, "resets_at": "2099-01-02T00:00:00+00:00"},
            {"kind": "weekly_scoped", "percent": 33,
             "resets_at": "2099-01-02T00:00:00+00:00",
             "scope": {"model": {"display_name": "Fable"}}},
        ]))
        self.assertAlmostEqual(r["scoped_utilization"], 0.33, places=5)
        self.assertEqual(r["scoped_label"], "Fable")
        self.assertGreater(r["scoped_reset"], 0)

    def test_no_scoped_limit_yields_empty_label(self) -> None:
        r = self._fetch(self._usage_payload([
            {"kind": "weekly_all", "percent": 61, "resets_at": "2099-01-02T00:00:00+00:00"},
        ]))
        self.assertEqual(r["scoped_label"], "")
        self.assertEqual(r["scoped_utilization"], 0.0)

    def test_missing_limits_array_is_safe(self) -> None:
        payload = self._usage_payload(None)
        del payload["limits"]
        r = self._fetch(payload)
        self.assertEqual(r["scoped_label"], "")

    def test_scoped_without_display_name_skipped(self) -> None:
        r = self._fetch(self._usage_payload([
            {"kind": "weekly_scoped", "percent": 50,
             "resets_at": "2099-01-02T00:00:00+00:00",
             "scope": {"model": {"display_name": ""}}},
        ]))
        self.assertEqual(r["scoped_label"], "")

    def test_highest_utilised_scoped_wins(self) -> None:
        r = self._fetch(self._usage_payload([
            {"kind": "weekly_scoped", "percent": 20,
             "resets_at": "2099-01-02T00:00:00+00:00",
             "scope": {"model": {"display_name": "Sonnet"}}},
            {"kind": "weekly_scoped", "percent": 70,
             "resets_at": "2099-01-02T00:00:00+00:00",
             "scope": {"model": {"display_name": "Fable"}}},
        ]))
        self.assertEqual(r["scoped_label"], "Fable")
        self.assertAlmostEqual(r["scoped_utilization"], 0.70, places=5)

    @patch("claude_usage.collector.fetch_rate_limits")
    def test_scoped_restored_and_clamped_on_throttle(self, mock_fetch: Any) -> None:
        """A throttled poll restores the scoped triple from history; an
        expired scoped window clamps to hidden."""
        from claude_usage.history import append_sample
        mock_fetch.return_value = {"error": "Rate limited", "rate_limited": True}
        now = datetime.now().timestamp()
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = os.path.join(tmpdir, "usage-history.jsonl")
            # live scoped window, still in the future
            append_sample(sp, now - 60, 0.1, 0.6,
                          session_reset=int(now + 3600),
                          weekly_reset=int(now + 86400),
                          scoped=0.44, scoped_reset=int(now + 86400),
                          scoped_label="Fable")
            stats = collect_all({"claude_dir": tmpdir})
            self.assertEqual(stats.scoped_label, "Fable")
            self.assertAlmostEqual(stats.scoped_utilization, 0.44)

        with tempfile.TemporaryDirectory() as tmpdir:
            sp = os.path.join(tmpdir, "usage-history.jsonl")
            # expired scoped window -> hidden
            append_sample(sp, now - 60, 0.1, 0.6,
                          weekly_reset=int(now + 86400),
                          scoped=0.44, scoped_reset=int(now - 3600),
                          scoped_label="Fable")
            stats = collect_all({"claude_dir": tmpdir})
            self.assertEqual(stats.scoped_label, "")
            self.assertEqual(stats.scoped_utilization, 0.0)


class _CtxResp:
    """Minimal context-manager stand-in for urlopen's response object."""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self._headers = dict(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._body

    def getheaders(self) -> list[tuple[str, str]]:
        # Real urlopen responses expose getheaders(); the fetch_rate_limits
        # fallback calls it, so the stand-in must mirror it or a signature
        # drift there would be invisible to tests (the context= lesson).
        return list(self._headers.items())


# ---------------------------------------------------------------------------
# collect_all integration
# ---------------------------------------------------------------------------


class TestCollectAll(unittest.TestCase):
    """Integration tests for collect_all with mocked API calls."""

    @patch("claude_usage.collector.fetch_rate_limits")
    def test_collect_all_integrates_history_and_tokens(self, mock_fetch: Any) -> None:
        """collect_all combines history stats, token totals, and rate-limit data."""
        mock_fetch.return_value = {
            "session_utilization": 0.33,
            "session_reset": 1700000000,
            "weekly_utilization": 0.66,
            "weekly_reset": 1700000001,
            "overage_status": "allowed",
            "fallback_status": "available",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a history file with one message
            history_path = os.path.join(tmpdir, "history.jsonl")
            now = _now_ms()
            with open(history_path, "w") as f:
                f.write(json.dumps({"display": "hi", "timestamp": now, "sessionId": "s1", "project": "/p"}) + "\n")

            # Create a conversation file with tokens. The date prefix MUST be
            # UTC — collect_all buckets by UTC date, so a local-time prefix
            # makes this test false-safe: green on UTC CI, red for anyone
            # west of UTC after their local evening.
            proj_dir = _make_conversation_dir(tmpdir)
            from datetime import timezone as _tz
            today_str = datetime.now(_tz.utc).strftime("%Y-%m-%d")
            _write_conversation(proj_dir, [
                _assistant_entry(f"{today_str}T10:00:00", output_tokens=500),
            ])

            config: dict[str, Any] = {"claude_dir": tmpdir}
            stats = collect_all(config)

            self.assertEqual(stats.today_messages, 1)
            self.assertEqual(stats.today_tokens, 500)
            self.assertAlmostEqual(stats.session_utilization, 0.33)
            self.assertEqual(stats.overage_status, "allowed")
            self.assertEqual(stats.rate_limit_error, "")

    @patch("claude_usage.collector.fetch_rate_limits")
    def test_collect_all_records_rate_limit_error(self, mock_fetch: Any) -> None:
        """When the rate-limit API fails, the error is stored but other stats remain valid."""
        mock_fetch.return_value = {"error": "No credentials found"}

        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = os.path.join(tmpdir, "history.jsonl")
            now = _now_ms()
            with open(history_path, "w") as f:
                f.write(json.dumps({"display": "hi", "timestamp": now, "sessionId": "s1", "project": "/p"}) + "\n")

            config: dict[str, Any] = {"claude_dir": tmpdir}
            stats = collect_all(config)

            self.assertEqual(stats.today_messages, 1)
            self.assertEqual(stats.rate_limit_error, "No credentials found")
            # Rate-limit fields should remain at defaults
            self.assertAlmostEqual(stats.session_utilization, 0.0)

    @patch("claude_usage.collector.fetch_rate_limits")
    def test_collect_all_with_empty_directory(self, mock_fetch: Any) -> None:
        """collect_all handles a completely empty claude_dir without crashing."""
        mock_fetch.return_value = {"error": "No credentials found"}

        with tempfile.TemporaryDirectory() as tmpdir:
            config: dict[str, Any] = {"claude_dir": tmpdir}
            stats = collect_all(config)

            self.assertEqual(stats.today_messages, 0)
            self.assertEqual(stats.today_tokens, 0)
            self.assertEqual(stats.week_tokens, 0)
            self.assertEqual(stats.active_sessions, [])


class TestCollectAllStaleFallback(unittest.TestCase):
    """When a poll is rate-limited/errored, collect_all falls back to the last
    on-disk sample — but a window whose reset time has already passed has rolled
    over, so its true utilization is 0, not the stale sample value. Without this
    the OSD shows a whole expired cycle's usage until the API recovers."""

    @patch("claude_usage.collector.fetch_rate_limits")
    def test_expired_session_window_falls_back_to_zero(self, mock_fetch: Any) -> None:
        from claude_usage.history import append_sample

        mock_fetch.return_value = {"error": "Rate limited -- using last known values",
                                   "rate_limited": True}
        now = datetime.now().timestamp()
        with tempfile.TemporaryDirectory() as tmpdir:
            samples_path = os.path.join(tmpdir, "usage-history.jsonl")
            # Last sample: a busy session whose 5h window already reset an hour
            # ago, but whose 7d window is still days out.
            append_sample(
                samples_path, now - 7200, 0.82, 0.40,
                session_reset=int(now - 3600),       # expired
                weekly_reset=int(now + 3 * 86400),   # still current
            )

            stats = collect_all({"claude_dir": tmpdir})

            # Expired 5h window -> zeroed, countdown cleared.
            self.assertEqual(stats.session_utilization, 0.0)
            self.assertEqual(stats.session_reset, 0)
            # Still-current 7d window -> stale value preserved.
            self.assertAlmostEqual(stats.weekly_utilization, 0.40)
            self.assertEqual(stats.weekly_reset, int(now + 3 * 86400))

    @patch("claude_usage.collector.fetch_rate_limits")
    def test_current_window_preserves_last_known(self, mock_fetch: Any) -> None:
        from claude_usage.history import append_sample

        mock_fetch.return_value = {"error": "Rate limited -- using last known values",
                                   "rate_limited": True}
        now = datetime.now().timestamp()
        with tempfile.TemporaryDirectory() as tmpdir:
            samples_path = os.path.join(tmpdir, "usage-history.jsonl")
            append_sample(
                samples_path, now - 60, 0.55, 0.25,
                session_reset=int(now + 1800),       # still current
                weekly_reset=int(now + 3 * 86400),
            )

            stats = collect_all({"claude_dir": tmpdir})

            # Both windows still current -> last-known values survive (issue #11).
            self.assertAlmostEqual(stats.session_utilization, 0.55)
            self.assertEqual(stats.session_reset, int(now + 1800))
            self.assertAlmostEqual(stats.weekly_utilization, 0.25)


class TestAuditFixesV093(unittest.TestCase):
    """Regression tests for the v0.9.3 audit fixes: 5xx retry, OAuth-token
    fallback skip, independent reset-key scan, and news opt-in gating."""

    def _http_error(self, code: int):
        from urllib.error import HTTPError
        return HTTPError("https://api", code, "err", {}, io.BytesIO(b"{}"))

    def test_5xx_is_retried_and_can_recover(self) -> None:
        import claude_usage.collector as c
        seq = [self._http_error(503), None]  # one 503, then success

        def flaky(req, timeout=10, **kw):
            item = seq.pop(0)
            if item is not None:
                raise item
            return _CtxResp(json.dumps({
                "five_hour": {"utilization": 20.0, "resets_at": "2099-01-01T00:00:00+00:00"},
                "seven_day": {"utilization": 5.0, "resets_at": "2099-01-02T00:00:00+00:00"},
            }).encode())

        with patch.object(c, "urlopen", flaky), \
             patch.object(c.time, "sleep", lambda s: None):
            result = _fetch_oauth_usage("valid-token")
        self.assertNotIn("error", result)
        self.assertAlmostEqual(result["session_utilization"], 0.20, places=5)

    def test_5xx_exhausts_retries_then_errors(self) -> None:
        import claude_usage.collector as c
        calls = {"n": 0}

        def always_503(req, timeout=10, **kw):
            calls["n"] += 1
            raise self._http_error(503)

        with patch.object(c, "urlopen", always_503), \
             patch.object(c.time, "sleep", lambda s: None):
            result = _fetch_oauth_usage("valid-token")
        self.assertIn("error", result)
        self.assertGreater(calls["n"], 1)  # actually retried before giving up

    def test_oauth_token_never_hits_xapikey_fallback(self) -> None:
        """An sk-ant-oat token can't authenticate as an x-api-key; on any
        primary failure the fallback must be skipped so a transient 5xx is
        never mislabeled 'Credentials expired'."""
        import claude_usage.collector as c

        def boom(*a, **k):
            raise AssertionError("x-api-key fallback must not run for OAuth tokens")

        with patch.object(c, "_load_credentials", lambda d: "sk-ant-oat01-xyz"), \
             patch.object(c, "_fetch_oauth_usage",
                          lambda t: {"error": "OAuth usage error 503"}), \
             patch.object(c, "urlopen", boom):
            result = fetch_rate_limits("/fake/dir")
        self.assertEqual(result["error"], "OAuth usage error 503")

    @patch("claude_usage.collector.fetch_rate_limits")
    def test_reset_scan_searches_keys_independently(self, mock_fetch: Any) -> None:
        """A newer sample carrying only weekly_reset must not bury an older
        sample's session_reset — otherwise the expired-window clamp can be
        bypassed and a finished 5h window keeps showing stale utilization."""
        from claude_usage.history import append_sample

        mock_fetch.return_value = {"error": "Rate limited", "rate_limited": True}
        now = datetime.now().timestamp()
        with tempfile.TemporaryDirectory() as tmpdir:
            samples_path = os.path.join(tmpdir, "usage-history.jsonl")
            # Older sample: both resets; session window expired an hour ago.
            append_sample(samples_path, now - 7200, 0.82, 0.40,
                          session_reset=int(now - 3600),
                          weekly_reset=int(now + 3 * 86400))
            # Newest sample: only weekly_reset (session_reset was 0 from API).
            append_sample(samples_path, now - 60, 0.82, 0.41,
                          weekly_reset=int(now + 3 * 86400))

            stats = collect_all({"claude_dir": tmpdir})

            # session_reset must be found in the OLDER sample and, being
            # expired, clamp session utilization to zero.
            self.assertEqual(stats.session_utilization, 0.0)
            self.assertEqual(stats.session_reset, 0)
            # weekly stays live from the newest sample.
            self.assertAlmostEqual(stats.weekly_utilization, 0.41)

    @patch("claude_usage.collector.fetch_rate_limits")
    @patch("claude_usage.collector.get_news_items")
    def test_news_not_fetched_when_opted_out(self, mock_news: Any, mock_fetch: Any) -> None:
        mock_fetch.return_value = {"error": "x"}
        with tempfile.TemporaryDirectory() as tmpdir:
            collect_all({"claude_dir": tmpdir})           # show_news absent
            collect_all({"claude_dir": tmpdir, "show_news": False})
        mock_news.assert_not_called()

    @patch("claude_usage.collector.fetch_rate_limits")
    @patch("claude_usage.collector.get_news_items")
    def test_news_fetched_when_opted_in(self, mock_news: Any, mock_fetch: Any) -> None:
        mock_fetch.return_value = {"error": "x"}
        mock_news.return_value = []
        with tempfile.TemporaryDirectory() as tmpdir:
            collect_all({"claude_dir": tmpdir, "show_news": True})
        mock_news.assert_called_once()


class TestMonthTokenCollection(unittest.TestCase):
    """_collect_month_tokens: the separate ~32-day, month-prefix budget scan."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def test_sums_current_month_excludes_other_month(self) -> None:
        now = datetime.now(timezone.utc)
        month_prefix = now.strftime("%Y-%m")
        # Day 15 is always valid and avoids month-boundary flakiness.
        cur = self._iso(now.replace(day=15, hour=12, minute=0, second=0, microsecond=0))
        prev = self._iso(now.replace(day=1) - timedelta(days=5))  # previous month
        proj = _make_conversation_dir(self.tmp, "-home-user-proj")
        _write_conversation(proj, [
            _assistant_entry(cur, output_tokens=1000, input_tokens=200),
            _assistant_entry(cur, output_tokens=500, input_tokens=100),
            _assistant_entry(prev, output_tokens=9999, input_tokens=9999),
        ])
        by_model = _collect_month_tokens(self.tmp, month_prefix)
        self.assertIn("claude-opus-4-6", by_model)
        bucket = by_model["claude-opus-4-6"]
        self.assertEqual(bucket["output"], 1500)   # prev-month 9999 excluded
        self.assertEqual(bucket["input"], 300)

    def test_skips_subagent_conversations(self) -> None:
        now = datetime.now(timezone.utc)
        cur = self._iso(now.replace(day=15, hour=12))
        sub = _make_conversation_dir(self.tmp, "-home-user-proj", subagent=True)
        _write_conversation(sub, [_assistant_entry(cur, output_tokens=1000)])
        self.assertEqual(_collect_month_tokens(self.tmp, now.strftime("%Y-%m")), {})

    def test_skips_files_older_than_32_days(self) -> None:
        now = datetime.now(timezone.utc)
        cur = self._iso(now.replace(day=15, hour=12))
        proj = _make_conversation_dir(self.tmp, "-home-user-proj")
        path = _write_conversation(proj, [_assistant_entry(cur, output_tokens=1000)])
        old = datetime.now().timestamp() - 40 * 86400
        os.utime(path, (old, old))
        self.assertEqual(_collect_month_tokens(self.tmp, now.strftime("%Y-%m")), {})

    def test_missing_projects_dir_returns_empty(self) -> None:
        self.assertEqual(_collect_month_tokens(self.tmp, "2026-07"), {})


class TestBurnDetectionWiring(unittest.TestCase):
    """Guard the collector→burn.py contract: the real TickerItem / sample-dict
    attributes the detectors read, so a future field rename fails loudly here."""

    def test_real_ticker_item_feeds_spike_detector(self) -> None:
        from claude_usage.burn import detect_token_spike
        from claude_usage.ticker import TickerItem
        turns = [
            TickerItem(ts=100.0, msg_id="m0", cost_usd=1.0, tool="",
                       output_tokens=50_000, model="x"),
        ] + [
            TickerItem(ts=90.0 - i, msg_id=f"m{i+1}", cost_usd=0.1, tool="",
                       output_tokens=2_000, model="x")
            for i in range(6)
        ]
        alert = detect_token_spike(
            turns, multiplier=4.0, min_tokens=20_000, min_baseline_turns=5,
        )
        self.assertTrue(alert.active)
        self.assertEqual(alert.msg_id, "m0")

    def test_real_sample_dicts_feed_fast_burn(self) -> None:
        from claude_usage.burn import detect_fast_burn
        # Same {ts, session, weekly} shape history.load_samples yields.
        samples = [
            {"ts": 0.0, "session": 0.10, "weekly": 0.2},
            {"ts": 540.0, "session": 0.55, "weekly": 0.2},
        ]
        alert = detect_fast_burn(samples, now=540.0, warn_pm=2.0, crit_pm=5.0,
                                 window_s=600.0)
        self.assertTrue(alert.active)
        self.assertEqual(alert.kind, "fast_burn")


if __name__ == "__main__":
    unittest.main()
