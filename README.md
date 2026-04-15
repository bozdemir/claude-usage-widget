# Claude Usage Widget

A desktop widget that displays your Claude Code usage limits in real-time. Shows session and weekly utilization percentages fetched directly from the Anthropic API, with an always-on-top OSD overlay and a system tray icon.

![OSD Overlay](https://img.shields.io/badge/desktop-OSD_overlay-blue)
![System Tray](https://img.shields.io/badge/system-tray_icon-green)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)

## Features

- **Real API data** — Fetches actual rate limit utilization from `anthropic-ratelimit-unified-*` response headers
- **OSD overlay** — Transparent, borderless widget in the corner of your screen showing session and weekly usage bars with reset countdowns
- **System tray** — Quick-glance usage info and a detailed popup window
- **Auto-refresh** — Updates every 30 seconds (configurable)
- **Resizable** — Scroll wheel to scale the OSD up/down
- **Opacity control** — Adjustable OSD transparency via tray menu
- **Draggable** — Left-click and drag to reposition the OSD
- **Minimizable** — Right-click OSD to collapse to a thin progress bar
- **Active sessions** — Shows running Claude Code sessions with project paths and durations

## Requirements

- Linux with X11 or XWayland (KDE Plasma, GNOME, etc.)
- Python 3.10+
- GTK 3
- System packages:
  - `gir1.2-ayatanaappindicator3-0.1` (system tray)
  - `python3-gi` (GTK bindings)
  - `python3-gi-cairo` (cairo integration for transparent OSD)
  - `python3-cairo` (pycairo)
- Claude Code CLI installed and authenticated (OAuth)

## Installation

### 1. Install system dependencies

```bash
# Ubuntu/Debian
sudo apt install python3-gi python3-gi-cairo python3-cairo gir1.2-ayatanaappindicator3-0.1

# Fedora
sudo dnf install python3-gobject python3-cairo gtk3

# Arch
sudo pacman -S python-gobject python-cairo gtk3 libappindicator-gtk3
```

### 2. Clone and run

```bash
git clone https://github.com/bozdemir/claude-usage-widget.git
cd claude-usage-widget
python3 main.py &
```

### 3. Autostart on login (optional)

```bash
./install.sh
```

This copies a `.desktop` file to `~/.config/autostart/` so the widget starts automatically on login.

## Usage

### OSD Overlay Controls

| Action | Effect |
|--------|--------|
| **Scroll up/down** | Resize (scale 0.6x - 2.0x) |
| **Left-click drag** | Move the OSD |
| **Right-click** | Minimize / Restore |

### System Tray Menu

- **Session / Weekly** — Current usage percentages
- **Details...** — Opens detailed popup with usage bars, model breakdown, active sessions
- **Refresh** — Force immediate data refresh
- **OSD Overlay** — Toggle the OSD on/off
- **OSD Opacity** — Set OSD transparency (100% / 75% / 50% / 25%)
- **Quit** — Exit the widget

## Configuration

Copy `config.json.example` to `config.json` and edit:

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

## How It Works

The widget reads your Claude Code OAuth credentials from `~/.claude/.credentials.json` and makes a minimal API call (1 token to `claude-haiku`) to read the rate limit response headers:

```
anthropic-ratelimit-unified-5h-utilization: 0.58
anthropic-ratelimit-unified-5h-reset: 1776186000
anthropic-ratelimit-unified-7d-utilization: 0.10
anthropic-ratelimit-unified-7d-reset: 1776690000
```

These are the same values shown on the [claude.ai usage page](https://claude.ai/settings/usage). The widget also reads local data from `~/.claude/` for message counts, token usage per model, and active session tracking.

## Troubleshooting

### OSD not visible
- Make sure XWayland is available (the widget forces `GDK_BACKEND=x11` for reliable borderless windows)
- Check if the process is running: `ps aux | grep main.py`

### No system tray icon
- Install `gir1.2-ayatanaappindicator3-0.1`
- On GNOME, you may need the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/)

### Cairo errors (`Couldn't find foreign struct converter`)
- Install `python3-gi-cairo`
- The widget includes a fallback that loads the module from GNOME snap packages if the system package is missing

### API authentication fails
- Make sure Claude Code CLI is installed and you're logged in (`claude` command works)
- OAuth token is read from `~/.claude/.credentials.json`

## License

MIT
