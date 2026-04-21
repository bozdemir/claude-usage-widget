"""Command-line interface for headless / scripted access to usage stats."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Sequence

from claude_usage import __version__
from claude_usage.collector import UsageStats, collect_all
from claude_usage.config import load_config


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser used by the CLI dispatcher."""
    p = argparse.ArgumentParser(
        prog="claude-usage",
        description="Claude Code usage tracker — GUI by default, CLI on demand.",
    )
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    p.add_argument("--json", action="store_true", help="Emit full stats as JSON.")
    p.add_argument("--once", action="store_true", help="Collect once and print JSON.")
    p.add_argument("--field", metavar="NAME", default=None,
                   help="Print a single UsageStats field by name.")
    return p


def _usage_stats_to_dict(stats: UsageStats) -> dict:
    """Convert a UsageStats dataclass to a JSON-serialisable dict."""
    return asdict(stats) if is_dataclass(stats) else dict(stats)


def _default_config_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = os.path.join(base_dir, "config.json")
    if not os.path.isfile(cfg):
        cfg = os.path.join(base_dir, "config.json.example")
    return cfg


def run_cli(argv: Sequence[str]) -> int:
    """Dispatch a single CLI invocation. Returns a process exit code."""
    args = build_parser().parse_args(list(argv))

    if args.version:
        print(__version__)
        return 0

    if args.json or args.once or args.field:
        config = load_config(_default_config_path())
        stats = collect_all(config)
        data = _usage_stats_to_dict(stats)

        if args.field is not None:
            if args.field not in data:
                print(f"error: unknown field {args.field!r}", file=sys.stderr)
                return 2
            print(data[args.field])
            return 0

        json.dump(data, sys.stdout, default=str, indent=2, sort_keys=True)
        print()
        return 0

    # No CLI flag — caller should fall through to GUI.
    return -1


def main() -> int:
    """Entry point for the ``claude-usage`` console script."""
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
