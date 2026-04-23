"""Per-turn cost stream feeding the OSD's scrolling ticker tape.

Scans recently-modified ``~/.claude/projects/*/*.jsonl`` for assistant turns
and emits one :class:`TickerItem` per unique message (dedup'd by the stable
``message.id``) with the USD cost, the primary tool invoked (if any), and
the output-token count. The OSD renders these right-to-left like a stock-
ticker ribbon.

Side effects: filesystem reads only — opens every JSONL whose mtime falls
inside the window. No network, no threads, no mutation of global state.
"""

from __future__ import annotations

import glob
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from claude_usage.pricing import calculate_cost

# How far back we surface items on the ticker.  Longer than the live-stream
# window because the ticker shows *finished* actions, not just "is burning".
TICKER_WINDOW_SECONDS = 15 * 60
# Cap items — a busy 15-minute burst can produce dozens; the OSD only renders
# the newest few and we don't want unbounded memory.
MAX_TICKER_ITEMS = 40
# Cheap mtime early filter — slightly wider than the window so a slow flush
# doesn't hide an entry whose mtime was stamped right at the boundary.
FILE_MTIME_CUTOFF_SECONDS = 20 * 60


@dataclass
class TickerItem:
    """A single completed assistant turn for the ticker tape."""

    ts: float            # unix seconds of the turn
    msg_id: str          # Anthropic message id — dedupe key
    cost_usd: float      # total USD for this turn (input + output + cache ops)
    tool: str            # primary tool name, or "" when the turn is text-only
    output_tokens: int   # output-token count, used to size the ticker label
    model: str


def _iter_recent_jsonl(projects_dir: str, mtime_cutoff: float) -> Iterator[str]:
    """Yield main-session JSONL paths whose mtime is >= *mtime_cutoff*.

    Skips ``/subagents/`` trees — those are child sessions whose tokens are
    already billed against the parent turn that spawned them.
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


def _extract_ticker_item(entry: dict) -> TickerItem | None:
    """Build a :class:`TickerItem` from a raw JSONL assistant entry, or None."""
    msg = entry.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return None

    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None

    ts_str = entry.get("timestamp")
    if not isinstance(ts_str, str) or not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None

    try:
        input_t = int(usage.get("input_tokens", 0) or 0)
        output_t = int(usage.get("output_tokens", 0) or 0)
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_creation = int(usage.get("cache_creation_input_tokens", 0) or 0)
    except (TypeError, ValueError):
        return None
    if output_t <= 0:
        return None

    msg_id = str(msg.get("id") or "")
    if not msg_id:
        # Without an id we can't dedupe Claude Code's replays of the same turn
        # as input context, which would double-count. Skip rather than guess.
        return None

    model = str(msg.get("model") or entry.get("requestModel") or "unknown")
    cost = calculate_cost(
        model,
        input_tokens=input_t,
        output_tokens=output_t,
        cache_read=cache_read,
        cache_creation=cache_creation,
    )

    tool_names: list[str] = []
    content = msg.get("content") or []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = str(block.get("name") or "").strip()
                if name:
                    tool_names.append(name)
    # Collapse multi-tool turns to "Read+2" so the ticker chip stays short
    # while still signalling that the turn wasn't single-tool.
    if not tool_names:
        tool = ""
    elif len(tool_names) == 1:
        tool = tool_names[0]
    else:
        tool = f"{tool_names[0]}+{len(tool_names) - 1}"

    return TickerItem(
        ts=ts,
        msg_id=msg_id,
        cost_usd=cost["total"],
        tool=tool,
        output_tokens=output_t,
        model=model,
    )


def scan_ticker_items(claude_dir: str, now: float | None = None) -> list[TickerItem]:
    """Return the most recent ticker items across all active sessions.

    Results are dedup'd by ``message.id`` and sorted newest-first, capped at
    :data:`MAX_TICKER_ITEMS`.
    """
    projects_dir = os.path.join(claude_dir, "projects")
    now_ts = now if now is not None else time.time()
    cutoff = now_ts - TICKER_WINDOW_SECONDS
    cutoff_mtime = now_ts - FILE_MTIME_CUTOFF_SECONDS

    seen: set[str] = set()
    items: list[TickerItem] = []

    for path in _iter_recent_jsonl(projects_dir, cutoff_mtime):
        try:
            f = open(path, encoding="utf-8", errors="replace")
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
                item = _extract_ticker_item(entry)
                if item is None:
                    continue
                if item.ts < cutoff or item.ts > now_ts + 60:
                    continue
                if item.msg_id in seen:
                    continue
                seen.add(item.msg_id)
                items.append(item)

    items.sort(key=lambda x: x.ts, reverse=True)
    return items[:MAX_TICKER_ITEMS]


__all__ = [
    "TickerItem",
    "scan_ticker_items",
    "TICKER_WINDOW_SECONDS",
    "MAX_TICKER_ITEMS",
]
