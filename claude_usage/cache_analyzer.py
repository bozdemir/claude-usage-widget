"""Prompt-cache opportunity analyser.

Scans ``~/.claude/projects/*/*.jsonl`` for repeated user-prompt prefixes and
computes how much money (USD) could be saved by enabling prompt caching on
them.  Pure module — no GUI, no network, safe to run on every refresh.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from claude_usage.pricing import MODEL_PRICING


# Anthropic's minimum cacheable block size (tokens).  Smaller prefixes are
# not eligible for ephemeral prompt caching, so we skip them.
MIN_CACHEABLE_TOKENS = 1024
# Require at least this many repetitions before we surface an opportunity.
# Cache creation costs ~25% more than the base input rate, so a single
# use isn't worth it — we need net savings after the cache-create penalty.
MIN_OCCURRENCES = 3
# How many top opportunities to surface in the UI.
TOP_N = 5


@dataclass
class CacheOpportunity:
    """A single repeated prefix that could benefit from prompt caching."""

    project: str                  # project folder name (raw, caller prettifies)
    prefix_preview: str           # first ~100 chars of the repeated content
    token_count: int              # approximate tokens in the repeated block
    occurrences: int              # how many times the prefix appeared
    model: str                    # model used on the requests
    potential_savings_usd: float  # savings over the sample window


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English code/prose."""
    return max(1, len(text) // 4)


def _prefix_hash(content: str) -> str:
    """Stable hash of the prefix content, truncated for memory."""
    return hashlib.blake2b(content.encode("utf-8", errors="replace"), digest_size=16).hexdigest()


def _extract_user_prefix(entry: dict) -> tuple[str, str] | None:
    """Return ``(prefix_text, model)`` for a user message, or None.

    We intentionally consider only the *first* content block of each user
    turn — that's typically where the system-prompt-like context lives.
    Subsequent blocks usually diverge between turns, which is exactly what
    makes them NOT cache candidates.
    """
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return None
    if msg.get("role") != "user":
        return None

    content = msg.get("content")
    text: str | None = None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("type") == "text":
            text = first.get("text")
        elif isinstance(first, str):
            text = first
    if not text or len(text) < 200:
        return None

    model = str(msg.get("model") or entry.get("requestModel") or "unknown")
    return text, model


def analyze_cache_opportunities(
    claude_dir: str,
    days: int = 7,
    now: float | None = None,
) -> list[CacheOpportunity]:
    """Return the top cache-saving opportunities across the recent window.

    Only scans files modified within the last *days* days, and only considers
    entries whose timestamp falls inside that window — so re-running the
    analyser is cheap even on a large ``~/.claude/projects/`` tree.
    """
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return []

    now_ts = now if now is not None else datetime.now().timestamp()
    cutoff = now_ts - days * 86400

    # prefix_hash -> dict(project, text, tokens, occurrences, model)
    buckets: dict[str, dict[str, Any]] = {}

    for jsonl_path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        if os.sep + "subagents" + os.sep in jsonl_path:
            continue
        try:
            if os.path.getmtime(jsonl_path) < cutoff:
                continue
        except OSError:
            continue

        project = os.path.basename(os.path.dirname(jsonl_path))
        try:
            f = open(jsonl_path, encoding="utf-8", errors="replace")
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

                # Window filter by ISO timestamp when present. Convert to a
                # unix float so the comparison is timezone-safe — earlier
                # versions compared a UTC dt against a local-tz dt and
                # shifted the cutoff by the host's UTC offset.
                ts_str = entry.get("timestamp", "")
                if ts_str:
                    try:
                        ts_unix = datetime.fromisoformat(
                            ts_str.replace("Z", "+00:00"),
                        ).timestamp()
                        if ts_unix < cutoff:
                            continue
                    except ValueError:
                        pass  # fall through — keep the entry

                extracted = _extract_user_prefix(entry)
                if extracted is None:
                    continue
                text, model = extracted
                tokens = _estimate_tokens(text)
                if tokens < MIN_CACHEABLE_TOKENS:
                    continue

                h = _prefix_hash(text)
                # Store only a short preview, not the full prefix — a 1 MB
                # pasted log shouldn't balloon the bucket dict.
                bucket = buckets.setdefault(h, {
                    "project": project,
                    "preview": text[:100].replace("\n", " ").strip(),
                    "tokens": tokens,
                    "occurrences": 0,
                    "model": model,
                })
                bucket["occurrences"] += 1

    opportunities: list[CacheOpportunity] = []
    for bucket in buckets.values():
        if bucket["occurrences"] < MIN_OCCURRENCES:
            continue
        savings = _compute_savings(
            tokens=bucket["tokens"],
            occurrences=bucket["occurrences"],
            model=bucket["model"],
        )
        if savings <= 0.01:
            continue
        opportunities.append(CacheOpportunity(
            project=bucket["project"],
            prefix_preview=bucket["preview"],
            token_count=bucket["tokens"],
            occurrences=bucket["occurrences"],
            model=bucket["model"],
            potential_savings_usd=savings,
        ))

    opportunities.sort(key=lambda o: o.potential_savings_usd, reverse=True)
    return opportunities[:TOP_N]


def _compute_savings(tokens: int, occurrences: int, model: str) -> float:
    """Dollar savings if a repeated prefix were cached vs re-sent every time.

    Without caching: tokens * occurrences * input_rate
    With caching   : tokens * cache_creation_rate                  (1 write)
                   + tokens * (occurrences - 1) * cache_read_rate  (N-1 reads)

    The returned figure is the difference (always non-negative for
    occurrences >= 2 since cache_read is < input).
    """
    rates = MODEL_PRICING.get(model) or MODEL_PRICING["claude-sonnet-4-6"]
    per_m = tokens / 1_000_000.0
    uncached = per_m * occurrences * rates["input"]
    cached = (
        per_m * rates["cache_creation"]
        + per_m * max(occurrences - 1, 0) * rates["cache_read"]
    )
    return max(0.0, uncached - cached)
