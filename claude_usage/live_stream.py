"""Live-activity detector for the OSD.

Scans ``~/.claude/projects/*/*.jsonl`` for assistant turns written in the
last few minutes, sums up their output tokens, and derives an instantaneous
tokens-per-minute rate.  Used by the overlay to show a ``● LIVE ~1240
tok/min`` indicator while a session is active.

Pure module — no GUI, no threads.  The caller decides how often to poll.
"""

from __future__ import annotations

import glob
import json
import os
import time
from dataclasses import dataclass
from typing import Iterator

# How far back to consider assistant turns when computing the live rate.
LIVE_WINDOW_SECONDS = 5 * 60
# A session is considered "active" if any assistant turn landed within this
# much time.  Shorter than LIVE_WINDOW_SECONDS so rate stays smooth while
# the "live" badge only shows during true activity.
ACTIVE_CUTOFF_SECONDS = 90
# Skip files that haven't been touched in this long — cheap early filter.
FILE_MTIME_CUTOFF_SECONDS = 10 * 60


@dataclass
class LiveActivity:
    """Instantaneous usage snapshot for the OSD live indicator."""

    is_live: bool = False
    tokens_per_minute: float = 0.0
    output_tokens_last_window: int = 0
    last_activity_ts: float = 0.0  # unix seconds; 0.0 means "no recent activity"


def _iter_recent_jsonl(projects_dir: str, mtime_cutoff: float) -> Iterator[str]:
    """Yield conversation JSONL paths whose mtime is >= *mtime_cutoff*.

    Skips ``/subagents/`` paths to avoid double-counting child sessions that
    were spawned from the parent.
    """
    if not os.path.isdir(projects_dir):
        return
    for path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        if os.sep + "subagents" + os.sep in path:
            continue
        try:
            if os.path.getmtime(path) < mtime_cutoff:
                continue
        except OSError:
            continue
        yield path


def _extract_assistant_sample(entry: dict) -> tuple[float, int] | None:
    """Return (timestamp, output_tokens) for an assistant turn, or None.

    We look only at assistant messages with a ``usage`` block — those are the
    ones that actually cost tokens.  Parsing is defensive: any malformed
    entry returns None and the caller skips it.
    """
    msg = entry.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        out_tokens = int(usage.get("output_tokens", 0) or 0)
    except (TypeError, ValueError):
        return None
    if out_tokens <= 0:
        return None

    ts_str = entry.get("timestamp")
    if not isinstance(ts_str, str) or not ts_str:
        return None
    # ISO-8601 with Z suffix → python-friendly +00:00.
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    return ts, out_tokens


def detect_live_activity(claude_dir: str, now: float | None = None) -> LiveActivity:
    """Scan recent conversation files and report the current tokens/min rate.

    *claude_dir* is the user's ``~/.claude`` directory.  *now* is an optional
    unix timestamp used by tests — production callers should pass None.
    """
    projects_dir = os.path.join(claude_dir, "projects")
    now_ts = now if now is not None else time.time()
    cutoff_window = now_ts - LIVE_WINDOW_SECONDS
    cutoff_active = now_ts - ACTIVE_CUTOFF_SECONDS
    cutoff_mtime = now_ts - FILE_MTIME_CUTOFF_SECONDS

    total_tokens = 0
    latest_ts = 0.0

    for path in _iter_recent_jsonl(projects_dir, cutoff_mtime):
        try:
            f = open(path)
        except OSError:
            continue
        with f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sample = _extract_assistant_sample(entry)
                if sample is None:
                    continue
                ts, out_tokens = sample
                if ts < cutoff_window or ts > now_ts + 60:
                    # Future-dated entries (clock skew) are ignored too.
                    continue
                total_tokens += out_tokens
                if ts > latest_ts:
                    latest_ts = ts

    tokens_per_minute = total_tokens / (LIVE_WINDOW_SECONDS / 60.0)
    is_live = latest_ts > 0 and latest_ts >= cutoff_active

    return LiveActivity(
        is_live=is_live,
        tokens_per_minute=tokens_per_minute,
        output_tokens_last_window=total_tokens,
        last_activity_ts=latest_ts,
    )


__all__ = [
    "LiveActivity",
    "detect_live_activity",
    "LIVE_WINDOW_SECONDS",
    "ACTIVE_CUTOFF_SECONDS",
]
