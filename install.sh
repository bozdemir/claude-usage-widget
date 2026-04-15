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

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
readonly DESKTOP_FILENAME="claude-usage.desktop"
readonly MAIN_SCRIPT="main.py"
readonly ICON_RELPATH="claude_usage/icons/claude-tray.svg"

# ---------------------------------------------------------------------------
# Resolve paths
# SCRIPT_DIR: absolute path to the directory containing this script (the repo
#             root), used to build the Exec= and Icon= paths in the .desktop
#             file so they remain valid regardless of where the script is run.
# AUTOSTART_DIR: the standard XDG autostart directory for the current user.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
readonly AUTOSTART_DIR

# ---------------------------------------------------------------------------
# Helper: print an error message to stderr and exit
# ---------------------------------------------------------------------------
die() {
    printf 'Error: %s\n' "$1" >&2
    exit "${2:-1}"
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

# Verify python3 is available
if ! command -v python3 >/dev/null 2>&1; then
    die "python3 is not installed or not in PATH. Please install Python 3 first."
fi

# Verify main.py exists in the repo directory
if [[ ! -f "$SCRIPT_DIR/$MAIN_SCRIPT" ]]; then
    die "$MAIN_SCRIPT not found in $SCRIPT_DIR. Is this script in the repository root?"
fi

# Verify the icon file exists (non-fatal warning)
if [[ ! -f "$SCRIPT_DIR/$ICON_RELPATH" ]]; then
    printf 'Warning: icon file not found at %s/%s — the .desktop entry will still work but may lack an icon.\n' \
        "$SCRIPT_DIR" "$ICON_RELPATH" >&2
fi

# ---------------------------------------------------------------------------
# Dependency check
# Each python3 one-liner silently tests for a required library/GI typelib.
# Failures are accumulated in the $missing array rather than aborting
# immediately so the user sees all missing packages in a single error message.
# ---------------------------------------------------------------------------
missing=()
python3 -c "import gi" 2>/dev/null \
    || missing+=("python3-gi")
python3 -c "import gi; gi.require_foreign('cairo')" 2>/dev/null \
    || missing+=("python3-gi-cairo")
python3 -c "import cairo" 2>/dev/null \
    || missing+=("python3-cairo")
python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1'); from gi.repository import AyatanaAppIndicator3" 2>/dev/null \
    || missing+=("gir1.2-ayatanaappindicator3-0.1")

if [[ ${#missing[@]} -gt 0 ]]; then
    printf 'Missing dependencies: %s\n' "${missing[*]}"
    printf 'Install with: sudo apt install %s\n' "${missing[*]}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Create the autostart directory if it does not already exist
# ---------------------------------------------------------------------------
if ! mkdir -p "$AUTOSTART_DIR"; then
    die "Failed to create autostart directory: $AUTOSTART_DIR"
fi

# ---------------------------------------------------------------------------
# Write the .desktop file
# The desktop environment reads this file on login and launches the Exec=
# command.  Key fields:
#   Exec=          — command used to start the widget
#   Icon=          — path to the tray icon shown in app menus
#   Terminal=false — run in the background, no terminal window
#   X-KDE-autostart-after=panel — on KDE, wait for the panel before starting
# ---------------------------------------------------------------------------
DESKTOP_FILE="$AUTOSTART_DIR/$DESKTOP_FILENAME"
readonly DESKTOP_FILE

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Usage Widget
Comment=Claude Code usage tracker
Exec=python3 ${SCRIPT_DIR}/main.py
Icon=${SCRIPT_DIR}/${ICON_RELPATH}
Terminal=false
Categories=Utility;
X-KDE-autostart-after=panel
StartupNotify=false
EOF

# Verify the file was written successfully
if [[ ! -f "$DESKTOP_FILE" ]]; then
    die "Failed to write desktop file to $DESKTOP_FILE"
fi

# ---------------------------------------------------------------------------
# Confirm installation and print helpful next steps
# ---------------------------------------------------------------------------
echo "Installed to $DESKTOP_FILE"
echo ""
echo "Start now:  python3 \"$SCRIPT_DIR/main.py\" &"
echo "Uninstall:  rm \"$DESKTOP_FILE\""
