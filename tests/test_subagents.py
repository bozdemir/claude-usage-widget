"""Tests for claude_usage.subagents."""

from __future__ import annotations

import os

from claude_usage.subagents import SUBAGENT_ACTIVE_SECONDS, count_active_subagents


def _touch(path, mtime: float) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("")
    os.utime(path, (mtime, mtime))


def test_no_projects_dir_returns_zero(tmp_path):
    assert count_active_subagents(str(tmp_path)) == 0


def test_counts_recent_subagent_files(tmp_path, monkeypatch):
    now = 1_776_000_000.0
    # Two fresh subagents + one stale one across two projects.
    _touch(str(tmp_path / "projects" / "proj-a" / "uuid1" / "subagents" / "agent-1.jsonl"), now - 10)
    _touch(str(tmp_path / "projects" / "proj-a" / "uuid1" / "subagents" / "agent-2.jsonl"), now - 20)
    _touch(str(tmp_path / "projects" / "proj-b" / "uuid2" / "subagents" / "agent-3.jsonl"), now - 5)
    _touch(
        str(tmp_path / "projects" / "proj-b" / "uuid2" / "subagents" / "agent-old.jsonl"),
        now - SUBAGENT_ACTIVE_SECONDS - 120,
    )
    assert count_active_subagents(str(tmp_path), now=now) == 3


def test_no_subagents_returns_zero(tmp_path):
    # A project with only a main session file, no subagents/ subdir.
    now = 1_776_000_000.0
    _touch(str(tmp_path / "projects" / "proj-a" / "main.jsonl"), now - 5)
    assert count_active_subagents(str(tmp_path), now=now) == 0


def test_boundary_at_active_cutoff(tmp_path):
    """A file mtime'd exactly on the cutoff boundary counts as active."""
    now = 1_776_000_000.0
    _touch(
        str(tmp_path / "projects" / "p" / "u" / "subagents" / "agent-boundary.jsonl"),
        now - SUBAGENT_ACTIVE_SECONDS,
    )
    assert count_active_subagents(str(tmp_path), now=now) == 1


def test_files_just_past_cutoff_are_excluded(tmp_path):
    now = 1_776_000_000.0
    _touch(
        str(tmp_path / "projects" / "p" / "u" / "subagents" / "agent-stale.jsonl"),
        now - SUBAGENT_ACTIVE_SECONDS - 1,
    )
    assert count_active_subagents(str(tmp_path), now=now) == 0


def test_ignores_non_agent_files_in_subagents_dir(tmp_path):
    """Glob pattern targets `agent-*.jsonl` — other noise is skipped."""
    now = 1_776_000_000.0
    subagents = tmp_path / "projects" / "p" / "u" / "subagents"
    _touch(str(subagents / "agent-real.jsonl"), now - 5)
    _touch(str(subagents / "README.md"), now - 5)
    _touch(str(subagents / "index.json"), now - 5)
    assert count_active_subagents(str(tmp_path), now=now) == 1
