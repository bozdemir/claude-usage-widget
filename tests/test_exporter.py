"""Tests for CSV / JSON history export."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import time
import unittest

from claude_usage.exporter import export_history


def _write_history(path: str, samples: list[dict]) -> None:
    with open(path, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")


class TestExportHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self.path = self.tmp.name

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_export_csv_writes_header_and_rows(self):
        now = time.time()
        _write_history(self.path, [
            {"ts": now, "session": 0.5, "weekly": 0.1},
            {"ts": now - 100, "session": 0.3, "weekly": 0.05},
        ])
        out = io.StringIO()
        count = export_history(self.path, fmt="csv", days=7, out=out, now=now)
        self.assertEqual(count, 2)
        reader = csv.reader(io.StringIO(out.getvalue()))
        rows = list(reader)
        self.assertEqual(rows[0], ["ts", "iso", "session", "weekly"])
        self.assertEqual(len(rows), 3)  # header + 2 rows

    def test_export_json_emits_array(self):
        now = time.time()
        _write_history(self.path, [{"ts": now, "session": 0.1, "weekly": 0.02}])
        out = io.StringIO()
        count = export_history(self.path, fmt="json", days=7, out=out, now=now)
        self.assertEqual(count, 1)
        data = json.loads(out.getvalue())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["session"], 0.1)

    def test_export_filters_by_days(self):
        now = time.time()
        _write_history(self.path, [
            {"ts": now, "session": 0.5, "weekly": 0.1},
            {"ts": now - 8 * 86400, "session": 0.9, "weekly": 0.9},
        ])
        out = io.StringIO()
        count = export_history(self.path, fmt="csv", days=7, out=out, now=now)
        self.assertEqual(count, 1)

    def test_export_missing_file_writes_empty(self):
        out = io.StringIO()
        count = export_history("/nonexistent/path.jsonl", fmt="csv", days=7, out=out)
        self.assertEqual(count, 0)
        self.assertIn("ts,iso,session,weekly", out.getvalue())

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            export_history(self.path, fmt="xml", days=7, out=io.StringIO())


if __name__ == "__main__":
    unittest.main()
