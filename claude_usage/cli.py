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
    p.add_argument("--export", choices=("csv", "json"), default=None,
                   help="Export history as CSV or JSON to stdout.")
    p.add_argument("--days", type=int, default=30,
                   help="Look-back window for --export (default: 30).")
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


def _launch_gui() -> None:
    """Launch the platform-appropriate GUI (GTK3 on Linux, AppKit on macOS)."""
    import signal

    # CLI entry is usually invoked by a console script shim (`claude-usage`),
    # so restore the default SIGINT handler so Ctrl-C kills the GUI cleanly.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == "darwin":
        from claude_usage.widget_macos import ClaudeUsageTray  # noqa: WPS433
        config = load_config(_default_config_path())
        app = ClaudeUsageTray(config)
        app.run()
        return

    if sys.platform.startswith("linux"):
        # Force XWayland; native Wayland doesn't support the override-redirect
        # tricks needed for our borderless OSD overlay.
        os.environ.setdefault("GDK_BACKEND", "x11")

        # Guarded gi import — if the system ``python3-gi`` is broken or
        # shadowed by a partial user-local install, bail out with a clear
        # message instead of a confusing internal traceback.
        try:
            import gi  # type: ignore[import-not-found]
        except ImportError as exc:
            _print_linux_install_instructions(exc)
            sys.exit(1)

        _ensure_gi_cairo_linux()

        try:
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk  # type: ignore[attr-defined]
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3  # noqa: F401
        except (ValueError, ImportError) as exc:
            _print_linux_install_instructions(exc)
            sys.exit(1)

        from claude_usage.widget import ClaudeUsageTray

        config = load_config(_default_config_path())
        _tray = ClaudeUsageTray(config)  # noqa: F841 — tray owns its lifecycle
        Gtk.main()
        return

    print(f"ERROR: Unsupported platform: {sys.platform}", file=sys.stderr)
    sys.exit(1)


def _print_linux_install_instructions(exc: Exception) -> None:
    """Print actionable install / repair instructions for GTK-related failures."""
    print(
        "\nERROR: GTK / GObject Introspection stack is missing or broken.\n"
        f"  ({exc.__class__.__name__}: {exc})\n"
        "\n"
        "Required system packages:\n"
        "  Ubuntu/Debian:\n"
        "    sudo apt install python3-gi python3-gi-cairo python3-cairo \\\n"
        "         gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7\n"
        "  Fedora:\n"
        "    sudo dnf install python3-gobject python3-gobject-cairo \\\n"
        "         libappindicator-gtk3 libnotify\n"
        "  Arch:\n"
        "    sudo pacman -S python-gobject python-cairo \\\n"
        "         libappindicator-gtk3 libnotify\n"
        "\n"
        "If 'circular import' appears, there may be a broken user-local install:\n"
        "  pip uninstall -y PyGObject pycairo\n"
        "  sudo apt install --reinstall python3-gi  # or your distro equivalent\n"
        "\n"
        "GNOME users: the tray icon also needs the AppIndicator extension:\n"
        "  https://extensions.gnome.org/extension/615/appindicator-support/\n",
        file=sys.stderr,
    )


def _ensure_gi_cairo_linux() -> None:
    """Try system gi-cairo first, then GNOME snap fallback, else warn."""
    import gi  # noqa: WPS433

    try:
        gi.require_foreign("cairo")
        return
    except Exception:
        pass

    import glob as _glob
    import importlib.util

    ver = f"{sys.version_info.major}{sys.version_info.minor}"
    snap_so_list = sorted(
        _glob.glob(
            f"/snap/gnome-*/*/usr/lib/python3/dist-packages/gi/"
            f"_gi_cairo.cpython-{ver}*.so"
        ),
        reverse=True,
    )
    for snap_so in snap_so_list:
        try:
            spec = importlib.util.spec_from_file_location("gi._gi_cairo", snap_so)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules["gi._gi_cairo"] = mod
            spec.loader.exec_module(mod)
            return
        except Exception:
            continue

    print(
        "WARNING: python3-gi-cairo not found. OSD overlay may not render.\n"
        "  Ubuntu/Debian: sudo apt install python3-gi-cairo\n"
        "  Fedora:        sudo dnf install python3-gobject-cairo\n"
        "  Arch:          sudo pacman -S python-gobject\n",
        file=sys.stderr,
    )


def main() -> int:
    """Entry point for the ``claude-usage`` console script.

    Dispatches CLI flags first; if none were given, launches the GUI and
    returns once the GUI exits.
    """
    if sys.version_info < (3, 10):
        print(
            "ERROR: Python 3.10+ is required (collector.py uses str|None syntax).",
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
