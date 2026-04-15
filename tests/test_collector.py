"""Tests for the claude_usage.collector module.

Covers history parsing, token aggregation, session detection, subagent
filtering, rate-limit header parsing, and the collect_all integration path.
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

from claude_usage.collector import (
    UsageStats,
    _collect_tokens_single_pass,
    _parse_rate_limit_headers,
    collect_all,
    collect_tokens_from_conversations,
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

            # Create a conversation file with tokens
            proj_dir = _make_conversation_dir(tmpdir)
            today_str = datetime.now().strftime("%Y-%m-%d")
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


if __name__ == "__main__":
    unittest.main()
