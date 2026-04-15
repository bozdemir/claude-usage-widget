# Claude Usage Widget

A desktop widget that displays your Claude Code usage limits in real-time. Shows session and weekly utilization percentages fetched directly from the Anthropic API, with an always-on-top OSD overlay and a system tray / menu bar icon.

![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

## Features

- **Real API data** — Fetches actual rate limit utilization from `anthropic-ratelimit-unified-*` response headers
- **OSD overlay** — Transparent, borderless widget in the corner of your screen showing session and weekly usage bars with reset countdowns
- **System tray / Menu bar** — Quick-glance usage info and a detailed popup window
- **Cross-platform** — Native GTK3 on Linux, native AppKit/rumps on macOS
- **Auto-refresh** — Updates every 30 seconds (configurable)
- **Resizable** — Scroll wheel to scale the OSD up/down
- **Opacity control** — Adjustable OSD transparency via tray/menu bar
- **Draggable** — Left-click and drag to reposition the OSD
- **Minimizable** — Right-click OSD to collapse to a thin progress bar
- **Active sessions** — Shows running Claude Code sessions with project paths and durations

## Requirements

- Python 3.10+
- Claude Code CLI installed and authenticated (OAuth)

### Linux

- GTK 3, python3-gi, python3-gi-cairo, python3-cairo
- `gir1.2-ayatanaappindicator3-0.1` (system tray)

### macOS

- `rumps` and `pyobjc-framework-Cocoa` (installed automatically via `requirements-macos.txt`)

## Installation

### Linux

```bash
# 1. Install system dependencies (Ubuntu/Debian)
sudo apt install python3-gi python3-gi-cairo python3-cairo gir1.2-ayatanaappindicator3-0.1

# Fedora
sudo dnf install python3-gobject python3-gobject-cairo python3-cairo gtk3

# Arch
sudo pacman -S python-gobject python-cairo gtk3 libappindicator-gtk3

# 2. Clone and run
git clone https://github.com/bozdemir/claude-usage-widget.git
cd claude-usage-widget
python3 main.py &

# 3. Autostart on login (optional)
./install.sh
```

### macOS

```bash
# 1. Clone
git clone https://github.com/bozdemir/claude-usage-widget.git
cd claude-usage-widget

# 2. Install Python dependencies
pip3 install -r requirements-macos.txt

# 3. Run
python3 main.py

# 4. Autostart on login (optional) — installs a Launch Agent
./install-macos.sh
```

## Usage

### OSD Overlay Controls

| Action | Effect |
|--------|--------|
| **Scroll up/down** | Resize (scale 0.6x - 2.0x) |
| **Left-click drag** | Move the OSD |
| **Right-click** | Minimize / Restore |

### System Tray / Menu Bar

- **Session / Weekly** — Current usage percentages
- **Details...** — Opens detailed popup with usage bars and active sessions
- **Refresh** — Force immediate data refresh
- **OSD Overlay** — Toggle the OSD on/off
- **OSD Opacity** — Set OSD transparency (100% / 75% / 50% / 25%)
- **Quit** — Exit the widget

## Configuration

Copy `config.json.example` to `config.json` and edit:

```bash
cp config.json.example config.json
```

```json
{
    "daily_message_limit": 200,
    "weekly_message_limit": 1000,
    "daily_token_limit": 5000000,
    "weekly_token_limit": 25000000,
    "refresh_seconds": 30,
    "osd_opacity": 0.75,
    "osd_scale": 1.0
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `refresh_seconds` | `30` | How often to fetch new data from API |
| `osd_opacity` | `0.75` | Initial OSD background opacity (0.15 - 1.0) |
| `osd_scale` | `1.0` | Initial OSD scale factor (0.6 - 2.0) |
| `daily_message_limit` | `200` | Used for local message tracking in the popup |
| `weekly_message_limit` | `1000` | Used for local message tracking in the popup |
| `daily_token_limit` | `5000000` | Daily token limit for local tracking |
| `weekly_token_limit` | `25000000` | Weekly token limit for local tracking |
| `claude_dir` | `~/.claude` | Path to Claude Code data directory |

## How It Works

The widget reads your Claude Code OAuth credentials from `~/.claude/.credentials.json` (Linux) or the macOS Keychain and makes a minimal API call (1 token to `claude-haiku`) to read the rate limit response headers:

```
anthropic-ratelimit-unified-5h-utilization: 0.58
anthropic-ratelimit-unified-5h-reset: 1776186000
anthropic-ratelimit-unified-7d-utilization: 0.10
anthropic-ratelimit-unified-7d-reset: 1776690000
```

These are the same values shown on the [claude.ai usage page](https://claude.ai/settings/usage). The widget also reads local data from `~/.claude/` for message counts, token usage per model, and active session tracking.

## Troubleshooting

### Linux: OSD not visible
- Make sure XWayland is available (the widget forces `GDK_BACKEND=x11` for reliable borderless windows)
- Check if the process is running: `ps aux | grep main.py`

### Linux: No system tray icon
- Install `gir1.2-ayatanaappindicator3-0.1`
- On GNOME, you may need the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/)

### Linux: Cairo errors (`Couldn't find foreign struct converter`)
- Install `python3-gi-cairo`: `sudo apt install python3-gi-cairo`

### macOS: No menu bar icon
- Make sure `rumps` is installed: `pip3 install rumps`
- If using a virtualenv, ensure `pyobjc-framework-Cocoa` is also installed

### API authentication fails
- Make sure Claude Code CLI is installed and you're logged in (`claude` command works)
- Linux: OAuth token is read from `~/.claude/.credentials.json`
- macOS: OAuth token is read from Keychain (fallback to `~/.claude/.credentials.json`)

## License

MIT
