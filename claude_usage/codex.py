"""OpenAI Codex rate-limit collector (opt-in second provider).

Talks to the local ``codex`` CLI's ``app-server`` over stdio JSON-RPC:
``initialize`` -> ``initialized`` -> ``account/rateLimits/read``. The
response carries a ``rateLimits`` object with a ``primary`` (~5h) and
``secondary`` (weekly) window, each with ``usedPercent`` and ``resetsAt``
— the same shape as Claude's session/weekly pair, so the overlay can
render them with the exact same ring/bar primitives.

Spawning the app-server takes a couple of seconds, so results are cached
on disk (`~/.cache/claude-usage/codex_limits.json`) and only refreshed
every ``poll_seconds``. Between polls — and on RPC failure — the cache is
served, with expired windows clamped back to zero exactly like the Claude
sample-fallback path in ``collector.collect_all``.

POSIX-only for now: the reader uses ``select`` on pipes, which does not
work on Windows. On other platforms ``collect_codex`` reports
unavailable and the UI simply never shows the Codex rows.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

RPC_TIMEOUT_SECONDS = 12
DEFAULT_POLL_SECONDS = 300
CACHE_PATH = Path.home() / ".cache" / "claude-usage" / "codex_limits.json"
_BIN_CANDIDATES = ("/opt/homebrew/bin/codex", "/usr/local/bin/codex")


def find_codex_bin() -> str | None:
    """Locate the ``codex`` CLI, preferring whatever is on PATH."""
    which = shutil.which("codex")
    if which:
        return which
    for candidate in _BIN_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def _rate_limits_rpc(codex_bin: str, timeout: float = RPC_TIMEOUT_SECONDS) -> dict[str, Any] | None:
    """Run one ``account/rateLimits/read`` round-trip against ``codex app-server``."""
    proc = subprocess.Popen(
        [codex_bin, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    def send(obj: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    result: dict[str, Any] | None = None
    try:
        send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {
                "name": "claude-usage-widget",
                "title": "Claude Usage Widget",
                "version": "0",
            }},
        })
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and result is None:
            assert proc.stdout is not None
            ready, _, _ = select.select(
                [proc.stdout], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == 1:
                send({"jsonrpc": "2.0", "method": "initialized"})
                # The app-server needs a beat between the handshake and the
                # first real request or it drops it on the floor.
                time.sleep(0.6)
                send({"jsonrpc": "2.0", "id": 2,
                      "method": "account/rateLimits/read", "params": {}})
            elif msg.get("id") == 2:
                result = msg.get("result")
    finally:
        try:
            proc.kill()
        except OSError:
            pass
    return result


def parse_rate_limits(payload: Any) -> dict[str, Any] | None:
    """Extract the two utilization windows from a rateLimits/read result.

    Returns ``{"session_pct", "session_reset", "weekly_pct", "weekly_reset"}``
    (pct 0..1, reset as unix seconds, 0 when absent), or None when the
    payload has no usable window data.
    """
    if not isinstance(payload, dict):
        return None
    limits = payload.get("rateLimits")
    if not isinstance(limits, dict):
        return None

    def window(block: Any) -> tuple[float, int] | None:
        if not isinstance(block, dict) or block.get("usedPercent") is None:
            return None
        try:
            pct = max(0.0, min(1.0, float(block["usedPercent"]) / 100.0))
        except (TypeError, ValueError):
            return None
        reset = block.get("resetsAt")
        try:
            reset_ts = int(reset) if reset is not None else 0
        except (TypeError, ValueError):
            reset_ts = 0
        if reset_ts > 10**12:  # milliseconds — normalise to seconds
            reset_ts //= 1000
        return pct, reset_ts

    primary = window(limits.get("primary"))
    secondary = window(limits.get("secondary"))
    if primary is None and secondary is None:
        return None
    return {
        "session_pct": primary[0] if primary else 0.0,
        "session_reset": primary[1] if primary else 0,
        "weekly_pct": secondary[0] if secondary else 0.0,
        "weekly_reset": secondary[1] if secondary else 0,
    }


def _load_cache() -> dict[str, Any] | None:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _save_cache(payload: dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": time.time(), "payload": payload}, fh)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def _clamp_expired(parsed: dict[str, Any], now_ts: float) -> dict[str, Any]:
    """A window whose reset has passed has rolled over — show 0, not stale %."""
    out = dict(parsed)
    if out["session_reset"] and now_ts >= out["session_reset"]:
        out["session_pct"], out["session_reset"] = 0.0, 0
    if out["weekly_reset"] and now_ts >= out["weekly_reset"]:
        out["weekly_pct"], out["weekly_reset"] = 0.0, 0
    return out


def collect_codex(poll_seconds: int = DEFAULT_POLL_SECONDS) -> dict[str, Any]:
    """Return Codex utilization for the overlay; never raises.

    ``{"available": bool, "session_pct", "session_reset", "weekly_pct",
    "weekly_reset", "error": str}`` — available=False hides the Codex UI.
    """
    unavailable = {
        "available": False, "error": "",
        "session_pct": 0.0, "session_reset": 0,
        "weekly_pct": 0.0, "weekly_reset": 0,
    }
    if os.name != "posix":
        return {**unavailable, "error": "codex provider is POSIX-only for now"}
    codex_bin = find_codex_bin()
    if codex_bin is None:
        return {**unavailable, "error": "codex binary not found"}

    now_ts = time.time()
    cache = _load_cache()
    if cache is not None:
        age = now_ts - float(cache.get("fetched_at", 0) or 0)
        parsed = parse_rate_limits(cache.get("payload"))
        if parsed is not None and 0 <= age < poll_seconds:
            return {"available": True, "error": "", **_clamp_expired(parsed, now_ts)}

    payload = None
    try:
        payload = _rate_limits_rpc(codex_bin)
    except OSError:
        payload = None
    parsed = parse_rate_limits(payload)
    if parsed is not None:
        assert isinstance(payload, dict)
        _save_cache(payload)
        return {"available": True, "error": "", **_clamp_expired(parsed, now_ts)}

    # RPC failed — fall back to any cache, however old, before giving up.
    if cache is not None:
        parsed = parse_rate_limits(cache.get("payload"))
        if parsed is not None:
            return {"available": True, "error": "rpc failed; serving cache",
                    **_clamp_expired(parsed, now_ts)}
    return {**unavailable, "error": "rateLimits/read returned no window data"}
