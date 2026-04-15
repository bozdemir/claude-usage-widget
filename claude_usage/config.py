"""Configuration loading for the Claude Usage Desktop Widget.

Provides DEFAULT_CONFIG with safe built-in values and load_config(), which
merges an optional user-supplied JSON file on top of those defaults so that
any key the user omits keeps its default value automatically.
"""

import json
import os

# Built-in defaults used when a key is absent from the user's config.json.
DEFAULT_CONFIG = {
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

    # How often (in seconds) the widget re-reads the usage logs and refreshes
    # its display.  30 s keeps the data reasonably fresh without hammering disk.
    "refresh_seconds": 30,

    # Opacity of the floating OSD overlay window (0.0 = fully transparent,
    # 1.0 = fully opaque).  0.75 keeps it readable without obscuring content.
    "osd_opacity": 0.75,

    # Uniform scale factor applied to the OSD overlay's font and layout sizes.
    # 1.0 = default size; increase for HiDPI displays where the overlay appears
    # too small, or decrease to make it less intrusive.
    "osd_scale": 1.0,
}


def load_config(path: str) -> dict:
    # Start from a shallow copy of the defaults so every key is guaranteed
    # to be present in the returned dict even if the file is missing or partial.
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(path):
        try:
            with open(path) as f:
                user_cfg = json.load(f)
            # Merge: user values overwrite defaults, unknown keys are added.
            cfg.update(user_cfg)
        except (json.JSONDecodeError, OSError) as e:
            # Bad JSON or unreadable file — warn but continue with defaults so
            # the widget still starts rather than crashing on a config error.
            import sys
            print(f"WARNING: Failed to load config {path}: {e}", file=sys.stderr)
    return cfg
