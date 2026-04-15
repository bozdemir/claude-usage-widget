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
