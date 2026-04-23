"""Claude-powered weekly activity report.

Generates a short natural-language summary of the user's past week of Claude
Code usage by sending an aggregated stats dict to Haiku 4.5 and asking for
a 3-4 sentence review.  Results are cached on disk for 1 hour so we don't
burn tokens on every widget refresh.

Pure(-ish) module — the only side effects are the one-shot HTTP call to the
Anthropic API and the on-disk cache file.  No GUI, no threads.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CACHE_TTL_SECONDS = 3600
CACHE_FILENAME = "weekly-report.json"
CACHE_SUBDIR = "widget-cache"
REPORT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 320
REQUEST_TIMEOUT = 20


@dataclass
class WeeklyReport:
    """Cached Claude-authored summary of last week's usage."""

    text: str
    generated_at: float  # unix timestamp
    model: str = REPORT_MODEL

    def is_fresh(self, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        delta = ts - self.generated_at
        # Reject future-dated reports (clock skew, shared-disk copies from a
        # faster machine). Without this guard a negative delta would pass
        # the `< TTL` check and pin a "future" report indefinitely.
        return 0 <= delta < CACHE_TTL_SECONDS


def _cache_path(claude_dir: str) -> str:
    return os.path.join(claude_dir, CACHE_SUBDIR, CACHE_FILENAME)


def load_cached_report(claude_dir: str, now: float | None = None) -> WeeklyReport | None:
    """Return the on-disk report if it exists and is still within the TTL."""
    path = _cache_path(claude_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    try:
        report = WeeklyReport(
            text=str(data.get("text", "")),
            generated_at=float(data.get("generated_at", 0)),
            model=str(data.get("model", REPORT_MODEL)),
        )
    except (TypeError, ValueError):
        return None
    if not report.text or not report.is_fresh(now):
        return None
    return report


def save_cached_report(claude_dir: str, report: WeeklyReport) -> None:
    """Persist *report* to the on-disk cache (best-effort — failures swallowed).

    Writes atomically via ``tmp + os.replace`` so a concurrent reader (or a
    crash mid-write) never sees a truncated JSON file — matches the pattern
    used by ``config.save_config``.
    """
    path = _cache_path(claude_dir)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "text": report.text,
                "generated_at": report.generated_at,
                "model": report.model,
            }, f)
        os.replace(tmp, path)
    except OSError:
        pass


def build_prompt(summary: dict[str, Any]) -> str:
    """Compose the user-facing prompt from an aggregated-stats dict.

    The prompt is deliberately short: Haiku is fast and we only need a few
    sentences back.  We ask for plain-text output — no markdown — so we can
    render it straight into the Qt popup.
    """
    week_cost = float(summary.get("week_cost", 0.0) or 0.0)
    week_tokens = int(summary.get("week_tokens", 0) or 0)
    week_messages = int(summary.get("week_messages", 0) or 0)
    subscription = str(summary.get("subscription_type", "") or "")
    top_projects = summary.get("top_projects") or []
    by_model = summary.get("by_model") or {}

    # Truncate / prettify top-3 projects so the prompt fits in ~150 tokens.
    top_lines: list[str] = []
    for name, tokens in list(top_projects)[:3]:
        try:
            tok_k = int(tokens) / 1000.0
        except (TypeError, ValueError):
            continue
        top_lines.append(f"  - {name}: {tok_k:.1f}k output tokens")

    model_lines: list[str] = []
    for model, counts in by_model.items():
        total = sum(int(counts.get(k, 0) or 0) for k in ("input", "output", "cache_read", "cache_creation"))
        if total:
            model_lines.append(f"  - {model}: {total/1000:.1f}k total tokens")

    plan_line = f"The user pays a flat {subscription.capitalize()} plan fee." if subscription else ""

    return (
        "You are summarising a single developer's past 7 days of Claude Code usage. "
        "Write 3-4 plain-text sentences (no markdown, no headings, no bullet lists). "
        "Be concrete, friendly, and slightly enthusiastic. Mention the top project(s) by name, "
        "the rough total output volume, and one observation about the model mix or cost. "
        "Do not invent features or numbers that aren't in the data.\n\n"
        f"Week messages: {week_messages}\n"
        f"Week output tokens: {week_tokens}\n"
        f"Week API-equivalent value: ${week_cost:.2f}\n"
        f"{plan_line}\n"
        "Top projects:\n"
        + ("\n".join(top_lines) if top_lines else "  (none)")
        + "\nModel usage:\n"
        + ("\n".join(model_lines) if model_lines else "  (none)")
    )


def _call_haiku(token: str, prompt: str) -> str | None:
    """POST a single-shot prompt to the Anthropic API and return the text reply."""
    body = json.dumps({
        "model": REPORT_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    # OAuth tokens use the same `x-api-key` slot as API keys but require the
    # `oauth-2025-04-20` beta header to be accepted — matches the pattern
    # used in collector.fetch_rate_limits for rate-limit polling.
    req = Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "oauth-2025-04-20",
            "content-type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None

    content = payload.get("content") or []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                return text
    return None


def generate_report(
    claude_dir: str,
    summary: dict[str, Any],
    token_loader,
    now: float | None = None,
) -> WeeklyReport | None:
    """Return a fresh or cached WeeklyReport, or None if generation fails.

    ``token_loader`` is a zero-arg callable returning the OAuth access token
    (or None).  We take it as a callback rather than importing the collector
    directly to keep this module independently testable.
    """
    cached = load_cached_report(claude_dir, now=now)
    if cached is not None:
        return cached

    token = None
    try:
        token = token_loader()
    except Exception:
        token = None
    if not token:
        return None

    prompt = build_prompt(summary)
    text = _call_haiku(token, prompt)
    if not text:
        return None

    report = WeeklyReport(text=text, generated_at=now if now is not None else time.time())
    save_cached_report(claude_dir, report)
    return report


__all__ = [
    "WeeklyReport",
    "build_prompt",
    "generate_report",
    "load_cached_report",
    "save_cached_report",
    "CACHE_TTL_SECONDS",
    "REPORT_MODEL",
]
