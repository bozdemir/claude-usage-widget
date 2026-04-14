import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from claude_usage.collector import parse_history, UsageStats, collect_tokens_from_conversations, get_active_sessions, collect_all


def _make_history_file(entries):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for entry in entries:
        f.write(json.dumps(entry) + "\n")
    f.close()
    return f.name


class TestParseHistory(unittest.TestCase):
    def test_counts_messages_for_today(self):
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
        path = _make_history_file([])
        try:
            stats = parse_history(path)
            self.assertEqual(stats.today_messages, 0)
            self.assertEqual(stats.week_messages, 0)
        finally:
            os.unlink(path)


class TestTokenCollection(unittest.TestCase):
    def test_collects_tokens_from_conversation_file(self):
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


if __name__ == "__main__":
    unittest.main()
