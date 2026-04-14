#!/usr/bin/env python3
"""Claude Usage Desktop Widget — system tray app for Claude Code usage tracking."""

import os
import signal
import sys

# Force XWayland for reliable borderless windows on Wayland compositors.
os.environ.setdefault("GDK_BACKEND", "x11")

# Ensure gi-cairo is available (needed for transparent OSD overlay).
# python3-gi-cairo must be installed; print a clear message if missing.
def _check_gi_cairo():
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

_check_gi_cairo()

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from claude_usage.config import load_config
from claude_usage.widget import ClaudeUsageTray

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")
if not os.path.isfile(CONFIG_PATH):
    CONFIG_PATH = os.path.join(_BASE_DIR, "config.json.example")


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    config = load_config(CONFIG_PATH)
    tray = ClaudeUsageTray(config)
    Gtk.main()


if __name__ == "__main__":
    main()
