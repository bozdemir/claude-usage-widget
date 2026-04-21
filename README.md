# Claude Usage Widget

A desktop widget that displays your Claude Code usage limits in real time. Shows session and weekly utilization percentages fetched from the Anthropic API, with an always-on-top OSD overlay and a system tray / menu bar icon.

![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

## Features

- **Real API data** -- fetches rate-limit utilization from `anthropic-ratelimit-unified-*` response headers
- **OSD overlay** -- transparent, borderless widget in the corner of your screen showing session and weekly usage bars with reset countdowns
- **System tray / menu bar** -- quick-glance usage info and a detailed popup window
- **Cross-platform** -- native GTK3 on Linux, native AppKit/rumps on macOS
- **Auto-refresh** -- updates every 30 seconds (configurable)
- **Resizable** -- scroll wheel to scale the OSD up or down (0.6x--2.0x)
- **Opacity control** -- adjustable OSD transparency via the tray / menu bar
- **Draggable** -- left-click and drag to reposition the OSD
- **Minimizable** -- right-click the OSD to collapse it to a thin progress bar
- **Active sessions** -- shows running Claude Code sessions with project paths and durations
- **Cost estimation** -- widget shows estimated $ spent today and cache savings using model pricing
- **Usage forecasting** -- burn rate calculation shows "at this rate you'll hit the limit in Xh Ym"
- **Per-project breakdown** -- top 5 projects by token usage today
- **Themes** -- 5 built-in themes (default, catppuccin-mocha, dracula, nord, gruvbox-dark), set via `"theme": "dracula"` in `config.json`

## Requirements

- Python 3.10+
- Claude Code CLI installed and authenticated (OAuth)

### Linux

- GTK3, python3-gi, python3-gi-cairo, python3-cairo
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

# 4. Autostart on login (optional) -- installs a Launch Agent
./install-macos.sh
```

## Usage

### OSD Overlay Controls

| Action | Effect |
|--------|--------|
| **Scroll up / down** | Resize (0.6x--2.0x) |
| **Left-click drag** | Move the OSD |
| **Right-click** | Minimize / restore |

### System Tray / Menu Bar

- **Session / Weekly** -- current usage percentages
- **Details...** -- opens a detailed popup with usage bars and active sessions
- **Refresh** -- force an immediate data refresh
- **OSD Overlay** -- toggle the OSD on or off
- **OSD Opacity** -- set OSD transparency (100% / 75% / 50% / 25%)
- **Quit** -- exit the widget

## Configuration

All settings are optional. Copy `config.json.example` to `config.json` and edit the values you want to change:

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
| `refresh_seconds` | `30` | How often to fetch new data from the API (seconds) |
| `osd_opacity` | `0.75` | OSD background opacity (0.15--1.0) |
| `osd_scale` | `1.0` | OSD scale factor (0.6--2.0) |
| `daily_message_limit` | `200` | Daily message limit for local tracking in the popup |
| `weekly_message_limit` | `1000` | Weekly message limit for local tracking in the popup |
| `daily_token_limit` | `5000000` | Daily token limit for local tracking |
| `weekly_token_limit` | `25000000` | Weekly token limit for local tracking |
| `claude_dir` | `~/.claude` | Path to the Claude Code data directory |
| `theme` | `default` | Color theme for the OSD and popup. One of `default`, `catppuccin-mocha`, `dracula`, `nord`, `gruvbox-dark` |

Keys omitted from `config.json` fall back to built-in defaults. `claude_dir` is not included in the example file because the default is correct for most setups.

## Themes

The widget ships with 5 built-in color themes. Select one by adding `"theme": "<name>"` to your `config.json`:

```json
{
    "theme": "dracula"
}
```

Available themes:

- **default** -- the original widget palette _(screenshots welcome)_
- **catppuccin-mocha** -- soft pastel dark theme _(screenshots welcome)_
- **dracula** -- classic purple-and-pink dark theme _(screenshots welcome)_
- **nord** -- cool arctic blue palette _(screenshots welcome)_
- **gruvbox-dark** -- warm retro-style dark theme _(screenshots welcome)_

## How It Works

The widget reads your Claude Code OAuth credentials from `~/.claude/.credentials.json` (Linux) or the macOS Keychain and makes a minimal API call (`max_tokens=1` to `claude-haiku-4-5-20251001`) to read the rate-limit response headers:

```
anthropic-ratelimit-unified-5h-utilization: 0.58
anthropic-ratelimit-unified-5h-reset: 1776186000
anthropic-ratelimit-unified-7d-utilization: 0.10
anthropic-ratelimit-unified-7d-reset: 1776690000
```

These are the same values shown on the [claude.ai usage page](https://claude.ai/settings/usage). The widget also reads local data from `~/.claude/` for message counts, token usage per model, and active session tracking.

### How the OSD Works

The OSD is a transparent, borderless window rendered entirely via 2D drawing primitives:

- **Linux** -- a `Gtk.Window` with the `NOTIFICATION` type hint uses Cairo to draw rounded rectangles, progress bars, and text onto an RGBA surface. The compositor handles transparency; `set_accept_focus(False)` prevents the overlay from stealing keyboard focus.
- **macOS** -- an `NSWindow` at `NSFloatingWindowLevel` with `NSWindowStyleMaskBorderless` and a transparent `NSView` subclass does the equivalent drawing via AppKit (`NSBezierPath`, `NSColor`, `NSAttributedString`).

**Scale and opacity** -- Both platforms store a float `scale` (0.6--2.0, default 1.0) and `opacity` (0.15--1.0, default 0.75) that are applied at draw time. Scale multiplies every pixel dimension (padding, font size, bar height, window size) before drawing, so the entire widget resizes proportionally without re-layout. Opacity is used as the alpha channel of the background fill; bar and text elements are drawn at full alpha on top so they remain legible at low opacity.

**Refresh cycle** -- A background thread wakes every `refresh_seconds` (default 30), makes an API call, and posts the result back to the main thread via `GLib.idle_add` (Linux) or a `rumps.Timer`-drained queue (macOS). The main thread then invalidates the OSD window, triggering a synchronous redraw. User interactions (scroll to resize, drag to move, right-click to minimize) update scale and position in place and queue an immediate redraw without waiting for the next refresh tick.

## Troubleshooting

### Linux: OSD not visible
- Ensure XWayland is available. The widget forces `GDK_BACKEND=x11` for reliable borderless windows.
- Check if the process is running: `ps aux | grep main.py`

### Linux: no system tray icon
- Install `gir1.2-ayatanaappindicator3-0.1`.
- On GNOME, you may need the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/).

### Linux: Cairo errors (`Couldn't find foreign struct converter`)
- Install `python3-gi-cairo`: `sudo apt install python3-gi-cairo`

### macOS: no menu bar icon
- Make sure `rumps` is installed: `pip3 install rumps`
- If using a virtualenv, ensure `pyobjc-framework-Cocoa` is also installed.

### API authentication fails
- Make sure the Claude Code CLI is installed and you are logged in (the `claude` command should work).
- Linux: the OAuth token is read from `~/.claude/.credentials.json`.
- macOS: the OAuth token is read from the Keychain, with a fallback to `~/.claude/.credentials.json`.

## Contributing

Contributions are welcome. A few guidelines:

- **Bug reports** -- open an issue with your OS, Python version, and the full error output. If the OSD is invisible, include `xrandr` or `system_profiler SPDisplaysDataType` output.
- **Pull requests** -- keep changes focused. One fix or feature per PR. Run the widget manually on the target platform before submitting.
- **Platform parity** -- features that affect the OSD or tray should work on both Linux and macOS, or be clearly gated behind a platform check.
- **No new dependencies** -- avoid adding Python packages beyond those already in `requirements-macos.txt` and the listed GTK stack. If a dependency is truly necessary, discuss it in an issue first.
- **Code style** -- follow the existing conventions. No formatter is enforced; just match the surrounding code.

## License

MIT
