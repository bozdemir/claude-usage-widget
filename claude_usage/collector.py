"""Data collection from ~/.claude/ sources and Anthropic API."""

from __future__ import annotations

import glob
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from claude_usage import forecast, pricing
from claude_usage.analytics import AnomalyReport, detect_anomaly, generate_tips
from claude_usage.cache_analyzer import CacheOpportunity, analyze_cache_opportunities
from claude_usage.history import aggregate, append_sample, load_samples, prune
from claude_usage.live_stream import LiveActivity, detect_live_activity
from claude_usage.subagents import count_active_subagents
from claude_usage.ticker import TickerItem, scan_ticker_items
from claude_usage.trends import daily_heatmap, hourly_histogram, monthly_summary

HISTORY_FILENAME = "usage-history.jsonl"
HISTORY_KEEP_DAYS = 90  # keep 90 days for trend/anomaly analysis
SESSION_WINDOW_SECONDS = 5 * 3600
SESSION_BUCKETS = 30
WEEKLY_WINDOW_SECONDS = 7 * 86400
ANALYTICS_WINDOW_SECONDS = 90 * 86400
WEEKLY_BUCKETS = 28


@dataclass
class UsageStats:
    """Aggregated usage statistics from local data and API rate limits."""

    today_messages: int = 0
    today_sessions: int = 0
    week_messages: int = 0
    week_sessions: int = 0
    today_tokens: int = 0
    week_tokens: int = 0
    active_sessions: list[dict[str, Any]] = field(default_factory=list)
    today_model_tokens: dict[str, int] = field(default_factory=dict)
    today_hourly: dict[int, int] = field(default_factory=dict)
    # Real rate limit data from API
    session_utilization: float = 0.0  # 0.0 - 1.0
    session_reset: int = 0  # unix timestamp (seconds)
    weekly_utilization: float = 0.0
    weekly_reset: int = 0
    overage_status: str = ""  # "rejected" or "allowed"
    fallback_status: str = ""  # "available" or ""
    rate_limit_error: str = ""  # error message if API call fails
    session_history: list = field(default_factory=list)  # bucketed sparkline (oldest first)
    weekly_history: list = field(default_factory=list)
    # Subscription type from OAuth credentials ("max", "pro", "free", or "" if unknown).
    # Used to relabel cost fields: subscribers pay a flat fee, so the "cost" is really
    # the pay-as-you-go API-equivalent value of their usage, not what they're billed.
    subscription_type: str = ""
    # Cost estimates (USD) — for subscribers these represent pay-as-you-go equivalent
    today_cost: float = 0.0
    week_cost: float = 0.0
    cache_savings: float = 0.0  # $ saved this week via prompt caching
    # {model: {"input": N, "output": N, "cache_read": N, "cache_creation": N}}
    today_by_model_detailed: dict = field(default_factory=dict)
    # {project_name: output_tokens} -- trimmed to the top N projects by tokens
    today_by_project: dict = field(default_factory=dict)
    # Forecast dicts produced by forecast.forecast_time_to_limit
    session_forecast: dict = field(default_factory=dict)
    weekly_forecast: dict = field(default_factory=dict)
    # Anomaly detection over the 90-day baseline
    anomaly: AnomalyReport = field(default_factory=AnomalyReport)
    # Cost optimisation tips (0-3 short strings)
    tips: list[str] = field(default_factory=list)
    # Long-range trends
    daily_heatmap: list = field(default_factory=list)       # 90-day peaks (newest last)
    yearly_heatmap: list = field(default_factory=list)      # 364-day peaks (52 wk × 7 d)
    monthly_summary: list = field(default_factory=list)     # last 6 months
    hourly_histogram: list = field(default_factory=list)    # 24 buckets
    # Prompt-cache savings opportunities (top N repeated prefixes)
    cache_opportunities: list[CacheOpportunity] = field(default_factory=list)
    # Live-activity snapshot for the OSD indicator
    live_activity: LiveActivity = field(default_factory=LiveActivity)
    # Claude-authored weekly summary text (empty when unavailable / not yet cached)
    weekly_report_text: str = ""
    # Rolling per-turn cost feed for the OSD's scrolling ticker tape
    ticker_items: list[TickerItem] = field(default_factory=list)
    # Count of subagent JSONLs touched in the last minute — surfaced as the
    # "⚙ N" rozet next to the CLAUDE title when > 0.
    active_subagent_count: int = 0


def parse_history(path: str) -> UsageStats:
    """Parse ~/.claude/history.jsonl for message counts and session tracking.

    Counts messages and unique sessions for today and the rolling 7-day window.
    Also builds an hourly message histogram for today.
    """
    stats = UsageStats()
    if not os.path.isfile(path):
        return stats

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Rolling 7-day window: include today plus the 6 previous calendar days
    week_start = today_start - timedelta(days=6)

    today_session_ids: set[str] = set()
    week_session_ids: set[str] = set()

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_ms = entry.get("timestamp", 0)
            if ts_ms <= 0:
                continue
            # history.jsonl stores timestamps in milliseconds
            dt = datetime.fromtimestamp(ts_ms / 1000)
            sid = entry.get("sessionId", "")

            if dt >= today_start:
                stats.today_messages += 1
                today_session_ids.add(sid)
                stats.today_hourly[dt.hour] = stats.today_hourly.get(dt.hour, 0) + 1

            if dt >= week_start:
                stats.week_messages += 1
                week_session_ids.add(sid)

    stats.today_sessions = len(today_session_ids)
    stats.week_sessions = len(week_session_ids)
    return stats


def _collect_tokens_single_pass(
    claude_dir: str,
    today_prefix: str,
    week_prefixes: list[str],
) -> dict[str, Any]:
    """Scan conversation JSONL files once, collecting tokens for both today and week.

    A single filesystem pass avoids reading every file twice when the caller needs
    both today and week totals.  ``today_prefix`` is a YYYY-MM-DD string;
    ``week_prefixes`` is the full list of 7 such strings (including today).
    """
    result: dict[str, Any] = {
        "today_output": 0,
        "week_output": 0,
        "today_by_model": {},
        # Full per-model breakdowns (input/output/cache_read/cache_creation)
        "today_by_model_detailed": {},
        "week_by_model_detailed": {},
        # Today's output tokens grouped by the immediate parent directory name
        "today_by_project": {},
    }
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return result

    # Resolve symlinks so glob patterns match the real on-disk layout
    projects_dir = os.path.realpath(projects_dir)

    # mtime cutoff: we only care about files touched within the week window
    # we're aggregating, plus a one-day slack for clock skew / slow flushes.
    mtime_cutoff = datetime.now().timestamp() - 8 * 86400

    for jsonl_path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        parts = jsonl_path.split(os.sep)
        # Subagent conversations share tokens with their parent; skip to avoid double-counting
        if "subagents" in parts:
            continue
        try:
            if os.path.getmtime(jsonl_path) < mtime_cutoff:
                continue
        except OSError:
            continue
        _parse_tokens_file(jsonl_path, today_prefix, week_prefixes, result)

    return result


def _parse_tokens_file(
    path: str,
    today_prefix: str,
    week_prefixes: list[str],
    result: dict[str, Any],
) -> None:
    """Extract token usage from a single conversation JSONL file.

    Mutates *result* in-place.  Only processes ``assistant`` entries because
    those are the ones that carry the ``usage`` block with ``output_tokens``.
    """
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return

    # Project name = name of the immediate parent directory under projects/
    # (e.g. "-home-user-my-project"). Used for per-project token breakdowns.
    project_name = os.path.basename(os.path.dirname(path))

    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            timestamp = entry.get("timestamp", "")
            # Check today first; if true, week is automatically true -- avoids iterating week_prefixes
            is_today = timestamp.startswith(today_prefix)
            is_week = is_today or any(timestamp.startswith(p) for p in week_prefixes)
            if not is_week:
                continue

            msg = entry.get("message", {})
            if not isinstance(msg, dict):
                continue

            usage = msg.get("usage", {})
            output_tokens = usage.get("output_tokens", 0) or 0
            input_tokens = usage.get("input_tokens", 0) or 0
            cache_read = usage.get("cache_read_input_tokens", 0) or 0
            cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
            model = msg.get("model", "unknown")

            result["week_output"] += output_tokens

            week_bucket = result["week_by_model_detailed"].setdefault(
                model, {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0},
            )
            week_bucket["input"] += input_tokens
            week_bucket["output"] += output_tokens
            week_bucket["cache_read"] += cache_read
            week_bucket["cache_creation"] += cache_creation

            if is_today:
                result["today_output"] += output_tokens
                result["today_by_model"][model] = result["today_by_model"].get(model, 0) + output_tokens

                today_bucket = result["today_by_model_detailed"].setdefault(
                    model, {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0},
                )
                today_bucket["input"] += input_tokens
                today_bucket["output"] += output_tokens
                today_bucket["cache_read"] += cache_read
                today_bucket["cache_creation"] += cache_creation

                result["today_by_project"][project_name] = (
                    result["today_by_project"].get(project_name, 0) + output_tokens
                )


# Preserved for test compatibility -- superseded by _collect_tokens_single_pass
def collect_tokens_from_conversations(
    claude_dir: str,
    date_prefixes: list[str],
) -> dict[str, Any]:
    """Scan conversation JSONL files for token usage on the given date prefixes.

    Legacy entry point kept so existing tests don't break.  New callers should
    use ``_collect_tokens_single_pass`` which covers today and week in one pass.
    Returns totals split by input/output and broken down per model.
    """
    result: dict[str, Any] = {"total_output": 0, "total_input": 0, "by_model": {}}
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return result

    projects_dir = os.path.realpath(projects_dir)

    for jsonl_path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        parts = jsonl_path.split(os.sep)
        if "subagents" in parts:
            continue
        _parse_conversation_tokens(jsonl_path, date_prefixes, result)

    return result


def _parse_conversation_tokens(
    path: str,
    date_prefixes: list[str],
    result: dict[str, Any],
) -> None:
    """Extract token usage from a single conversation JSONL file.

    Mutates *result* in-place, accumulating input/output totals and per-model
    breakdowns.
    """
    try:
        f = open(path)
    except OSError:
        return

    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            timestamp = entry.get("timestamp", "")
            if not any(timestamp.startswith(prefix) for prefix in date_prefixes):
                continue

            msg = entry.get("message", {})
            if not isinstance(msg, dict):
                continue

            usage = msg.get("usage", {})
            output_tokens = usage.get("output_tokens", 0)
            input_tokens = usage.get("input_tokens", 0)
            model = msg.get("model", "unknown")

            result["total_output"] += output_tokens
            result["total_input"] += input_tokens

            if model not in result["by_model"]:
                result["by_model"][model] = {"input": 0, "output": 0}
            result["by_model"][model]["input"] += input_tokens
            result["by_model"][model]["output"] += output_tokens


def get_active_sessions(claude_dir: str) -> list[dict[str, Any]]:
    """Return list of active Claude sessions whose recorded PID is still alive.

    Uses ``os.kill(pid, 0)`` as a zero-signal probe: it raises
    ``ProcessLookupError`` when the process is gone and ``PermissionError``
    when it exists but is owned by another user.  In both surviving cases the
    session is treated as "running" from the user's perspective.
    """
    sessions_dir = os.path.join(claude_dir, "sessions")
    if not os.path.isdir(sessions_dir):
        return []

    active: list[dict[str, Any]] = []
    for fname in os.listdir(sessions_dir):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(sessions_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                sess = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        pid = sess.get("pid", 0)
        if pid <= 0:
            continue
        try:
            os.kill(pid, 0)  # signal 0: probe existence without killing
        except PermissionError:
            # Process exists but is owned by a different UID -- still alive.
            active.append(sess)
        except ProcessLookupError:
            pass  # PID no longer exists; session is stale.
        else:
            active.append(sess)
    return active


def _load_subscription_type(claude_dir: str) -> str:
    """Return subscription type ("max", "pro", "free", ...) from credentials, or ""."""
    creds_path = os.path.join(claude_dir, ".credentials.json")
    if not os.path.isfile(creds_path):
        return ""
    try:
        with open(creds_path) as f:
            creds = json.load(f)
        return str(creds.get("claudeAiOauth", {}).get("subscriptionType", ""))
    except (json.JSONDecodeError, OSError):
        return ""


def _load_credentials(claude_dir: str) -> str | None:
    """Load the OAuth access token from the credentials file or macOS Keychain.

    The file-based path (``~/.claude/.credentials.json``) works on both Linux
    and macOS.  The Keychain fallback handles macOS installs where Claude Code
    stores credentials in the system keychain rather than (or in addition to)
    the flat file.

    Returns the raw access-token string, or ``None`` if no valid token is found.
    """
    # 1. Try the credentials file (Linux + macOS)
    creds_path = os.path.join(claude_dir, ".credentials.json")
    if os.path.isfile(creds_path):
        try:
            with open(creds_path) as f:
                creds = json.load(f)
            return creds["claudeAiOauth"]["accessToken"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # File exists but is unreadable or lacks the token key; try Keychain

    # 2. Keychain fallback -- macOS only; /usr/bin/security is the canonical CLI
    if sys.platform == "darwin":
        try:
            import subprocess

            result = subprocess.run(
                [
                    "/usr/bin/security",
                    "find-generic-password",
                    "-s",
                    "Claude Code-credentials",
                    "-w",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                creds = json.loads(result.stdout.strip())
                return creds["claudeAiOauth"]["accessToken"]
        except Exception:
            pass

    return None


def fetch_rate_limits(claude_dir: str) -> dict[str, Any]:
    """Fetch rate-limit data from the Anthropic API using OAuth credentials.

    Makes a minimal API call (``max_tokens=1`` to the cheapest model) purely to
    receive response headers -- the actual reply text is discarded.  ``urllib``
    is used instead of ``subprocess``/``curl`` so the bearer token never appears
    in the process argument list (visible via ``/proc/cmdline`` on Linux).

    On HTTP 429 the rate-limit headers are still present on the error response,
    so we parse them instead of treating the 429 as a fatal failure.
    """
    token = _load_credentials(claude_dir)
    if not token:
        return {"error": "No credentials found -- run 'claude' to log in"}

    # Cheapest model, smallest completion -- we only care about the response headers
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "h"}],
    }).encode()

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
        with urlopen(req, timeout=15) as resp:
            headers = {k.lower(): v for k, v in resp.getheaders()}
    except HTTPError as e:
        if e.code == 401:
            return {"error": "Credentials expired -- re-authenticate with 'claude'"}
        if e.code == 429:
            # Rate-limit headers are still populated on 429 responses
            headers = {k.lower(): v for k, v in e.headers.items()}
            prefix = "anthropic-ratelimit-unified-"
            if any(k.startswith(prefix) for k in headers):
                return _parse_rate_limit_headers(headers)
            return {"error": "Rate limited -- try again later"}
        return {"error": f"API error {e.code}"}
    except (URLError, OSError, TimeoutError):
        return {"error": "API request failed -- check network"}

    return _parse_rate_limit_headers(headers)


def _parse_rate_limit_headers(headers: dict[str, str]) -> dict[str, Any]:
    """Parse Anthropic unified rate-limit headers into typed values.

    All header values arrive as strings and may be missing or malformed, so
    every field goes through a safe converter with a sensible default.
    """
    prefix = "anthropic-ratelimit-unified-"
    if not any(k.startswith(prefix) for k in headers):
        return {"error": "No rate limit headers in response"}

    def _safe_float(suffix: str, default: float = 0.0) -> float:
        """Return a clamped [0.0, 1.0] float, falling back to *default* on bad input."""
        try:
            val = float(headers.get(prefix + suffix, default))
            # NaN/Inf cannot be displayed or compared meaningfully
            if math.isnan(val) or math.isinf(val):
                return default
            return max(0.0, min(val, 1.0))
        except (ValueError, TypeError):
            return default

    def _safe_int(suffix: str, default: int = 0) -> int:
        """Return a non-negative int, normalising millisecond timestamps to seconds."""
        try:
            # float() first because the API may send "1234567890.0"
            val = int(float(headers.get(prefix + suffix, default)))
            # Guard against the API accidentally sending ms instead of s:
            # 4_102_444_800 is 2100-01-01 00:00:00 UTC -- no valid reset
            # timestamp should exceed that in seconds.
            if suffix.endswith("-reset") and val > 4_102_444_800:
                val = val // 1000
            return max(0, val)
        except (ValueError, TypeError):
            return default

    return {
        "session_utilization": _safe_float("5h-utilization"),
        "session_reset": _safe_int("5h-reset"),
        "weekly_utilization": _safe_float("7d-utilization"),
        "weekly_reset": _safe_int("7d-reset"),
        "overage_status": headers.get(prefix + "overage-status", ""),
        "fallback_status": headers.get(prefix + "fallback", ""),
    }


def collect_all(config: dict[str, Any]) -> UsageStats:
    """Collect all usage stats from local ``~/.claude/`` files and the Anthropic API.

    Combines history-based message/session counts, token totals from conversation
    files, live session detection, and API-sourced rate-limit data into a single
    ``UsageStats`` snapshot.  A rate-limit API failure is non-fatal; the error is
    recorded in ``stats.rate_limit_error`` and all other fields remain valid.
    """
    claude_dir = config["claude_dir"]
    # Two distinct files with similar names — keep them separate to avoid the
    # "history_path" shadowing bomb where a later reassignment silently swaps
    # which file the rest of collect_all reads/writes.
    claude_history_path = os.path.join(claude_dir, "history.jsonl")
    samples_path = os.path.join(claude_dir, HISTORY_FILENAME)

    stats = parse_history(claude_history_path)
    stats.subscription_type = _load_subscription_type(claude_dir)

    # Build date prefix strings used to filter conversation entries by timestamp.
    # A single pass over the files collects both today and week totals at once.
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    week_start = now - timedelta(days=6)
    week_dates = [(week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    tokens = _collect_tokens_single_pass(claude_dir, today_str, week_dates)
    stats.today_tokens = tokens["today_output"]
    stats.week_tokens = tokens["week_output"]
    stats.today_model_tokens = tokens["today_by_model"]
    stats.today_by_model_detailed = tokens.get("today_by_model_detailed", {})

    # Per-project breakdown: keep only the top 10 projects by output tokens,
    # preserving descending order so callers can iterate directly.
    project_totals = tokens.get("today_by_project", {})
    top_projects = sorted(project_totals.items(), key=lambda kv: kv[1], reverse=True)[:10]
    stats.today_by_project = dict(top_projects)

    # Cost estimates via pricing module. A single call covers today + week so
    # the pricing table is walked twice rather than per-model per-request.
    today_cost_summary = pricing.calculate_stats_cost(stats.today_by_model_detailed)
    week_cost_summary = pricing.calculate_stats_cost(tokens.get("week_by_model_detailed", {}))
    stats.today_cost = float(today_cost_summary.get("total", 0.0))
    stats.week_cost = float(week_cost_summary.get("total", 0.0))
    stats.cache_savings = float(week_cost_summary.get("cache_savings", 0.0))

    stats.active_sessions = get_active_sessions(claude_dir)

    rate_limits = fetch_rate_limits(claude_dir)
    now_ts = datetime.now().timestamp()

    if "error" in rate_limits:
        stats.rate_limit_error = rate_limits["error"]
    else:
        stats.session_utilization = rate_limits["session_utilization"]
        stats.session_reset = rate_limits["session_reset"]
        stats.weekly_utilization = rate_limits["weekly_utilization"]
        stats.weekly_reset = rate_limits["weekly_reset"]
        stats.overage_status = rate_limits["overage_status"]
        stats.fallback_status = rate_limits["fallback_status"]
        try:
            append_sample(samples_path, now_ts, stats.session_utilization, stats.weekly_utilization)
            prune(samples_path, keep_seconds=HISTORY_KEEP_DAYS * 86400, now=now_ts)
        except OSError:
            pass

    # Load 90 days of history for analytics/trends; the aggregators below
    # filter it down to their respective windows.
    samples = load_samples(samples_path, since_ts=now_ts - ANALYTICS_WINDOW_SECONDS)
    stats.session_history = aggregate(
        samples, "session", now=now_ts,
        window_seconds=SESSION_WINDOW_SECONDS, n_buckets=SESSION_BUCKETS,
    )
    stats.weekly_history = aggregate(
        samples, "weekly", now=now_ts,
        window_seconds=WEEKLY_WINDOW_SECONDS, n_buckets=WEEKLY_BUCKETS,
    )

    # Anomaly detection — compares today's session utilization against the
    # per-day peaks over prior days (requires >= 7 days of history).
    stats.anomaly = detect_anomaly(samples, today_usage=stats.session_utilization)

    # Cost optimisation tips (up to 3 short actionable suggestions).
    stats.tips = generate_tips(
        by_model=stats.today_by_model_detailed,
        week_cost=stats.week_cost,
        cache_savings=stats.cache_savings,
    )

    # Long-range trend aggregations for the popup UI.
    stats.daily_heatmap = daily_heatmap(samples, now=now_ts, n_days=90)
    # 52 weeks × 7 days = 364 cells — GitHub-style yearly calendar grid.
    stats.yearly_heatmap = daily_heatmap(samples, now=now_ts, n_days=364)
    stats.monthly_summary = monthly_summary(samples, now=now_ts, n_months=6)
    stats.hourly_histogram = hourly_histogram(samples, now=now_ts)

    # Prompt-cache savings opportunities — scans ~/.claude/projects/ for
    # repeated prompt prefixes; bounded cost by the mtime cutoff in the
    # analyser, so this stays cheap on every refresh.
    try:
        stats.cache_opportunities = analyze_cache_opportunities(claude_dir, days=7, now=now_ts)
    except OSError:
        stats.cache_opportunities = []

    # Live-activity rate: scans the same tree but only touches recently-
    # modified files, so it's O(active-sessions) per refresh.
    try:
        stats.live_activity = detect_live_activity(claude_dir, now=now_ts)
    except OSError:
        stats.live_activity = LiveActivity()

    # Ticker tape: latest ~40 assistant turns across active sessions, each
    # with its USD cost and primary tool. Drives the scrolling strip on the
    # OSD. Same cheap mtime-filtered scan as the other recent-activity modules.
    try:
        stats.ticker_items = scan_ticker_items(claude_dir, now=now_ts)
    except OSError:
        stats.ticker_items = []

    # Active subagent count — stat-only glob (no file contents opened).
    try:
        stats.active_subagent_count = count_active_subagents(claude_dir, now=now_ts)
    except OSError:
        stats.active_subagent_count = 0

    # Claude-authored weekly report — we only *read* the on-disk cache here;
    # regeneration happens in a background thread from the widget so the
    # refresh path stays synchronous and never blocks on a network call.
    from claude_usage.ai_report import load_cached_report
    cached_report = load_cached_report(claude_dir, now=now_ts)
    if cached_report is not None:
        stats.weekly_report_text = cached_report.text

    # Burn-rate forecasts: project when utilization will hit 100% at the current rate.
    # Requires at least 2 samples in the window; falls back to an empty dict otherwise.
    session_rate = forecast.calculate_burn_rate(samples, "session")
    weekly_rate = forecast.calculate_burn_rate(samples, "weekly")
    stats.session_forecast = forecast.forecast_time_to_limit(
        stats.session_utilization, session_rate, stats.session_reset,
    )
    stats.weekly_forecast = forecast.forecast_time_to_limit(
        stats.weekly_utilization, weekly_rate, stats.weekly_reset,
    )

    return stats
