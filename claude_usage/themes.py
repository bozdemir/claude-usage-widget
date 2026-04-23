"""Theme presets for the Claude Usage Widget.

Each theme is a flat dict of hex color strings with an identical set of keys.
The canonical key set is :data:`THEME_KEYS`.

Public API:
    THEMES      -- mapping of theme name (str) -> color dict
    THEME_KEYS  -- frozenset of the canonical keys every theme must provide
    get_theme() -- look up a theme by name, falling back to "default"

Keys and their intended roles:
    bg             -- window / panel background
    bar_blue       -- progress-bar fill (primary accent)
    bar_track      -- progress-bar empty track
    text_primary   -- headings and primary labels
    text_secondary -- subtitles and supporting info
    text_dim       -- timestamps and low-priority text
    text_link      -- links / active-session paths
    separator      -- horizontal rules and dividers
    warn           -- warning notices (e.g. approaching limits)
    crit           -- critical notices (e.g. over budget)
    error          -- error text (e.g. API / collection failures)
    live_indicator -- "● LIVE" dot + text on the OSD while a session is running
"""

from __future__ import annotations

from typing import Dict, Mapping

# Canonical set of keys every theme must provide.
THEME_KEYS: frozenset[str] = frozenset({
    "bg",
    "bar_blue",
    "bar_track",
    "text_primary",
    "text_secondary",
    "text_dim",
    "text_link",
    "separator",
    "warn",
    "crit",
    "error",
    "live_indicator",
})


# --- Theme presets ---------------------------------------------------------

# 1. Default — extracted from claude_usage/widget.py.
_DEFAULT: Dict[str, str] = {
    "bg":             "#1a1a2e",
    "bar_blue":       "#5B9BD5",
    "bar_track":      "#333340",
    "text_primary":   "#e0e0e8",
    "text_secondary": "#8a8a9a",
    "text_dim":       "#555568",
    "text_link":      "#6BA4D9",
    "separator":      "#2a2a38",
    "warn":           "#f59e0b",  # amber — matches tray icon warn gradient
    "crit":           "#dc2626",  # strong red
    "error":          "#ef4444",  # vivid red — matches existing .error-text CSS
    "live_indicator": "#4ade80",  # emerald — reads as "running" against dark bg
}

# 2. Catppuccin Mocha — https://catppuccin.com/palette/
#    base/blue/surface0/text/subtext0/overlay0/sapphire/surface1/peach/red/maroon
_CATPPUCCIN_MOCHA: Dict[str, str] = {
    "bg":             "#1e1e2e",  # base
    "bar_blue":       "#89b4fa",  # blue
    "bar_track":      "#313244",  # surface0
    "text_primary":   "#cdd6f4",  # text
    "text_secondary": "#a6adc8",  # subtext0
    "text_dim":       "#6c7086",  # overlay0
    "text_link":      "#74c7ec",  # sapphire
    "separator":      "#45475a",  # surface1
    "warn":           "#fab387",  # peach
    "crit":           "#f38ba8",  # red
    "error":          "#eba0ac",  # maroon
    "live_indicator": "#a6e3a1",  # green
}

# 3. Dracula — https://draculatheme.com/contribute
#    background/purple/current line/foreground/comment/selection/cyan/orange/red/pink
_DRACULA: Dict[str, str] = {
    "bg":             "#282a36",  # background
    "bar_blue":       "#bd93f9",  # purple (primary accent in Dracula)
    "bar_track":      "#44475a",  # current line
    "text_primary":   "#f8f8f2",  # foreground
    "text_secondary": "#bfbfbf",  # lighter foreground-ish
    "text_dim":       "#6272a4",  # comment
    "text_link":      "#8be9fd",  # cyan
    "separator":      "#44475a",  # selection / current line
    "warn":           "#ffb86c",  # orange
    "crit":           "#ff5555",  # red
    "error":          "#ff79c6",  # pink — reserved for hard errors
    "live_indicator": "#50fa7b",  # green
}

# 4. Nord — https://www.nordtheme.com/docs/colors-and-palettes
#    nord0/nord8/nord1/nord6/nord4/nord3/nord9/nord2/nord13/nord11/nord12
_NORD: Dict[str, str] = {
    "bg":             "#2e3440",  # nord0
    "bar_blue":       "#88c0d0",  # nord8 (frost)
    "bar_track":      "#3b4252",  # nord1
    "text_primary":   "#eceff4",  # nord6
    "text_secondary": "#d8dee9",  # nord4
    "text_dim":       "#4c566a",  # nord3
    "text_link":      "#81a1c1",  # nord9
    "separator":      "#434c5e",  # nord2
    "warn":           "#ebcb8b",  # nord13 (aurora yellow)
    "crit":           "#bf616a",  # nord11 (aurora red)
    "error":          "#d08770",  # nord12 (aurora orange)
    "live_indicator": "#a3be8c",  # nord14 (aurora green)
}

# 5. Gruvbox Dark — https://github.com/morhetz/gruvbox
#    bg0/blue bright/bg1/fg1/fg3/gray/aqua/bg2/yellow/red/orange (bright variants)
_GRUVBOX_DARK: Dict[str, str] = {
    "bg":             "#282828",  # bg0
    "bar_blue":       "#83a598",  # bright blue
    "bar_track":      "#3c3836",  # bg1
    "text_primary":   "#ebdbb2",  # fg1
    "text_secondary": "#bdae93",  # fg3
    "text_dim":       "#928374",  # gray
    "text_link":      "#8ec07c",  # bright aqua
    "separator":      "#504945",  # bg2
    "warn":           "#fabd2f",  # bright yellow
    "crit":           "#fb4934",  # bright red
    "error":          "#fe8019",  # bright orange
    "live_indicator": "#b8bb26",  # bright green
}


THEMES: Dict[str, Dict[str, str]] = {
    "default":          _DEFAULT,
    "catppuccin-mocha": _CATPPUCCIN_MOCHA,
    "dracula":          _DRACULA,
    "nord":             _NORD,
    "gruvbox-dark":     _GRUVBOX_DARK,
}


def get_theme(name: str) -> Dict[str, str]:
    """Return the color dict for *name*, falling back to ``"default"``.

    The returned dict is a fresh copy, so callers may mutate it freely
    without affecting the shared :data:`THEMES` registry.
    """
    theme: Mapping[str, str] = THEMES.get(name, THEMES["default"])
    return dict(theme)


__all__ = ["THEMES", "THEME_KEYS", "get_theme"]
