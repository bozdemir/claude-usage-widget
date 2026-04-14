#!/usr/bin/env python3
"""Claude Usage Desktop Widget — system tray app for Claude Code usage tracking."""

import os
import signal
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")
if not os.path.isfile(CONFIG_PATH):
    CONFIG_PATH = os.path.join(_BASE_DIR, "config.json.example")


def _main_macos():
    """macOS entry point: uses AppKit/rumps."""
    from claude_usage.config import load_config
    from claude_usage.widget_macos import ClaudeUsageTray

    config = load_config(CONFIG_PATH)
    app = ClaudeUsageTray(config)
    app.run()


def _main_linux():
    """Linux entry point: uses GTK3/AppIndicator."""
    # Force XWayland for reliable borderless windows on Wayland compositors.
    os.environ.setdefault("GDK_BACKEND", "x11")

    try:
        import gi
        gi.require_foreign("cairo")
    except (ImportError, Exception):
        print(
            "ERROR: python3-gi-cairo is required for the OSD overlay.\n"
            "Install it with:\n"
            "  Ubuntu/Debian: sudo apt install python3-gi-cairo\n"
            "  Fedora:        sudo dnf install python3-gobject-cairo\n"
            "  Arch:          sudo pacman -S python-gobject\n",
            file=sys.stderr,
        )
        sys.exit(1)

    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    from claude_usage.config import load_config
    from claude_usage.widget import ClaudeUsageTray

    config = load_config(CONFIG_PATH)
    _tray = ClaudeUsageTray(config)
    Gtk.main()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == "darwin":
        _main_macos()
    elif sys.platform.startswith("linux"):
        _main_linux()
    else:
        print(f"ERROR: Unsupported platform: {sys.platform}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
