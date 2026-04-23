"""Command-line interface + single-process GUI entry point.

``run_cli(argv)`` handles the CLI flags (``--version``, ``--json``,
``--field``, ``--export``); when no flag is given, ``main()`` falls through
to the cross-platform PySide6 GUI (:class:`claude_usage.widget.ClaudeUsageApp`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Sequence

from claude_usage import __version__
from claude_usage.collector import UsageStats, collect_all
from claude_usage.config import load_config, user_config_path


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
    p.add_argument("--export", choices=("csv", "json"), default=None,
                   help="Export history as CSV or JSON to stdout.")
    p.add_argument("--days", type=int, default=30,
                   help="Look-back window for --export (default: 30).")
    return p


def _usage_stats_to_dict(stats: UsageStats) -> dict:
    return asdict(stats) if is_dataclass(stats) else dict(stats)


def _default_config_path() -> str:
    """Pick the config.json path to load on startup.

    Precedence: user's XDG config > project-local config.json (repo
    checkouts only) > the user XDG path again. In the last case
    :func:`load_config` gracefully returns :data:`DEFAULT_CONFIG`, so a
    first-run pip install does not need a config file on disk — the GUI
    will write one the first time the user touches a menu.
    """
    user = user_config_path()
    if os.path.isfile(user):
        return user
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_cfg = os.path.join(base_dir, "config.json")
    if os.path.isfile(project_cfg):
        return project_cfg
    return user


def run_cli(argv: Sequence[str]) -> int:
    """Dispatch a single CLI invocation. Returns a process exit code.

    Returns -1 when no CLI flag was provided — the caller should then launch
    the GUI.
    """
    args = build_parser().parse_args(list(argv))

    if args.version:
        print(__version__)
        return 0

    if args.export:
        from claude_usage.exporter import export_history
        config = load_config(_default_config_path())
        history_path = os.path.join(config["claude_dir"], "usage-history.jsonl")
        count = export_history(history_path, fmt=args.export, days=args.days, out=sys.stdout)
        print(f"# exported {count} samples", file=sys.stderr)
        return 0

    if args.json or args.once or args.field:
        config = load_config(_default_config_path())
        stats = collect_all(config)
        data = _usage_stats_to_dict(stats)
        # Same privacy redaction as the localhost API — never leak raw prompt
        # text through --json / --field output.
        from claude_usage.api_server import _redact_external
        data = _redact_external(data)

        if args.field is not None:
            if args.field not in data:
                print(f"error: unknown field {args.field!r}", file=sys.stderr)
                return 2
            value = data[args.field]
            # Render containers as JSON so shell pipelines can jq/grep them;
            # scalars stay in their native repr for backwards-compat with
            # existing status-bar scripts that expect raw numbers.
            if isinstance(value, (dict, list)):
                json.dump(value, sys.stdout, default=str)
                print()
            else:
                print(value)
            return 0

        json.dump(data, sys.stdout, default=str, indent=2, sort_keys=True)
        print()
        return 0

    return -1


def _print_qt_install_hint(exc: Exception) -> None:
    """Print install instructions for Qt's xcb platform plugin runtime deps."""
    print(
        "\nERROR: Qt platform plugin failed to load.\n"
        f"  ({exc.__class__.__name__}: {exc})\n"
        "\n"
        "Qt 6.5+ needs one small system library that ships outside the wheel:\n"
        "  Ubuntu/Debian:  sudo apt install -y libxcb-cursor0\n"
        "  Fedora:         sudo dnf install -y xcb-util-cursor\n"
        "  Arch:           sudo pacman -S xcb-util-cursor\n",
        file=sys.stderr,
    )


def _launch_gui() -> None:
    """Launch the PySide6 GUI (cross-platform)."""
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Force XWayland on Linux: native Wayland forbids absolute window
    # positioning, so ``QWidget.move()``, ``QMenu.popup(global_pos)``, and
    # any drag-to-reposition logic silently break. XCB (XWayland) honours
    # the standard X11 positioning semantics our OSD relies on.
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from claude_usage.widget import ClaudeUsageApp

    # High-DPI is default in Qt 6; no special attribute needed.
    try:
        app = QApplication.instance() or QApplication(sys.argv)
    except Exception as exc:
        _print_qt_install_hint(exc)
        raise

    # Hint to window managers that this is a utility/panel process — some
    # WMs use this to decide whether to show a dock icon.
    app.setApplicationName("claude-usage")
    app.setDesktopFileName("claude-usage")
    if app is None:
        # QApplication() returned None — usually because the xcb plugin
        # couldn't load.  Print a helpful hint before Qt's own abort kicks in.
        _print_qt_install_hint(RuntimeError("QApplication failed to initialise"))
        sys.exit(1)
    app.setQuitOnLastWindowClosed(False)

    config = load_config(_default_config_path())
    _controller = ClaudeUsageApp(config)  # keep a reference
    _ = _controller  # suppress unused-var warnings; QApplication holds ownership
    sys.exit(app.exec())


def main() -> int:
    """Entry point for the ``claude-usage`` console script."""
    if sys.version_info < (3, 10):
        print(
            "ERROR: Python 3.10+ is required.",
            file=sys.stderr,
        )
        return 1

    rc = run_cli(sys.argv[1:])
    if rc >= 0:
        return rc

    # No CLI flag — fall through to the GUI.
    _launch_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
