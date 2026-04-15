#!/bin/bash
# =============================================================================
# install-macos.sh — Install Claude Usage Widget as a macOS Launch Agent
#
# What it does:
#   1. Installs the required Python packages from requirements-macos.txt.
#   2. Writes a launchd property-list (plist) to ~/Library/LaunchAgents/ so
#      macOS starts the Claude Usage Widget tray application automatically
#      each time the user logs in.
#   3. Loads the agent immediately with launchctl so it starts right away
#      without requiring a logout/login cycle.
#   4. Creates the log files with restricted permissions (600) to prevent
#      other users from reading error tracebacks.
#
# Prerequisites:
#   - macOS (tested on Monterey and later)
#   - python3 available in PATH (Homebrew or system Python)
#   - pip3 available in PATH
#   - requirements-macos.txt present in the same directory as this script
#
# Usage:
#   bash install-macos.sh
#
# Log files (stdout / stderr from the widget):
#   ~/Library/Logs/claude-usage-widget.log
#   ~/Library/Logs/claude-usage-widget.err
#
# To start the widget manually without waiting for the next login:
#   launchctl start com.claude-usage-widget
#
# To uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.claude-usage-widget.plist
#   rm ~/Library/LaunchAgents/com.claude-usage-widget.plist
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths
# SCRIPT_DIR: absolute path to the repo root (where main.py lives).
# PLIST_DIR:  standard per-user Launch Agents directory on macOS.
# PLIST_FILE: full path for the plist that launchd will manage.
# PYTHON:     absolute path to python3, captured now so the plist remains
#             valid even if PATH changes in future login sessions.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.claude-usage-widget.plist"
PYTHON="$(which python3)"

echo "=== Claude Usage Widget — macOS installer ==="

# ---------------------------------------------------------------------------
# Install Python dependencies
# Uses requirements-macos.txt which lists macOS-specific packages (e.g.
# rumps for the tray icon) instead of the Linux GTK/Ayatana stack.
# The -q flag suppresses verbose pip output.
# ---------------------------------------------------------------------------
echo "Installing Python dependencies..."
pip3 install -q -r "$SCRIPT_DIR/requirements-macos.txt"

# ---------------------------------------------------------------------------
# Create the LaunchAgents directory if it does not already exist
# (It is present by default on standard macOS installs, but may be absent
# in minimal or freshly provisioned environments.)
# ---------------------------------------------------------------------------
mkdir -p "$PLIST_DIR"

# ---------------------------------------------------------------------------
# Write the launchd plist
# Key plist entries:
#   Label            — unique reverse-DNS identifier for the agent
#   ProgramArguments — argv array: [python3, main.py]
#   RunAtLoad        — start the agent as soon as it is loaded (and on login)
#   KeepAlive        — false: launchd will NOT restart the widget if it exits
#   StandardOutPath  — redirect stdout to a log file
#   StandardErrorPath— redirect stderr to a separate error log file
#   EnvironmentVariables/PATH — ensure Homebrew binaries (/opt/homebrew/bin)
#                               and standard locations are on PATH at runtime
# ---------------------------------------------------------------------------
cat > "$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-usage-widget</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_DIR/main.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/claude-usage-widget.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/claude-usage-widget.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
EOF

# ---------------------------------------------------------------------------
# Create log files and lock down permissions
# The log files are created explicitly here so chmod can be applied before
# the agent runs.  chmod 600 ensures only the owning user can read the logs,
# which may contain Python tracebacks or sensitive path information.
# ---------------------------------------------------------------------------
touch "$HOME/Library/Logs/claude-usage-widget.log" "$HOME/Library/Logs/claude-usage-widget.err"
chmod 600 "$HOME/Library/Logs/claude-usage-widget.log" "$HOME/Library/Logs/claude-usage-widget.err"

# ---------------------------------------------------------------------------
# Register and start the Launch Agent
# "launchctl unload" is attempted first (suppressing errors) to cleanly
# remove any previously loaded version of the agent before reloading it.
# This makes the script safe to run on subsequent installs or upgrades.
# ---------------------------------------------------------------------------
launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load "$PLIST_FILE"

# ---------------------------------------------------------------------------
# Confirm installation and print helpful next steps
# ---------------------------------------------------------------------------
echo ""
echo "Done! The widget will start automatically on next login."
echo "To start it now: launchctl start com.claude-usage-widget"
echo "To remove:       launchctl unload $PLIST_FILE && rm $PLIST_FILE"
