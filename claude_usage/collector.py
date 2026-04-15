"""Data collection from ~/.claude/ sources and Anthropic API."""

import glob
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError


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
    session_reset: int = 0  # unix timestamp
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
    week_start = today_start - timedelta(days=6)  # rolling 7-day window

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
            dt = datetime.fromtimestamp(ts_ms / 1000)
            sid = entry.get("sessionId", "")

            if dt >= today_start:
                stats.today_messages += 1
                today_session_ids.add(sid)
                hour = dt.hour
                stats.today_hourly[hour] = stats.today_hourly.get(hour, 0) + 1

            if dt >= week_start:
                stats.week_messages += 1
                week_session_ids.add(sid)

    stats.today_sessions = len(today_session_ids)
    stats.week_sessions = len(week_session_ids)
    return stats


def collect_tokens_from_conversations(claude_dir: str, date_prefixes: list[str]) -> dict:
    """Scan conversation JSONL files for token usage on given dates."""
    result = {"total_output": 0, "total_input": 0, "by_model": {}}
    projects_dir = os.path.join(claude_dir, "projects")
    if not os.path.isdir(projects_dir):
        return result

    for jsonl_path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
        if os.sep + "subagents" + os.sep in jsonl_path:
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
            os.kill(pid, 0)
            active.append(sess)
        except (ProcessLookupError, PermissionError):
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
            return None

    # 2. Try macOS Keychain (credentials stored by Claude Code for macOS)
    if os.uname().sysname == "Darwin":
        try:
            import subprocess
            result = subprocess.run(
                ["security", "find-generic-password",
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
        return {"error": "No credentials found"}

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
    except (URLError, OSError, TimeoutError):
        return {"error": "API request failed"}

    prefix = "anthropic-ratelimit-unified-"
    if not any(k.startswith(prefix) for k in headers):
        return {"error": "No rate limit headers in response"}

    def _h(suffix, default="0"):
        return headers.get(prefix + suffix, default)

    return {
        "session_utilization": float(_h("5h-utilization")),
        "session_reset": int(_h("5h-reset")),
        "weekly_utilization": float(_h("7d-utilization")),
        "weekly_reset": int(_h("7d-reset")),
        "overage_status": _h("overage-status", ""),
        "fallback_status": _h("fallback", ""),
    }


def collect_all(config: dict) -> UsageStats:
    """Collect all usage stats from ~/.claude/ data sources and API."""
    claude_dir = config["claude_dir"]
    history_path = os.path.join(claude_dir, "history.jsonl")

    stats = parse_history(history_path)

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    week_start = now - timedelta(days=6)
    week_dates = [(week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    today_tokens = collect_tokens_from_conversations(claude_dir, [today_str])
    stats.today_tokens = today_tokens["total_output"]
    stats.today_model_tokens = {
        model: data["output"] for model, data in today_tokens["by_model"].items()
    }

    week_tokens = collect_tokens_from_conversations(claude_dir, week_dates)
    stats.week_tokens = week_tokens["total_output"]

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
