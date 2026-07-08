"""Codex (OpenAI `codex` CLI) usage provider.

Reads local session rollout JSONL under ``<codex_dir>/sessions/YYYY/MM/DD/
rollout-*.jsonl``. Every ``token_count`` event carries a ``rate_limits`` block
(account-global) plus per-turn ``last_token_usage`` deltas — enough for bars
and token totals with no network call.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from claude_usage.collector import UsageStats
from claude_usage.providers.base import window_label


def _rollout_paths(codex_dir: str) -> list[str]:
    pat = os.path.join(codex_dir, "sessions", "*", "*", "*", "rollout-*.jsonl")
    return glob.glob(pat)


def _iter_records(path: str):
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _latest_rate_limits(codex_dir: str) -> dict | None:
    """Return the ``rate_limits`` block from the newest ``token_count`` event
    across all rollouts (account-global, so newest timestamp = current)."""
    latest_ts = ""
    latest_rl: dict | None = None
    for path in _rollout_paths(codex_dir):
        for rec in _iter_records(path):
            payload = rec.get("payload", {})
            if payload.get("type") != "token_count":
                continue
            rl = payload.get("rate_limits")
            if not rl:
                continue
            ts = rec.get("timestamp", "")
            if ts >= latest_ts:
                latest_ts = ts
                latest_rl = rl
    return latest_rl


def _apply_rate_limits(stats: UsageStats, rl: dict | None) -> None:
    """Map Codex primary/secondary windows onto session_*/weekly_* by length."""
    if not rl:
        stats.rate_limit_error = "no Codex rate-limit data on disk"
        return
    windows = [w for w in (rl.get("primary"), rl.get("secondary"))
               if isinstance(w, dict) and w.get("window_minutes")]
    windows.sort(key=lambda w: w["window_minutes"])  # shortest first
    # shortest → session bar
    if windows:
        short = windows[0]
        stats.session_utilization = float(short.get("used_percent", 0.0)) / 100.0
        stats.session_reset = int(short.get("resets_at", 0) or 0)
        stats.session_label = window_label(int(short["window_minutes"]))
    # longest → weekly bar (when a second, longer window exists)
    if len(windows) >= 2:
        long = windows[-1]
        stats.weekly_utilization = float(long.get("used_percent", 0.0)) / 100.0
        stats.weekly_reset = int(long.get("resets_at", 0) or 0)
        stats.weekly_label = window_label(int(long["window_minutes"]))
    elif windows and int(windows[0]["window_minutes"]) >= 1440:
        # Only one window and it's long (≥1 day) → treat it as the weekly bar,
        # not the session bar, so a lone monthly cap shows in the right slot.
        long = windows[0]
        stats.weekly_utilization = float(long.get("used_percent", 0.0)) / 100.0
        stats.weekly_reset = int(long.get("resets_at", 0) or 0)
        stats.weekly_label = window_label(int(long["window_minutes"]))
        stats.session_utilization = 0.0
        stats.session_reset = 0
        stats.session_label = ""
    stats.subscription_type = str(rl.get("plan_type", "") or "")
