"""Count subagent (Task tool) processes that are currently active.

Claude Code writes each subagent session to
``~/.claude/projects/<proj>/<session-uuid>/subagents/agent-*.jsonl``. A file
whose mtime is within :data:`SUBAGENT_ACTIVE_SECONDS` is assumed to belong
to a still-running subagent — the JSONL is line-flushed as the agent
writes, so a recent mtime is a reliable "this process is working" signal.

Pure module — filesystem reads only, no network, no threads.
"""

from __future__ import annotations

import glob
import os
import time

# How recent a subagent JSONL's mtime must be to count as "active". Claude
# Code flushes lines as the agent writes tool-use + text blocks; when the
# subagent finishes, the file goes quiet. 60 s is a balance between
# false-positives (subagent just finished but file not yet idle) and
# false-negatives (subagent busy thinking but not writing yet).
SUBAGENT_ACTIVE_SECONDS = 60


def count_active_subagents(claude_dir: str, now: float | None = None) -> int:
    """Return the number of subagent JSONLs touched in the last ACTIVE window.

    Safe to call on every refresh — the glob is scoped and no file contents
    are opened; we only stat mtimes.
    """
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return 0
    now_ts = now if now is not None else time.time()
    cutoff = now_ts - SUBAGENT_ACTIVE_SECONDS

    count = 0
    pattern = os.path.join(projects_dir, "*", "*", "subagents", "agent-*.jsonl")
    for path in glob.glob(pattern):
        try:
            if os.path.getmtime(path) >= cutoff:
                count += 1
        except OSError:
            continue
    return count


__all__ = [
    "SUBAGENT_ACTIVE_SECONDS",
    "count_active_subagents",
]
