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
# Constants
# ---------------------------------------------------------------------------
readonly AGENT_LABEL="com.claude-usage-widget"
readonly MAIN_SCRIPT="main.py"
readonly REQUIREMENTS_FILE="requirements-macos.txt"
readonly LOG_FILE="$HOME/Library/Logs/claude-usage-widget.log"
readonly ERR_FILE="$HOME/Library/Logs/claude-usage-widget.err"

# ---------------------------------------------------------------------------
# Helper: print an error message to stderr and exit
# ---------------------------------------------------------------------------
die() {
    printf 'Error: %s\n' "$1" >&2
    exit "${2:-1}"
}

# ---------------------------------------------------------------------------
# Resolve paths
# SCRIPT_DIR: absolute path to the repo root (where main.py lives).
# PLIST_DIR:  standard per-user Launch Agents directory on macOS.
# PLIST_FILE: full path for the plist that launchd will manage.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
PLIST_DIR="$HOME/Library/LaunchAgents"
readonly PLIST_DIR
PLIST_FILE="$PLIST_DIR/${AGENT_LABEL}.plist"
readonly PLIST_FILE

echo "=== Claude Usage Widget -- macOS installer ==="

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

# Verify python3 is available
if ! command -v python3 >/dev/null 2>&1; then
    die "python3 is not installed or not in PATH. Install it with: brew install python3"
fi

# Capture the absolute path to python3 so the plist remains valid even if
# PATH changes in future login sessions.
PYTHON="$(command -v python3)"
readonly PYTHON

# Verify pip3 is available
if ! command -v pip3 >/dev/null 2>&1; then
    die "pip3 is not installed or not in PATH. Install it with: brew install python3"
fi

# Verify main.py exists in the repo directory
if [[ ! -f "$SCRIPT_DIR/$MAIN_SCRIPT" ]]; then
    die "$MAIN_SCRIPT not found in $SCRIPT_DIR. Is this script in the repository root?"
fi

# Verify requirements file exists
if [[ ! -f "$SCRIPT_DIR/$REQUIREMENTS_FILE" ]]; then
    die "$REQUIREMENTS_FILE not found in $SCRIPT_DIR. Is this script in the repository root?"
fi

# ---------------------------------------------------------------------------
# Install Python dependencies
# Uses requirements-macos.txt which lists macOS-specific packages (e.g.
# rumps for the tray icon) instead of the Linux GTK/Ayatana stack.
# The -q flag suppresses verbose pip output.
# ---------------------------------------------------------------------------
echo "Installing Python dependencies..."
if ! pip3 install -q -r "$SCRIPT_DIR/$REQUIREMENTS_FILE"; then
    die "pip3 install failed. Check the output above for details."
fi

# ---------------------------------------------------------------------------
# Create the LaunchAgents directory if it does not already exist
# (It is present by default on standard macOS installs, but may be absent
# in minimal or freshly provisioned environments.)
# ---------------------------------------------------------------------------
if ! mkdir -p "$PLIST_DIR"; then
    die "Failed to create LaunchAgents directory: $PLIST_DIR"
fi

# ---------------------------------------------------------------------------
# Unload any previously loaded version of the agent before writing the new
# plist.  This makes the script safe to run multiple times (idempotent).
# Errors are suppressed because the agent may not be loaded on first run.
# ---------------------------------------------------------------------------
launchctl unload "$PLIST_FILE" 2>/dev/null || true

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
    <string>${AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${SCRIPT_DIR}/${MAIN_SCRIPT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${ERR_FILE}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
EOF

# Verify the plist was written successfully
if [[ ! -f "$PLIST_FILE" ]]; then
    die "Failed to write plist to $PLIST_FILE"
fi

# ---------------------------------------------------------------------------
# Create log files and lock down permissions
# The log files are created explicitly here so chmod can be applied before
# the agent runs.  chmod 600 ensures only the owning user can read the logs,
# which may contain Python tracebacks or sensitive path information.
# ---------------------------------------------------------------------------
if ! mkdir -p "$(dirname "$LOG_FILE")"; then
    die "Failed to create log directory: $(dirname "$LOG_FILE")"
fi
touch "$LOG_FILE" "$ERR_FILE"
chmod 600 "$LOG_FILE" "$ERR_FILE"

# ---------------------------------------------------------------------------
# Load and start the Launch Agent
# ---------------------------------------------------------------------------
if ! launchctl load "$PLIST_FILE"; then
    die "launchctl load failed. Check the plist for errors: $PLIST_FILE"
fi

# ---------------------------------------------------------------------------
# Confirm installation and print helpful next steps
# ---------------------------------------------------------------------------
echo ""
echo "Done! The widget will start automatically on next login."
echo "To start it now: launchctl start $AGENT_LABEL"
echo "To remove:       launchctl unload \"$PLIST_FILE\" && rm \"$PLIST_FILE\""
