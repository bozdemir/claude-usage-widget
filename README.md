# Claude Usage Widget

A cross-platform desktop widget that displays your Claude Code usage limits in real time. Always-on-top OSD overlay showing session and weekly utilization — built with PySide6 (Qt), so a single `pip install` works on Linux, macOS, and Windows.

![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

## Screenshots

<p align="center">
  <img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-default.png" alt="OSD overlay" width="320" /><br/>
  <em>Always-on-top OSD: session + weekly utilisation, reset timers, live token-per-minute badge, subagent counter, and a scrolling per-turn cost ticker along the bottom.</em>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/popup-default.png" alt="Detail popup with usage bars, heatmaps, cost breakdown, and the AI-generated weekly report" width="540" /><br/>
  <em>Click the OSD to open the detail popup: forecasts, 5h/7d sparklines, 90-day heatmap, 52-week GitHub-style calendar, per-model cost breakdown with Anthropic-published rates, top projects, tips, and a Claude-authored weekly summary.</em>
</p>

### OSD view modes

Two layouts, switch with right-click → OSD View ▸. Selection persists to `~/.config/claude-usage/config.json` so a restart keeps it.

<table align="center">
  <tr>
    <td align="center"><b>Bars</b> — default, includes the scrolling ticker</td>
    <td align="center"><b>Gauge</b> — circular rings, car-dashboard vibe</td>
  </tr>
  <tr>
    <td><img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-default.png" alt="bars view" width="300" /></td>
    <td><img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-gauge-default.png" alt="gauge view" width="300" /></td>
  </tr>
</table>

### Themes

Five built-in palettes. Right-click the OSD → Theme ▸ to switch instantly; the choice also persists to `~/.config/claude-usage/config.json`.

<table align="center">
  <tr>
    <td align="center"><b>default</b></td>
    <td align="center"><b>catppuccin-mocha</b></td>
    <td align="center"><b>dracula</b></td>
  </tr>
  <tr>
    <td><img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-default.png" alt="default" width="260" /></td>
    <td><img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-catppuccin-mocha.png" alt="catppuccin-mocha" width="260" /></td>
    <td><img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-dracula.png" alt="dracula" width="260" /></td>
  </tr>
  <tr>
    <td align="center"><b>nord</b></td>
    <td align="center"><b>gruvbox-dark</b></td>
    <td></td>
  </tr>
  <tr>
    <td><img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-nord.png" alt="nord" width="260" /></td>
    <td><img src="https://raw.githubusercontent.com/bozdemir/claude-usage-widget/main/screenshots/osd-gruvbox-dark.png" alt="gruvbox-dark" width="260" /></td>
    <td></td>
  </tr>
</table>

Gauge variants for every theme are available at `screenshots/osd-gauge-<theme>.png`.

## Features

- **Single `pip install`** -- no `apt`/`brew`/system libraries required, Qt is bundled
- **Real API data** -- rate-limit utilisation read straight from `anthropic-ratelimit-unified-*` response headers
- **OSD overlay** -- transparent, frameless, always-on-top; left-click opens the details popup, right-click shows a context menu
- **Live token stream** -- `● LIVE 5.3k tok/min` badge on the OSD while a Claude Code session is actively writing, derived from the conversation JSONLs
- **Per-turn cost ticker** -- a scrolling strip at the bottom of the OSD shows the USD cost of each assistant turn as it lands (`$0.156 ← Bash · 116`), colour-coded by quartile within the visible window so the tape always stays visually varied. Toggle via right-click → "Show cost ticker" or set `"show_ticker": false` in `config.json`.
- **Subagent rozet** -- when you spawn parallel subagents via the Task tool, the `CLAUDE` title gets a `⚙ N` counter next to it showing how many are currently writing. Hidden when zero so single-session use isn't cluttered.
- **Detail popup** -- usage bars, forecast, 5h/7d sparklines, 90-day heatmap, 52-week GitHub-style calendar, per-model cost breakdown, top projects, active sessions (resizable)
- **Auto-refresh** -- every 30 seconds by default, fully configurable
- **Resizable** -- scroll wheel on the OSD (0.6x -- 2.0x); drag the popup window edges to widen it
- **Draggable** -- left-click drag on the OSD
- **Cost estimation** -- USD equivalent per model, cache savings, pay-as-you-go comparison for flat-fee subscribers
- **Usage forecasting** -- burn-rate prediction: "At current rate: 2h 30m to limit"
- **Per-project breakdown** -- top 5 projects by token usage today
- **Prompt-cache opportunities** -- scans recent sessions for repeated prompt prefixes and suggests `cache_control` changes with a concrete $ savings estimate
- **AI-generated weekly report** -- Claude Haiku writes a 3-4 sentence summary of your past week of usage (cached 1h; never leaks prompt text)
- **Anomaly detection** -- flags days whose utilisation exceeds the 7/90-day baseline
- **Cost optimisation tips** -- suggests cache-hit-rate improvements and model-mix changes
- **Themes** -- default, catppuccin-mocha, dracula, nord, gruvbox-dark
- **Threshold notifications** -- native desktop notifications on crossing 75% / 90%
- **Webhooks** -- optional POST to Slack / Discord / custom URLs on threshold, daily, or anomaly events
- **Localhost JSON API** -- optional `http://127.0.0.1:8765/usage` for tmux / polybar / waybar integrations (prompt previews redacted at the serialization boundary)
- **CLI mode** -- `--json`, `--field`, `--export csv` for scripts and status bars

## Requirements

- Python 3.10+
- Claude Code CLI installed and authenticated (OAuth) — the widget reads the same token from `~/.claude/.credentials.json` (or macOS Keychain)

## Installation

### Any platform (pip — recommended)

```bash
pip install --user --upgrade claude-usage-widget
claude-usage              # launches the OSD overlay
claude-usage --version    # 0.4.4
```

That's it — no `apt`, no `brew`, no PyGObject, no rumps. PySide6 ships Qt in the wheel, so the widget is fully self-contained.

### macOS (Homebrew — optional)

If you prefer `brew` over `pip`:

```bash
brew tap bozdemir/tap
brew install claude-usage-widget
```

### From source

```bash
git clone https://github.com/bozdemir/claude-usage-widget.git
cd claude-usage-widget
pip install -e .
python3 main.py
```

## Usage

### OSD overlay controls

| Action              | Effect |
|---------------------|--------|
| **Left-click**      | Open the details popup |
| **Left-click drag** | Move the OSD |
| **Right-click**     | Open context menu (Details, Refresh, Opacity, Minimize, Quit) |
| **Scroll up / down**| Resize (0.6x -- 2.0x) |

### Context menu (right-click OSD)

- **Details…** -- open the detail popup
- **Refresh** -- force an immediate data refresh
- **OSD Opacity** -- 100% / 75% / 50% / 25%
- **OSD View ▸** -- switch between **Bars** (default — progress bars + cost ticker) and **Gauge** (two circular rings); auto-persisted
- **Theme ▸** -- pick one of the 5 palettes; the choice persists to `~/.config/claude-usage/config.json` so a restart keeps it
- **Minimize / Restore** -- collapse the OSD to a thin progress strip
- **Show cost ticker** -- toggle the scrolling per-turn cost strip on the OSD
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
| `show_ticker` | `true` | Whether the scrolling per-turn cost ticker is painted at the bottom of the OSD. Toggle at runtime via right-click → "Show cost ticker". |

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

### How the OSD works

Qt's `QWidget` with `FramelessWindowHint | Tool | WindowStaysOnTopHint` plus `WA_TranslucentBackground` gives us a transparent, borderless floating window that behaves identically on X11, XWayland, native Wayland, macOS, and Windows. All drawing goes through `QPainter` (`drawRoundedRect`, `drawText`), so there's a single code path with no platform shims.

**Scale and opacity** -- the overlay stores a `scale` (0.6 -- 2.0, default 1.0) and `opacity` (0.15 -- 1.0, default 0.75). Scale multiplies every pixel dimension before drawing, so the widget resizes proportionally. Opacity is the alpha channel of the background fill only; bar and text remain at full alpha so they stay legible at low opacity.

**Refresh cycle** -- a daemon thread wakes every `refresh_seconds` (default 30), performs the API call, and emits a Qt signal back to the GUI thread (`Signal(object)`). The GUI thread then updates the OSD and the popup together. User interactions (scroll, drag, right-click) update in place and request an immediate repaint.

### Live token stream

The OSD renders a `● LIVE ~5.3k tok/min` badge when a Claude Code session is actively writing. The detector scans `~/.claude/projects/*/*.jsonl` for assistant turns in the last 5 minutes (filtered cheaply by file mtime), sums their `output_tokens`, and divides by the window. The "live" dot only lights up when the newest turn is under 90 seconds old; the rate keeps showing for the full 5-minute window so bursts are visible in context.

### Per-turn cost ticker

A thin scrolling strip along the bottom of the OSD shows the USD cost of each assistant turn as it lands (`$0.156 ← Bash · 116`). The same JSONL scan that powers the live-tokens badge reads `usage.{input, output, cache_read, cache_creation}_tokens` from each unique message (dedup'd by Anthropic's `message.id`) and multiplies by the Anthropic-published rates in `pricing.py`. Multi-tool turns collapse to a compact `Read+2` label. Items are colour-coded by quartile rank within the current 40-item buffer (dim → blue → amber → red), so you always see four tiers regardless of whether you're on Haiku, Sonnet, or Opus — the tape stays meaningful when every turn happens to land in a narrow dollar band. Disable with the right-click menu or `show_ticker: false` in `config.json`.

### Subagent rozet

Right next to the `CLAUDE` title, a `⚙ N` badge shows how many Task-tool subagents are actively writing. Detection is a stat-only glob of `~/.claude/projects/<proj>/<uuid>/subagents/agent-*.jsonl` filtered to files whose mtime is within the last 60 s — no file contents opened, negligible cost on every refresh. The rozet is hidden when the count is zero so single-session users aren't nagged by a permanent `⚙ 0`.

### Prompt-cache opportunities

Scans your recent conversation history for repeated user-prompt prefixes (≥1024 tokens, ≥3 occurrences within the last 7 days) and estimates how much you'd save by enabling Anthropic's ephemeral prompt cache on them (`cache_creation` write once + `cache_read` for the rest). The top 5 are shown in the popup with a $ figure. Prompt previews stay local -- they're redacted from `--json` and the localhost API so raw prompt text never leaves your machine via those surfaces.

### AI-generated weekly report

A 3-4 sentence natural-language summary of the past week (top projects, total volume, cost/model mix) is generated on demand by Claude Haiku 4.5 and cached at `~/.claude/widget-cache/weekly-report.json` for one hour. The generator runs on a background thread so refresh stays synchronous. If the OAuth token is missing or Anthropic is unreachable, the section simply disappears -- no retries, no errors in your face.

### Calendar heatmap (52 weeks × 7 days)

GitHub-style yearly activity grid below the 90-day strip. Rows are weekdays (Sunday at the top), columns are ISO weeks with today anchored in the rightmost column at its real weekday. Cell alpha maps to per-day peak session utilisation.

## Troubleshooting

### OSD not visible
- Check if the process is running: `ps aux | grep claude-usage` (Linux/macOS) or the Task Manager (Windows).
- Try launching from a terminal: `claude-usage` — any startup error prints to stderr.

### Linux: `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`
Qt 6.5+ needs one tiny system library that ships separately from the wheel:
```bash
sudo apt install -y libxcb-cursor0     # Ubuntu/Debian
sudo dnf install -y xcb-util-cursor    # Fedora
sudo pacman -S xcb-util-cursor         # Arch
```

### Linux: notifications don't appear
The widget shoots notifications via `notify-send`. Install it if missing:
```bash
sudo apt install libnotify-bin    # Ubuntu/Debian
sudo dnf install libnotify        # Fedora
sudo pacman -S libnotify          # Arch
```

### API authentication fails
- Make sure the Claude Code CLI is installed and you are logged in (the `claude` command should work in a terminal).
- Linux / Windows: the OAuth token is read from `~/.claude/.credentials.json`.
- macOS: the OAuth token is read from the Keychain, with a fallback to `~/.claude/.credentials.json`.

## Contributing

Contributions are welcome. A few guidelines:

- **Bug reports** — open an issue with your OS, Python version, and the full error output.
- **Pull requests** — keep changes focused. One fix or feature per PR. Run the widget manually before submitting.
- **No new runtime dependencies** — PySide6-Essentials is the only runtime dep. Everything else uses the Python stdlib and platform-native CLIs.
- **Code style** — follow the existing conventions. No formatter is enforced; just match the surrounding code.

## License

MIT
