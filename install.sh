#!/bin/bash
# install.sh — Install desktop autostart entry for Claude Usage Widget

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"

# Check dependencies
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

mkdir -p "$AUTOSTART_DIR"

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

echo "Installed to $AUTOSTART_DIR/claude-usage.desktop"
echo ""
echo "Start now:  python3 $SCRIPT_DIR/main.py &"
echo "Uninstall:  rm $AUTOSTART_DIR/claude-usage.desktop"
