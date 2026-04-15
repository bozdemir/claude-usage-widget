#!/usr/bin/env python3
"""Claude Usage Desktop Widget — system tray app for Claude Code usage tracking."""

import sys

if sys.version_info < (3, 10):
    print("ERROR: Python 3.10+ is required (collector.py uses str|None union syntax).", file=sys.stderr)
    sys.exit(1)

import os
import signal

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")
# Fall back to the bundled example config when the user has not created their own.
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
    import glob as _glob

    # GDK_BACKEND=x11 forces GTK to run through XWayland instead of the native
    # Wayland backend.  The native Wayland backend does not support the
    # override-redirect / type-hint tricks that GTK3 uses to create borderless,
    # click-through OSD windows, so we need X11 semantics even on Wayland
    # compositors.  setdefault() is used so a caller can still override this
    # explicitly from the environment before launching the process.
    os.environ.setdefault("GDK_BACKEND", "x11")

    # gi-cairo (the C extension that bridges GObject Introspection and the Cairo
    # graphics library) is needed to draw the transparent OSD overlay.  It ships
    # as a separate package from python3-gi on most distros, so it may be absent.
    #
    # gi.require_foreign("cairo") is the canonical way to test for it: it
    # succeeds silently when gi-cairo is importable and raises an exception when
    # the native Cairo typelib is not registered in the GI repository.
    import importlib.util
    import gi
    try:
        gi.require_foreign("cairo")
    except (ImportError, Exception):
        # gi-cairo is not available via the normal import path.  On Ubuntu/GNOME
        # systems the snap package for the GNOME runtime ships its own copy of
        # _gi_cairo.cpython-<ver>-linux-gnu.so buried inside the snap mount at
        # /snap/gnome-<revision>/*/usr/lib/python3/dist-packages/gi/.  We
        # manually load that .so into sys.modules under the canonical module name
        # "gi._gi_cairo" so the rest of the gi stack can find it transparently.
        loaded = False
        # Build the version tag that CPython embeds in extension filenames, e.g.
        # "312" for Python 3.12, to match the correct snap .so without guessing.
        ver = f"{sys.version_info.major}{sys.version_info.minor}"
        # Glob across all installed snap revisions (the '*' in gnome-*) and
        # sort in reverse order so the highest (newest) revision is tried first.
        for snap_so in sorted(_glob.glob(
            f"/snap/gnome-*/*/usr/lib/python3/dist-packages/gi/_gi_cairo.cpython-{ver}*.so"
        ), reverse=True):
            try:
                # Use importlib's low-level API to load an arbitrary .so path
                # as a named module, bypassing the normal sys.path machinery.
                spec = importlib.util.spec_from_file_location("gi._gi_cairo", snap_so)
                mod = importlib.util.module_from_spec(spec)
                # Register the module before exec so any internal self-references
                # inside the extension can resolve to the same object.
                sys.modules["gi._gi_cairo"] = mod
                spec.loader.exec_module(mod)
                loaded = True
                break  # Stop at the first snap revision that loads cleanly.
            except Exception:
                continue
        if not loaded:
            # Neither system gi-cairo nor any snap fallback worked.  The OSD
            # overlay will likely fail to render, but we continue anyway so the
            # tray icon and menu still function.
            print(
                "WARNING: python3-gi-cairo not found. OSD overlay may not render.\n"
                "Install it with:\n"
                "  Ubuntu/Debian: sudo apt install python3-gi-cairo\n"
                "  Fedora:        sudo dnf install python3-gobject-cairo\n"
                "  Arch:          sudo pacman -S python-gobject\n",
                file=sys.stderr,
            )

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    from claude_usage.config import load_config
    from claude_usage.widget import ClaudeUsageTray

    config = load_config(CONFIG_PATH)
    _tray = ClaudeUsageTray(config)
    Gtk.main()


def main():
    # Restore the default SIGINT handler so Ctrl-C kills the process cleanly.
    # Python replaces it with a KeyboardInterrupt-raising handler by default,
    # but GTK's main loop can suppress that, leaving no way to quit from the
    # terminal without this line.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Route to the correct platform implementation.  Each backend wraps a
    # different GUI toolkit: AppKit/rumps on macOS, GTK3/AppIndicator on Linux.
    # Other platforms (Windows, etc.) are not supported.
    if sys.platform == "darwin":
        _main_macos()
    elif sys.platform.startswith("linux"):
        _main_linux()
    else:
        print(f"ERROR: Unsupported platform: {sys.platform}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
