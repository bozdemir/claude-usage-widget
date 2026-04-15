#!/bin/bash
# =============================================================================
# install.sh — Install Claude Usage Widget autostart entry (Linux)
#
# What it does:
#   Installs a .desktop file into ~/.config/autostart so the Claude Usage
#   Widget tray application launches automatically whenever the user logs
#   into a desktop session (GNOME, KDE, XFCE, etc.).
#
# Prerequisites:
#   - Linux with a freedesktop-compliant desktop environment
#   - python3
#   - python3-gi          (GObject Introspection bindings)
#   - python3-gi-cairo    (Cairo integration for PyGObject)
#   - python3-cairo       (pycairo)
#   - gir1.2-ayatanaappindicator3-0.1  (system tray indicator support)
#
#   Install missing packages with:
#     sudo apt install python3-gi python3-gi-cairo python3-cairo \
#                      gir1.2-ayatanaappindicator3-0.1
#
# Usage:
#   bash install.sh
#
# To start the widget immediately without rebooting:
#   python3 <repo-dir>/main.py &
#
# To uninstall:
#   rm ~/.config/autostart/claude-usage.desktop
# =============================================================================

set -e

# ---------------------------------------------------------------------------
# Resolve paths
# SCRIPT_DIR: absolute path to the directory containing this script (the repo
#             root), used to build the Exec= and Icon= paths in the .desktop
#             file so they remain valid regardless of where the script is run.
# AUTOSTART_DIR: the standard XDG autostart directory for the current user.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"

# ---------------------------------------------------------------------------
# Dependency check
# Each python3 one-liner silently tests for a required library/GI typelib.
# Failures are accumulated in $missing rather than aborting immediately so
# the user sees all missing packages in a single error message.
# ---------------------------------------------------------------------------
missing=""
python3 -c "import gi" 2>/dev/null || missing="$missing python3-gi"
python3 -c "import gi; gi.require_foreign('cairo')" 2>/dev/null || missing="$missing python3-gi-cairo"
python3 -c "import cairo" 2>/dev/null || missing="$missing python3-cairo"
python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1'); from gi.repository import AyatanaAppIndicator3" 2>/dev/null || missing="$missing gir1.2-ayatanaappindicator3-0.1"

if [ -n "$missing" ]; then
    echo "Missing dependencies:$missing"
    echo "Install with: sudo apt install$missing"
    exit 1
fi

# ---------------------------------------------------------------------------
# Create the autostart directory if it does not already exist
# ---------------------------------------------------------------------------
mkdir -p "$AUTOSTART_DIR"

# ---------------------------------------------------------------------------
# Write the .desktop file
# The desktop environment reads this file on login and launches the Exec=
# command.  Key fields:
#   Exec=          — command used to start the widget
#   Icon=          — path to the tray icon shown in app menus
#   Terminal=false — run in the background, no terminal window
#   X-KDE-autostart-after=panel — on KDE, wait for the panel before starting
# ---------------------------------------------------------------------------
cat > "$AUTOSTART_DIR/claude-usage.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Usage Widget
Comment=Claude Code usage tracker
Exec=python3 $SCRIPT_DIR/main.py
Icon=$SCRIPT_DIR/claude_usage/icons/claude-tray.svg
Terminal=false
Categories=Utility;
X-KDE-autostart-after=panel
StartupNotify=false
EOF

# ---------------------------------------------------------------------------
# Confirm installation and print helpful next steps
# ---------------------------------------------------------------------------
echo "Installed to $AUTOSTART_DIR/claude-usage.desktop"
echo ""
echo "Start now:  python3 $SCRIPT_DIR/main.py &"
echo "Uninstall:  rm $AUTOSTART_DIR/claude-usage.desktop"
