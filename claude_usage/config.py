"""Configuration loading for the Claude Usage Desktop Widget.

Provides ``DEFAULT_CONFIG`` with safe built-in values and :func:`load_config`,
which merges an optional user-supplied JSON file on top of those defaults so
that any key the user omits keeps its default value automatically.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Type alias for the config dict returned by load_config().
# We intentionally use a plain dict rather than a TypedDict because the config
# is open-ended: user JSON files may contain extra keys consumed by other parts
# of the codebase, and we propagate them through unchanged.
Config = dict[str, Any]

# Built-in defaults used when a key is absent from the user's config.json.
DEFAULT_CONFIG: Config = {
    # Directory where Claude Code writes its usage logs.  The tilde is
    # expanded at import time so the path is always absolute.
    "claude_dir": os.path.expanduser("~/.claude"),

    # Rolling-window message limits.  These mirror the Claude Code plan
    # thresholds and are used only for the progress-bar display; the plugin
    # does not enforce them.
    "daily_message_limit": 200,    # max messages in one calendar day
    "weekly_message_limit": 1000,  # max messages across a 7-day window

    # Rolling-window token limits.  Five million tokens/day and 25 million/week
    # are typical Pro plan figures; adjust for your actual plan.
    "daily_token_limit": 5_000_000,
    "weekly_token_limit": 25_000_000,

    # Base poll interval (seconds): how often the widget refreshes usage.
    # 60 s keeps the data fresh while staying well under the /api/oauth/usage
    # budget (a low-volume endpoint shared with Claude Code).
    "refresh_seconds": 60,

    # Which providers to collect. "claude" is always the primary; add "codex"
    # to also poll the local OpenAI Codex CLI (`codex app-server`) and show
    # its 5h/weekly rings & bars beneath Claude's. POSIX-only.
    "providers": ["claude"],
    # How often (seconds) to actually spawn the codex app-server RPC; between
    # polls the on-disk cache is served. The RPC takes a couple of seconds,
    # so keep this much larger than refresh_seconds.
    "codex_poll_seconds": 300,

    # Max poll interval (seconds) the adaptive backoff climbs to when the API
    # rate-limits/errors; it snaps back to refresh_seconds on the next clean
    # refresh.
    "refresh_max_seconds": 300,

    # Optional path to a JSON file a Claude Code statusLine command dumps its
    # rate-limit payload to ({"captured_at": iso, "rate_limits": {"five_hour":
    # {"used_percentage", "resets_at"}, "seven_day": {...}}}). Claude Code
    # re-renders the statusline continuously during an active session, so a
    # fresh copy of this file carries the same numbers as /api/oauth/usage at
    # zero API cost. Empty = disabled; see "Statusline-fed rate limits" in
    # the README.
    "statusline_cache_path": "",
    # With statusline_cache_path set: while the dump is seconds-fresh, skip
    # the /api/oauth/usage call and only hit the endpoint at most once per
    # this many seconds — it is a low-budget endpoint shared with Claude
    # Code, and the scoped/overage fields plus headless (`claude -p`)
    # consumption are all it's still needed for.
    "usage_endpoint_min_seconds": 300,

    # Opacity of the floating OSD overlay window (0.0 = fully transparent,
    # 1.0 = fully opaque).  0.75 keeps it readable without obscuring content.
    "osd_opacity": 0.75,

    # Uniform scale factor applied to the OSD overlay's font and layout sizes.
    # 1.0 = default size; increase for HiDPI displays where the overlay appears
    # too small, or decrease to make it less intrusive.
    "osd_scale": 1.0,
    "notifications_enabled": True,
    "notify_thresholds": [0.75, 0.90],
    # Localhost JSON API server (opt-in). Exposes /usage and /healthz on
    # 127.0.0.1:<port> for shell integrations (tmux, polybar, waybar, etc.).
    "api_server_enabled": False,
    "api_server_host": "127.0.0.1",
    "api_server_port": 8765,
    # Webhooks (opt-in). Map event -> URL. Supported events:
    #   threshold_crossed, daily_report, anomaly, budget_projection, burn_alert
    "webhooks": {},
    # Appearance: theme palette name (see themes.py for the 5 ships).
    "theme": "default",
    # Whether the OSD paints a scrolling per-turn cost ticker along the
    # bottom edge. Toggle at runtime via the right-click menu.
    "show_ticker": True,
    # OSD view mode — "bars" (default) or "gauge". See overlay.VIEW_MODES.
    "osd_view_mode": "bars",
    # Where the OSD anchors on screen. One of the four corners, or "custom"
    # to use the exact osd_x / osd_y coordinates below (set automatically
    # when you drag the overlay). See overlay.OSD_POSITIONS.
    "osd_position": "top-right",
    # Absolute screen coordinates used only when osd_position == "custom".
    # null means "not set yet" — the overlay falls back to top-right.
    "osd_x": None,
    "osd_y": None,
    # Session UI state restored on the next launch. osd_scale is also read
    # by the overlay at startup; these two are written automatically as the
    # user minimizes / hides the OSD so it reopens the way they left it.
    "osd_minimized": False,
    "osd_visible": True,
    # Keep the OSD pinned above other windows. Turn off (right-click ->
    # "Always on top") to let it sit as a normal background desktop widget
    # that the window manager stacks like any other window.
    "osd_always_on_top": True,

    # --- Peak-window awareness (Anthropic's weekday reduced-limit window) ---
    # When enabled, an unobtrusive hint appears next to the 5h session reset
    # during the reduced-limit window. Data-driven so you can adjust it when
    # Anthropic changes the window. Default ~5-11 AM US Pacific, Mon-Fri.
    "peak_awareness_enabled": True,
    "peak_timezone": "America/Los_Angeles",
    "peak_start_hour": 5,    # local hour the window starts (inclusive)
    "peak_end_hour": 11,     # local hour the window ends (exclusive)
    "peak_weekdays": [0, 1, 2, 3, 4],  # datetime.weekday(): 0=Mon .. 6=Sun

    # --- Monthly budget cap + projection ---
    # Set monthly_budget_usd > 0 to see month-to-date spend + a linear
    # end-of-month projection in the popup, and (optionally) a once-per-month
    # notification when projected to exceed the cap. 0 disables the feature
    # entirely (no extra month-wide token scan).
    "monthly_budget_usd": 0.0,
    "budget_notify_enabled": True,
    "budget_notify_ratio": 1.0,  # notify when projected >= ratio * cap

    # --- Real-time burn / spike / retry-storm alerts ---
    # An OSD badge + debounced (once-per-episode) notification when the 5h
    # window burns abnormally fast or a single turn / retry loop spikes tokens.
    # Desktop notifications also require notifications_enabled.
    "burn_alerts_enabled": True,
    "burn_warn_pct_per_min": 2.0,   # fast-burn WARN: session pp/min
    "burn_crit_pct_per_min": 5.0,   # fast-burn CRIT: session pp/min
    "burn_window_seconds": 600,     # window the burn rate is measured over
    "spike_token_multiplier": 4.0,  # turn output >= mult * recent baseline
    "spike_min_tokens": 20_000,     # absolute floor for a spike / heavy turn
    "spike_baseline_min_turns": 5,  # prior turns needed before spike fires
    "retry_storm_turns": 3,         # heavy turns clustered => storm
    "retry_storm_window_seconds": 120,
    "burn_alert_cooldown_seconds": 900,  # min seconds between same-episode notifies
}


def load_config(path: str) -> Config:
    """Load and return the merged configuration dictionary.

    Starts from a shallow copy of :data:`DEFAULT_CONFIG` so every key is
    guaranteed to be present even if *path* does not exist or is only a partial
    override.  Unknown keys from the user file are preserved.
    """
    cfg: Config = dict(DEFAULT_CONFIG)
    if not os.path.isfile(path):
        return cfg

    try:
        with open(path, encoding="utf-8") as f:
            user_cfg: object = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        # Bad JSON or unreadable file -- warn but continue with defaults so
        # the widget still starts rather than crashing on a config error.
        print(f"WARNING: Failed to load config {path}: {exc}", file=sys.stderr)
        return cfg

    if not isinstance(user_cfg, dict):
        print(
            f"WARNING: Config {path} must be a JSON object, "
            f"got {type(user_cfg).__name__}; using defaults.",
            file=sys.stderr,
        )
        return cfg

    # Merge: user values overwrite defaults, unknown keys are added.
    cfg.update(user_cfg)
    return cfg


def user_config_path() -> str:
    """Return the path where runtime preference changes should be persisted.

    Uses ``$XDG_CONFIG_HOME/claude-usage/config.json`` when set, otherwise
    ``~/.config/claude-usage/config.json`` on Linux/macOS. On Windows the
    expanduser fallback still yields ``%USERPROFILE%\\.config\\...`` which is
    non-idiomatic but functional — we prefer one code path over platform
    dispatch for something the widget writes a few times per week.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "claude-usage", "config.json")


def save_config(path: str, cfg: Config) -> None:
    """Atomically persist *cfg* to *path* (creating parent dirs as needed).

    Writes to ``path + ".tmp"`` then ``os.replace``s onto the target so a
    crash mid-write can never produce a truncated JSON file. Callers should
    handle :class:`OSError` for read-only targets (e.g. packaged installs).
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
