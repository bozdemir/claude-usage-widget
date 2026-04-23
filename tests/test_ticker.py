"""Tests for claude_usage.ticker."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from claude_usage.ticker import (
    MAX_TICKER_ITEMS,
    TICKER_WINDOW_SECONDS,
    TickerItem,
    scan_ticker_items,
)


def _assistant_entry(
    ts: datetime,
    msg_id: str,
    output_tokens: int,
    tool: str | None = None,
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 10,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> dict:
    content: list[dict] = [{"type": "text", "text": "ok"}]
    if tool is not None:
        content.insert(0, {"type": "tool_use", "name": tool, "input": {}})
    return {
        "timestamp": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": {
            "role": "assistant",
            "id": msg_id,
            "model": model,
            "content": content,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            },
        },
    }


def _write(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_no_projects_dir_returns_empty(tmp_path):
    assert scan_ticker_items(str(tmp_path)) == []


def test_emits_one_item_per_assistant_turn(tmp_path):
    now = datetime.now(timezone.utc)
    entries = [
        _assistant_entry(now - timedelta(seconds=30), "msg_a", 100, tool="Bash"),
        _assistant_entry(now - timedelta(seconds=60), "msg_b", 200, tool="Read"),
        _assistant_entry(now - timedelta(seconds=90), "msg_c", 50, tool=None),
    ]
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), entries)
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert len(items) == 3
    # Sorted newest-first.
    assert [it.msg_id for it in items] == ["msg_a", "msg_b", "msg_c"]
    assert items[0].tool == "Bash"
    assert items[1].tool == "Read"
    assert items[2].tool == ""  # text-only turn


def test_deduplicates_by_msg_id(tmp_path):
    """Claude Code replays prior turns as context — same msg.id, different line."""
    now = datetime.now(timezone.utc)
    entry = _assistant_entry(now - timedelta(seconds=30), "msg_dup", 150, tool="Edit")
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [entry, entry, entry])
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert len(items) == 1
    assert items[0].msg_id == "msg_dup"


def test_skips_entries_outside_window(tmp_path):
    now = datetime.now(timezone.utc)
    inside = _assistant_entry(now - timedelta(seconds=60), "msg_in", 100, tool="Bash")
    outside = _assistant_entry(
        now - timedelta(seconds=TICKER_WINDOW_SECONDS + 300), "msg_old", 100, tool="Bash",
    )
    future = _assistant_entry(now + timedelta(seconds=300), "msg_future", 100, tool="Bash")
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [inside, outside, future])
    # Bump mtime so mtime-cutoff doesn't skip the file entirely.
    os.utime(str(tmp_path / "projects" / "p" / "s.jsonl"), (now.timestamp(), now.timestamp()))
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert [it.msg_id for it in items] == ["msg_in"]


def test_skips_entries_without_msg_id(tmp_path):
    """Without an id we can't dedupe replays — drop to avoid double-counting."""
    now = datetime.now(timezone.utc)
    bad = _assistant_entry(now - timedelta(seconds=30), "", 100, tool="Bash")
    good = _assistant_entry(now - timedelta(seconds=60), "msg_ok", 100, tool="Bash")
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [bad, good])
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert [it.msg_id for it in items] == ["msg_ok"]


def test_skips_subagent_sessions(tmp_path):
    now = datetime.now(timezone.utc)
    entry = _assistant_entry(now - timedelta(seconds=30), "msg_sub", 100, tool="Bash")
    _write(str(tmp_path / "projects" / "p" / "subagents" / "child.jsonl"), [entry])
    assert scan_ticker_items(str(tmp_path), now=now.timestamp()) == []


def test_caps_at_max_ticker_items_and_keeps_newest(tmp_path):
    now = datetime.now(timezone.utc)
    # msg_0 is newest (ts offset 0), msg_{N-1} is oldest.
    entries = [
        _assistant_entry(now - timedelta(seconds=i * 5), f"msg_{i}", 50, tool="Bash")
        for i in range(MAX_TICKER_ITEMS + 10)
    ]
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), entries)
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert len(items) == MAX_TICKER_ITEMS
    # Regression guard: if the slice ever reverted to items[-MAX:] (oldest
    # kept) this would fail.
    assert items[0].msg_id == "msg_0"
    assert items[-1].msg_id == f"msg_{MAX_TICKER_ITEMS - 1}"


def test_cost_matches_anthropic_pricing_exactly(tmp_path):
    """Pin the exact dollar amount for a known (model, tokens) so any
    accidental input↔output swap or rate drift surfaces immediately."""
    now = datetime.now(timezone.utc)
    # Sonnet: $3/M input, $15/M output.
    # 500 input + 1000 output → 500*3 + 1000*15 = 16500 / 1M = $0.0165.
    entry = _assistant_entry(
        now - timedelta(seconds=30), "msg_s", 1000,
        model="claude-sonnet-4-6", input_tokens=500,
    )
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [entry])
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert len(items) == 1
    assert abs(items[0].cost_usd - 0.0165) < 1e-9


def test_cost_reflects_model_pricing(tmp_path):
    now = datetime.now(timezone.utc)
    entries = [
        _assistant_entry(
            now - timedelta(seconds=30), "msg_opus", 1000,
            model="claude-opus-4-7", input_tokens=500,
        ),
        _assistant_entry(
            now - timedelta(seconds=60), "msg_haiku", 1000,
            model="claude-haiku-4-5-20251001", input_tokens=500,
        ),
    ]
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), entries)
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    opus = next(it for it in items if it.msg_id == "msg_opus")
    haiku = next(it for it in items if it.msg_id == "msg_haiku")
    assert opus.cost_usd > haiku.cost_usd  # Opus $25/M >> Haiku $5/M on output


def test_future_skew_within_60s_is_kept(tmp_path):
    """Clock drift of a few seconds shouldn't drop otherwise-valid entries."""
    now = datetime.now(timezone.utc)
    near_future = _assistant_entry(
        now + timedelta(seconds=30), "msg_near", 100, tool="Bash",
    )
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [near_future])
    os.utime(str(tmp_path / "projects" / "p" / "s.jsonl"), (now.timestamp(), now.timestamp()))
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert [it.msg_id for it in items] == ["msg_near"]


def test_future_skew_beyond_60s_is_rejected(tmp_path):
    """Entries dated well past the clock-skew tolerance are rejected."""
    now = datetime.now(timezone.utc)
    far_future = _assistant_entry(
        now + timedelta(seconds=120), "msg_far", 100, tool="Bash",
    )
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [far_future])
    os.utime(str(tmp_path / "projects" / "p" / "s.jsonl"), (now.timestamp(), now.timestamp()))
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert items == []


def test_multi_tool_turn_collapses_to_short_label(tmp_path):
    """A turn with Read + Bash + Edit shows 'Read+2' on the tape."""
    now = datetime.now(timezone.utc)
    # Build a custom entry with three tool_use blocks.
    entry = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "message": {
            "role": "assistant",
            "id": "msg_multi",
            "model": "claude-sonnet-4-6",
            "content": [
                {"type": "tool_use", "name": "Read", "input": {}},
                {"type": "tool_use", "name": "Bash", "input": {}},
                {"type": "tool_use", "name": "Edit", "input": {}},
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 50,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }
    _write(str(tmp_path / "projects" / "p" / "s.jsonl"), [entry])
    items = scan_ticker_items(str(tmp_path), now=now.timestamp())
    assert len(items) == 1
    assert items[0].tool == "Read+2"
