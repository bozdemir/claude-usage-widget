import json
import os
import tempfile
import unittest

from claude_usage.history import aggregate, append_sample, load_samples, prune


class TestAggregate(unittest.TestCase):
    def test_empty_points_returns_zeros(self):
        self.assertEqual(aggregate([], "session", now=100, window_seconds=60, n_buckets=6), [0.0] * 6)

    def test_invalid_params_return_empty(self):
        self.assertEqual(aggregate([{"ts": 1, "session": 0.5}], "session", 100, 0, 6), [])
        self.assertEqual(aggregate([{"ts": 1, "session": 0.5}], "session", 100, 60, 0), [])

    def test_buckets_use_max_within_slice(self):
        # window 60s, 6 buckets of 10s, now=100 → buckets cover [40,50),[50,60),...,[90,100]
        points = [
            {"ts": 45, "session": 0.30},
            {"ts": 48, "session": 0.50},  # max in bucket 0
            {"ts": 95, "session": 0.80},  # bucket 5
        ]
        result = aggregate(points, "session", now=100, window_seconds=60, n_buckets=6)
        self.assertEqual(result[0], 0.50)
        self.assertEqual(result[5], 0.80)
        self.assertEqual(result[1], 0.0)

    def test_points_outside_window_ignored(self):
        points = [
            {"ts": 10, "session": 0.99},  # before window
            {"ts": 200, "session": 0.99},  # after now
            {"ts": 50, "session": 0.40},
        ]
        result = aggregate(points, "session", now=100, window_seconds=60, n_buckets=6)
        self.assertEqual(max(result), 0.40)

    def test_picks_correct_key(self):
        points = [{"ts": 50, "session": 0.10, "weekly": 0.90}]
        s = aggregate(points, "session", now=100, window_seconds=60, n_buckets=6)
        w = aggregate(points, "weekly", now=100, window_seconds=60, n_buckets=6)
        self.assertEqual(max(s), 0.10)
        self.assertEqual(max(w), 0.90)

    def test_now_boundary_value_lands_in_last_bucket(self):
        points = [{"ts": 100, "session": 0.7}]
        result = aggregate(points, "session", now=100, window_seconds=60, n_buckets=6)
        self.assertEqual(result[-1], 0.7)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self.path = self.tmp.name
        os.unlink(self.path)  # let append_sample create it

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_append_and_load_roundtrip(self):
        append_sample(self.path, ts=100.0, session_util=0.5, weekly_util=0.1)
        append_sample(self.path, ts=200.0, session_util=0.6, weekly_util=0.2)
        samples = load_samples(self.path)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]["ts"], 100.0)
        self.assertEqual(samples[1]["session"], 0.6)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load_samples("/nonexistent/path.jsonl"), [])

    def test_load_skips_corrupt_lines(self):
        with open(self.path, "w") as f:
            f.write('{"ts": 1, "session": 0.1, "weekly": 0.1}\n')
            f.write("not valid json\n")
            f.write('{"ts": 2, "session": 0.2, "weekly": 0.2}\n')
        samples = load_samples(self.path)
        self.assertEqual(len(samples), 2)

    def test_load_filters_by_since_ts(self):
        for i in range(5):
            append_sample(self.path, ts=float(i * 100), session_util=0.1, weekly_util=0.1)
        samples = load_samples(self.path, since_ts=250.0)
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]["ts"], 300.0)

    def test_prune_drops_old_entries(self):
        for i in range(5):
            append_sample(self.path, ts=float(i * 100), session_util=0.1, weekly_util=0.1)
        # cutoff = 400 - 250 = 150 → keep 200, 300, 400
        kept = prune(self.path, keep_seconds=250.0, now=400.0)
        self.assertEqual(kept, 3)
        samples = load_samples(self.path)
        self.assertEqual([s["ts"] for s in samples], [200.0, 300.0, 400.0])

    def test_prune_missing_file_is_noop(self):
        self.assertEqual(prune("/nonexistent/p.jsonl", keep_seconds=100, now=200), 0)


if __name__ == "__main__":
    unittest.main()
