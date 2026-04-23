"""Tests for claude_usage.themes."""

from __future__ import annotations

import re

import pytest

from claude_usage.themes import THEME_KEYS, THEMES, get_theme


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

EXPECTED_THEMES = {
    "default",
    "catppuccin-mocha",
    "dracula",
    "nord",
    "gruvbox-dark",
    "terminal",
    "dashboard",
    "hud",
    "receipt",
    "strip",
    "brutalist",
}


def test_all_themes_present() -> None:
    """All shipped themes are registered."""
    assert set(THEMES.keys()) == EXPECTED_THEMES


def test_all_themes_share_identical_keys() -> None:
    """Every theme exposes exactly the canonical key set."""
    for name, palette in THEMES.items():
        assert set(palette.keys()) == THEME_KEYS, (
            f"theme {name!r} keys diverge: "
            f"missing={THEME_KEYS - set(palette.keys())!r}, "
            f"extra={set(palette.keys()) - THEME_KEYS!r}"
        )


def test_theme_keys_contains_expected_role_names() -> None:
    """THEME_KEYS matches the documented role names."""
    assert THEME_KEYS == frozenset({
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


@pytest.mark.parametrize("name", sorted(EXPECTED_THEMES))
def test_all_color_values_are_valid_hex(name: str) -> None:
    """Every value is a ``#RRGGBB`` hex string."""
    palette = THEMES[name]
    for key, value in palette.items():
        assert isinstance(value, str), f"{name}.{key} is not a string: {value!r}"
        assert _HEX_RE.match(value), (
            f"{name}.{key} is not a valid 6-digit hex color: {value!r}"
        )


def test_get_theme_returns_known_theme() -> None:
    """get_theme returns the requested palette for a known name."""
    assert get_theme("dracula") == THEMES["dracula"]
    assert get_theme("nord") == THEMES["nord"]


def test_get_theme_falls_back_to_default_for_unknown_name() -> None:
    """Unknown names resolve to the default palette."""
    assert get_theme("does-not-exist") == THEMES["default"]
    assert get_theme("") == THEMES["default"]


def test_get_theme_returns_a_copy() -> None:
    """Mutating the returned dict must not affect THEMES."""
    theme = get_theme("default")
    theme["bg"] = "#000000"
    assert THEMES["default"]["bg"] != "#000000"


def test_default_theme_matches_widget_colors() -> None:
    """The "default" theme preserves the colors used by widget.py."""
    default = THEMES["default"]
    assert default["bg"] == "#1a1a2e"
    assert default["bar_blue"] == "#5B9BD5"
    assert default["bar_track"] == "#333340"
    assert default["text_primary"] == "#e0e0e8"
    assert default["text_secondary"] == "#8a8a9a"
    assert default["text_dim"] == "#555568"
    assert default["text_link"] == "#6BA4D9"
    assert default["separator"] == "#2a2a38"
    assert default["error"] == "#ef4444"
