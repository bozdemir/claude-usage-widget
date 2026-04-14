#!/bin/bash
# Install Claude Usage Widget as a macOS Launch Agent (autostart on login).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.claude-usage-widget.plist"
PYTHON="$(which python3)"

echo "=== Claude Usage Widget — macOS installer ==="

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -q -r "$SCRIPT_DIR/requirements-macos.txt"

# Create LaunchAgents dir if missing
mkdir -p "$PLIST_DIR"

# Write the plist
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

# Load the agent
launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load "$PLIST_FILE"

echo ""
echo "Done! The widget will start automatically on next login."
echo "To start it now: launchctl start com.claude-usage-widget"
echo "To remove:       launchctl unload $PLIST_FILE && rm $PLIST_FILE"
