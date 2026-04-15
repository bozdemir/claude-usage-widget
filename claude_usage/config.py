import json
import os

DEFAULT_CONFIG = {
    "claude_dir": os.path.expanduser("~/.claude"),
    "daily_message_limit": 200,
    "weekly_message_limit": 1000,
    "daily_token_limit": 5_000_000,
    "weekly_token_limit": 25_000_000,
    "refresh_seconds": 30,
    "osd_opacity": 0.75,
    "osd_scale": 1.0,
}


def load_config(path: str) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(path):
        try:
            with open(path) as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg)
        except (json.JSONDecodeError, OSError) as e:
            import sys
            print(f"WARNING: Failed to load config {path}: {e}", file=sys.stderr)
    return cfg
