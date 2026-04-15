"""Tests for the claude_usage.collector module, covering history parsing, token aggregation, and session detection."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from claude_usage.collector import (
    parse_history,
    UsageStats,
    collect_tokens_from_conversations,
    get_active_sessions,
    collect_all,
    _parse_rate_limit_headers,
)


def _make_history_file(entries):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for entry in entries:
        f.write(json.dumps(entry) + "\n")
    f.close()
    return f.name


class TestParseHistory(unittest.TestCase):
    def test_counts_messages_for_today(self):
        """Verifies that only messages timestamped today are counted in today_messages."""
        now_ms = int(datetime.now().timestamp() * 1000)
        yesterday_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
        entries = [
            {"display": "msg1", "timestamp": now_ms, "sessionId": "s1", "project": "/p"},
            {"display": "msg2", "timestamp": now_ms + 1000, "sessionId": "s1", "project": "/p"},
            {"display": "old", "timestamp": yesterday_ms, "sessionId": "s2", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 2)
        finally:
            os.unlink(path)

    def test_counts_weekly_messages(self):
        """Verifies that messages within the past 7 days are counted in week_messages while older ones are excluded."""
        now = datetime.now()
        now_ms = int(now.timestamp() * 1000)
        week_ago_ms = int((now - timedelta(days=3)).timestamp() * 1000)
        old_ms = int((now - timedelta(days=10)).timestamp() * 1000)
        entries = [
            {"display": "m1", "timestamp": now_ms, "sessionId": "s1", "project": "/p"},
            {"display": "m2", "timestamp": week_ago_ms, "sessionId": "s2", "project": "/p"},
            {"display": "m3", "timestamp": old_ms, "sessionId": "s3", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.week_messages, 2)
        finally:
            os.unlink(path)

    def test_counts_unique_sessions_today(self):
        """Verifies that today_sessions reflects the number of distinct session IDs seen today."""
        now_ms = int(datetime.now().timestamp() * 1000)
        entries = [
            {"display": "m1", "timestamp": now_ms, "sessionId": "s1", "project": "/p"},
            {"display": "m2", "timestamp": now_ms + 1, "sessionId": "s1", "project": "/p"},
            {"display": "m3", "timestamp": now_ms + 2, "sessionId": "s2", "project": "/p"},
        ]
        path = _make_history_file(entries)
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_sessions, 2)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        """Verifies that parsing an empty history file returns zero counts for all stats."""
        path = _make_history_file([])
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 0)
            self.assertEqual(stats.week_messages, 0)
        finally:
            os.unlink(path)


class TestTokenCollection(unittest.TestCase):
    def test_collects_tokens_from_conversation_file(self):
        """Verifies that token counts are correctly summed across multiple assistant messages in a conversation file."""
        tmpdir = tempfile.mkdtemp()
        proj_dir = os.path.join(tmpdir, "projects", "-home-test")
        os.makedirs(proj_dir)

        conv_path = os.path.join(proj_dir, "session-abc.jsonl")
        now_iso = datetime.now().isoformat()
        messages = [
            {"type": "user", "timestamp": now_iso},
            {
                "type": "assistant",
                "timestamp": now_iso,
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 500,
                        "cache_read_input_tokens": 1000,
                        "cache_creation_input_tokens": 200,
                    },
                },
            },
            {
                "type": "assistant",
                "timestamp": now_iso,
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {
                        "input_tokens": 50,
                        "output_tokens": 300,
                        "cache_read_input_tokens": 500,
                        "cache_creation_input_tokens": 100,
                    },
                },
            },
        ]
        with open(conv_path, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        tokens = collect_tokens_from_conversations(tmpdir, [now_iso[:10]])
        self.assertEqual(tokens["total_output"], 800)
        self.assertEqual(tokens["by_model"]["claude-opus-4-6"]["output"], 800)

        import shutil

        shutil.rmtree(tmpdir)


class TestActiveSessions(unittest.TestCase):
    def test_reads_session_files(self):
        """Verifies that a session file for a live PID is read and returned by get_active_sessions."""
        tmpdir = tempfile.mkdtemp()
        sess_dir = os.path.join(tmpdir, "sessions")
        os.makedirs(sess_dir)

        my_pid = os.getpid()
        sess = {
            "pid": my_pid,
            "sessionId": "test-session",
            "cwd": "/home/test",
            "startedAt": int(datetime.now().timestamp() * 1000),
        }
        with open(os.path.join(sess_dir, f"{my_pid}.json"), "w") as f:
            json.dump(sess, f)

        sessions = get_active_sessions(tmpdir)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["sessionId"], "test-session")

        import shutil

        shutil.rmtree(tmpdir)

    def test_skips_dead_sessions(self):
        """Verifies that session files whose PID no longer exists are excluded from active sessions."""
        tmpdir = tempfile.mkdtemp()
        sess_dir = os.path.join(tmpdir, "sessions")
        os.makedirs(sess_dir)

        sess = {
            "pid": 999999999,
            "sessionId": "dead-session",
            "cwd": "/tmp",
            "startedAt": int(datetime.now().timestamp() * 1000),
        }
        with open(os.path.join(sess_dir, "999999999.json"), "w") as f:
            json.dump(sess, f)

        sessions = get_active_sessions(tmpdir)
        self.assertEqual(len(sessions), 0)

        import shutil

        shutil.rmtree(tmpdir)


# Header prefix used by all rate-limit tests
_RL_PREFIX = "anthropic-ratelimit-unified-"


class TestRateLimitParsing(unittest.TestCase):
    """Tests for _parse_rate_limit_headers covering valid data and edge cases."""

    def _make_headers(self, overrides=None):
        """Return a minimal valid set of rate-limit headers, with optional overrides."""
        headers = {
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

    def test_normal_headers_parsed_correctly(self):
        """All fields are returned with correct types and values from well-formed headers."""
        result = _parse_rate_limit_headers(self._make_headers())

        self.assertNotIn("error", result)
        self.assertAlmostEqual(result["session_utilization"], 0.42, places=5)
        self.assertEqual(result["session_reset"], 1800000000)
        self.assertAlmostEqual(result["weekly_utilization"], 0.75, places=5)
        self.assertEqual(result["weekly_reset"], 1800000001)
        self.assertEqual(result["overage_status"], "allowed")
        self.assertEqual(result["fallback_status"], "available")

    def test_missing_headers_returns_error(self):
        """A completely empty dict returns an error key."""
        result = _parse_rate_limit_headers({})
        self.assertIn("error", result)

    def test_missing_headers_with_unrelated_keys_returns_error(self):
        """Headers that contain no anthropic-ratelimit-unified- prefix return an error."""
        result = _parse_rate_limit_headers(
            {"content-type": "application/json", "x-request-id": "abc123"}
        )
        self.assertIn("error", result)

    def test_nan_utilization_falls_back_to_default(self):
        """A NaN string for a utilization header is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "nan"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_negative_utilization_is_clamped_to_zero(self):
        """A negative utilization value is clamped to 0.0."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "-0.5"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_negative_reset_timestamp_is_clamped_to_zero(self):
        """A negative reset timestamp is clamped to 0."""
        headers = self._make_headers({_RL_PREFIX + "5h-reset": "-1000"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], 0)

    def test_empty_string_utilization_falls_back_to_default(self):
        """An empty string for a utilization header is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": ""})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)

    def test_empty_string_reset_timestamp_falls_back_to_default(self):
        """An empty string for a reset timestamp is treated as 0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-reset": ""})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], 0)

    def test_millisecond_timestamp_is_divided_by_1000(self):
        """A reset timestamp above the year-2100 threshold (milliseconds) is divided by 1000."""
        # 4_102_444_800 is the cutoff (seconds); supply a value clearly above it in ms
        ms_timestamp = 4_102_444_801_000  # well above the 4_102_444_800 seconds threshold
        expected_seconds = ms_timestamp // 1000
        headers = self._make_headers({_RL_PREFIX + "5h-reset": str(ms_timestamp)})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_reset"], expected_seconds)

    def test_utilization_above_one_is_clamped_to_one(self):
        """A utilization value above 1.0 is clamped to 1.0."""
        headers = self._make_headers({_RL_PREFIX + "7d-utilization": "1.5"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["weekly_utilization"], 1.0)

    def test_non_numeric_utilization_falls_back_to_default(self):
        """A non-numeric string for utilization is treated as 0.0 (the default)."""
        headers = self._make_headers({_RL_PREFIX + "5h-utilization": "not-a-number"})
        result = _parse_rate_limit_headers(headers)
        self.assertNotIn("error", result)
        self.assertEqual(result["session_utilization"], 0.0)


if __name__ == "__main__":
    unittest.main()
