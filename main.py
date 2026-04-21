#!/usr/bin/env python3
"""Claude Usage Desktop Widget -- system tray app for Claude Code usage tracking."""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    print(
        "ERROR: Python 3.10+ is required (collector.py uses str|None union syntax).",
        file=sys.stderr,
    )
    sys.exit(1)

import glob as _glob
import importlib.util
import os
import signal
from types import ModuleType

_BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))

# Fall back to the bundled example config when the user has not created one.
CONFIG_PATH: str = os.path.join(_BASE_DIR, "config.json")
if not os.path.isfile(CONFIG_PATH):
    CONFIG_PATH = os.path.join(_BASE_DIR, "config.json.example")


# ---------------------------------------------------------------------------
# Platform-specific entry points
# ---------------------------------------------------------------------------

def _main_macos() -> None:
    """macOS entry point: uses AppKit/rumps."""
    from claude_usage.config import load_config
    from claude_usage.widget_macos import ClaudeUsageTray

    config = load_config(CONFIG_PATH)
    app = ClaudeUsageTray(config)
    app.run()


def _ensure_gi_cairo() -> None:
    """Ensure gi-cairo is importable, with a snap-based fallback on Linux.

    gi-cairo (the C extension bridging GObject Introspection and Cairo) ships
    as a separate package from ``python3-gi`` on most distros.  If the normal
    import path fails, we probe the GNOME snap runtime for a compatible ``.so``
    and load it manually so the OSD overlay can render.
    """
    import gi  # already available when called from _main_linux

    try:
        gi.require_foreign("cairo")
        return  # system gi-cairo works fine
    except Exception:
        pass

    # Build the version tag CPython embeds in extension filenames (e.g. "312").
    ver: str = f"{sys.version_info.major}{sys.version_info.minor}"

    # Glob across all installed snap revisions; sort descending so the newest
    # revision is tried first.
    snap_paths: list[str] = sorted(
        _glob.glob(
            f"/snap/gnome-*/*/usr/lib/python3/dist-packages/gi/"
            f"_gi_cairo.cpython-{ver}*.so"
        ),
        reverse=True,
    )

    for snap_so in snap_paths:
        try:
            spec = importlib.util.spec_from_file_location("gi._gi_cairo", snap_so)
            if spec is None or spec.loader is None:
                continue
            mod: ModuleType = importlib.util.module_from_spec(spec)
            # Register before exec so internal self-references resolve.
            sys.modules["gi._gi_cairo"] = mod
            spec.loader.exec_module(mod)
            return  # success
        except Exception:
            continue

    # Neither system gi-cairo nor any snap fallback worked.  The OSD overlay
    # will likely fail to render, but the tray icon and menu still function.
    print(
        "WARNING: python3-gi-cairo not found. OSD overlay may not render.\n"
        "Install it with:\n"
        "  Ubuntu/Debian: sudo apt install python3-gi-cairo\n"
        "  Fedora:        sudo dnf install python3-gobject-cairo\n"
        "  Arch:          sudo pacman -S python-gobject\n",
        file=sys.stderr,
    )


def _main_linux() -> None:
    """Linux entry point: uses GTK3/AppIndicator."""
    # Force GTK to use XWayland.  The native Wayland backend does not support
    # the override-redirect / type-hint tricks needed for borderless,
    # click-through OSD windows.  setdefault() lets callers override explicitly.
    os.environ.setdefault("GDK_BACKEND", "x11")

    _ensure_gi_cairo()

    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    from claude_usage.config import load_config
    from claude_usage.widget import ClaudeUsageTray

    config = load_config(CONFIG_PATH)
    _tray = ClaudeUsageTray(config)  # prevent GC; tray owns its own lifecycle
    Gtk.main()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Top-level dispatcher: restore SIGINT and route to the right platform."""
    # CLI flags take precedence over the GUI. run_cli returns -1 when the
    # user did not pass any CLI-specific flag, in which case we fall through
    # to the platform GUI entry point below.
    from claude_usage.cli import run_cli
    rc = run_cli(sys.argv[1:])
    if rc >= 0:
        sys.exit(rc)

    # Restore the default SIGINT handler so Ctrl-C kills the process cleanly.
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
