"""Data collection from ~/.claude/ sources and Anthropic API."""

import glob
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


@dataclass
class UsageStats:
    """Aggregated usage statistics from local data and API rate limits."""
    today_messages: int = 0
    today_sessions: int = 0
    week_messages: int = 0
    week_sessions: int = 0
    today_tokens: int = 0
    week_tokens: int = 0
    active_sessions: list = field(default_factory=list)
    today_model_tokens: dict = field(default_factory=dict)
    today_hourly: dict = field(default_factory=dict)
    # Real rate limit data from API
    session_utilization: float = 0.0  # 0.0 - 1.0
    session_reset: int = 0  # unix timestamp (seconds)
    weekly_utilization: float = 0.0
    weekly_reset: int = 0
    overage_status: str = ""  # "rejected" or "allowed"
    fallback_status: str = ""  # "available" or ""
    rate_limit_error: str = ""  # error message if API call fails


def parse_history(path: str) -> UsageStats:
    """Parse ~/.claude/history.jsonl for message counts and session tracking."""
    stats = UsageStats()
    if not os.path.isfile(path):
        return stats

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)

    today_session_ids = set()
    week_session_ids = set()

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


def _collect_tokens_single_pass(claude_dir: str, today_prefix: str, week_prefixes: list[str]) -> dict:
    """Scan conversation JSONL files once, collecting tokens for both today and week."""
    result = {
        "today_output": 0, "week_output": 0,
        "today_by_model": {},
    }
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return result

    projects_dir = os.path.realpath(projects_dir)

    for jsonl_path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        parts = jsonl_path.split(os.sep)
        if "subagents" in parts:
            continue
        _parse_tokens_file(jsonl_path, today_prefix, week_prefixes, result)

    return result


def _parse_tokens_file(path: str, today_prefix: str, week_prefixes: list[str], result: dict):
    """Extract token usage from a single conversation JSONL file."""
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
            is_today = timestamp.startswith(today_prefix)
            is_week = is_today or any(timestamp.startswith(p) for p in week_prefixes)
            if not is_week:
                continue

            msg = entry.get("message", {})
            if not isinstance(msg, dict):
                continue

            usage = msg.get("usage", {})
            output_tokens = usage.get("output_tokens", 0)
            model = msg.get("model", "unknown")

            if is_week:
                result["week_output"] += output_tokens

            if is_today:
                result["today_output"] += output_tokens
                result["today_by_model"][model] = result["today_by_model"].get(model, 0) + output_tokens


# Keep old function name for test compatibility
def collect_tokens_from_conversations(claude_dir: str, date_prefixes: list[str]) -> dict:
    """Scan conversation JSONL files for token usage on given dates."""
    result = {"total_output": 0, "total_input": 0, "by_model": {}}
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


def _parse_conversation_tokens(path: str, date_prefixes: list[str], result: dict):
    """Extract token usage from a single conversation JSONL file."""
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


def get_active_sessions(claude_dir: str) -> list[dict]:
    """Return list of active Claude sessions (PID still running)."""
    sessions_dir = os.path.join(claude_dir, "sessions")
    if not os.path.isdir(sessions_dir):
        return []

    active = []
    for fname in os.listdir(sessions_dir):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(sessions_dir, fname)
        try:
            with open(path) as f:
                sess = json.load(f)
            pid = sess.get("pid", 0)
            if pid <= 0:
                continue
            os.kill(pid, 0)
            active.append(sess)
        except PermissionError:
            active.append(sess)
        except ProcessLookupError:
            pass
        except (json.JSONDecodeError, OSError):
            continue
    return active


def _load_credentials(claude_dir: str) -> str | None:
    """Load OAuth access token from credentials file or macOS Keychain."""
    # 1. Try the credentials file (Linux + macOS)
    creds_path = os.path.join(claude_dir, ".credentials.json")
    if os.path.isfile(creds_path):
        try:
            with open(creds_path) as f:
                creds = json.load(f)
            return creds["claudeAiOauth"]["accessToken"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # Fall through to Keychain on macOS

    # 2. Try macOS Keychain
    if sys.platform == "darwin":
        try:
            import subprocess
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password",
                 "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                creds = json.loads(result.stdout.strip())
                return creds["claudeAiOauth"]["accessToken"]
        except Exception:
            pass

    return None


def fetch_rate_limits(claude_dir: str) -> dict:
    """Fetch rate limit data from Anthropic API using OAuth credentials.

    Makes a minimal API call (1 token to haiku) and reads rate limit headers.
    Uses urllib to keep credentials in-process (not exposed via /proc/cmdline).
    """
    token = _load_credentials(claude_dir)
    if not token:
        return {"error": "No credentials found — run 'claude' to log in"}

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
            return {"error": "Credentials expired — re-authenticate with 'claude'"}
        if e.code == 429:
            headers = {k.lower(): v for k, v in e.headers.items()}
            prefix = "anthropic-ratelimit-unified-"
            if any(k.startswith(prefix) for k in headers):
                return _parse_rate_limit_headers(headers)
            return {"error": "Rate limited — try again later"}
        return {"error": f"API error {e.code}"}
    except (URLError, OSError, TimeoutError):
        return {"error": "API request failed — check network"}

    return _parse_rate_limit_headers(headers)


def _parse_rate_limit_headers(headers: dict) -> dict:
    """Parse rate limit values from API response headers with safe type conversion."""
    prefix = "anthropic-ratelimit-unified-"
    if not any(k.startswith(prefix) for k in headers):
        return {"error": "No rate limit headers in response"}

    def _safe_float(suffix, default=0.0):
        try:
            val = float(headers.get(prefix + suffix, default))
            if math.isnan(val) or math.isinf(val):
                return default
            return max(0.0, min(val, 1.0))
        except (ValueError, TypeError):
            return default

    def _safe_int(suffix, default=0):
        try:
            val = int(float(headers.get(prefix + suffix, default)))
            # Sanity: timestamps > year 2100 in seconds likely means milliseconds
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


def collect_all(config: dict) -> UsageStats:
    """Collect all usage stats from ~/.claude/ data sources and API."""
    claude_dir = config["claude_dir"]
    history_path = os.path.join(claude_dir, "history.jsonl")

    stats = parse_history(history_path)

    # Single-pass token collection for both today and week
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    week_start = now - timedelta(days=6)
    week_dates = [(week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    tokens = _collect_tokens_single_pass(claude_dir, today_str, week_dates)
    stats.today_tokens = tokens["today_output"]
    stats.week_tokens = tokens["week_output"]
    stats.today_model_tokens = tokens["today_by_model"]

    stats.active_sessions = get_active_sessions(claude_dir)

    # Fetch real rate limits from API
    rate_limits = fetch_rate_limits(claude_dir)
    if "error" in rate_limits:
        stats.rate_limit_error = rate_limits["error"]
    else:
        stats.session_utilization = rate_limits["session_utilization"]
        stats.session_reset = rate_limits["session_reset"]
        stats.weekly_utilization = rate_limits["weekly_utilization"]
        stats.weekly_reset = rate_limits["weekly_reset"]
        stats.overage_status = rate_limits["overage_status"]
        stats.fallback_status = rate_limits["fallback_status"]

    return stats
