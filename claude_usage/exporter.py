"""CSV / JSON export of the history.jsonl sample stream.

Pure module — takes a path and a file-like destination. The CLI wires this
to stdout when --export is passed; tests supply a StringIO so they never
touch the real filesystem.
"""

from __future__ import annotations

import csv
import json
import os
import time as _time
from datetime import datetime, timezone
from typing import IO, Iterator


CSV_HEADER = ["ts", "iso", "session", "weekly"]


def _iter_samples(path: str, cutoff_ts: float) -> Iterator[dict]:
    """Yield JSON-decoded samples from *path* with ts >= cutoff_ts."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("ts", 0) >= cutoff_ts:
                yield entry


def export_history(
    path: str,
    fmt: str,
    days: int,
    out: IO[str],
    now: float | None = None,
) -> int:
    """Write the last *days* of history samples to *out* in *fmt*.

    Args:
        path: Path to history.jsonl.
        fmt: "csv" or "json".
        days: Look-back window (sample kept if ts >= now - days*86400).
        out: Text-mode writable (e.g. sys.stdout or StringIO).
        now: Unix timestamp used as the upper bound. Defaults to time.time().

    Returns:
        Number of samples written.

    Raises:
        ValueError: If fmt is not "csv" or "json".
    """
    if fmt not in ("csv", "json"):
        raise ValueError(f"Unknown export format: {fmt!r}")

    if now is None:
        now = _time.time()
    cutoff = now - days * 86400

    if fmt == "csv":
        writer = csv.writer(out)
        writer.writerow(CSV_HEADER)
        count = 0
        for s in _iter_samples(path, cutoff):
            ts = float(s.get("ts", 0))
            writer.writerow([
                ts,
                datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds"),
                float(s.get("session", 0.0)),
                float(s.get("weekly", 0.0)),
            ])
            count += 1
        return count

    # JSON array
    samples = list(_iter_samples(path, cutoff))
    json.dump(samples, out, indent=2)
    out.write("\n")
    return len(samples)
