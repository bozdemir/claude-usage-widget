"""Time-series storage for past utilization samples.

Samples are appended to a JSONL file as `{ts, session, weekly}`. The pure
`aggregate` function turns a point list into fixed-width buckets for sparkline
rendering; tests cover it directly.
"""

import json
import os
import tempfile


def append_sample(path: str, ts: float, session_util: float, weekly_util: float) -> None:
    """Append one sample to the JSONL history file."""
    line = json.dumps({
        "ts": float(ts),
        "session": float(session_util),
        "weekly": float(weekly_util),
    })
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(line + "\n")


def load_samples(path: str, since_ts: float = 0.0) -> list[dict]:
    """Read all samples from JSONL, optionally filtering to `ts >= since_ts`."""
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("ts", 0) >= since_ts:
                out.append(entry)
    return out


def prune(path: str, keep_seconds: float, now: float) -> int:
    """Rewrite file dropping samples older than `now - keep_seconds`. Returns kept count."""
    if not os.path.isfile(path):
        return 0
    cutoff = now - keep_seconds
    kept = load_samples(path, since_ts=cutoff)
    # Atomic rewrite
    dirname = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dirname, prefix=".history-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            for entry in kept:
                f.write(json.dumps(entry) + "\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return len(kept)


def aggregate(
    points: list[dict],
    key: str,
    now: float,
    window_seconds: float,
    n_buckets: int,
) -> list[float]:
    """Bucket samples into a fixed-width series ending at `now`.

    Each bucket holds the MAX utilization seen in its time slice (utilization
    is what matters for "did we approach the limit"). Empty buckets become 0.0.
    Returns a list of length `n_buckets`, oldest first.
    """
    if n_buckets <= 0 or window_seconds <= 0:
        return []
    bucket_size = window_seconds / n_buckets
    start = now - window_seconds
    out = [0.0] * n_buckets
    for p in points:
        ts = p.get("ts", 0)
        if ts < start or ts > now:
            continue
        idx = int((ts - start) / bucket_size)
        if idx >= n_buckets:
            idx = n_buckets - 1
        elif idx < 0:
            idx = 0
        val = float(p.get(key, 0.0))
        if val > out[idx]:
            out[idx] = val
    return out
