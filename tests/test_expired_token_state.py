"""Expired-token state (PR #37, following #36).

When Claude Code's OAuth token has expired the widget keeps the last-known
Claude numbers, and every view must show that they are stale (dimmed rows
plus a "token expired · run claude" hint) instead of painting them like live
data. The widget never refreshes the token itself.

Uses Qt's offscreen platform so the tests run headless on CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from collections import Counter

import pytest
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QApplication

from claude_usage.collector import UsageStats
from claude_usage.overlay import SCALE_MIN, VIEW_MODE_BARS, VIEW_MODE_GAUGE, UsageOverlay
from claude_usage.skins import SKIN_MODULES
from claude_usage.skins._paint import EXPIRED_NOTICE, fit_expired_notice, mono_font
from claude_usage.themes import THEMES

_app = QApplication.instance() or QApplication([])

# One clock for every render, so reset labels can't differ between the two
# renders being compared.
NOW = int(time.time())

VIEWS = [("default", VIEW_MODE_BARS), ("default", VIEW_MODE_GAUGE)] + [
    (name, VIEW_MODE_BARS) for name in sorted(SKIN_MODULES)
]


def _render(theme: str, mode: str, credentials_expired: bool) -> bytes:
    ov = UsageOverlay({"theme": theme})
    ov.set_view_mode(mode)
    ov.update_stats(UsageStats(
        session_utilization=0.24, session_reset=NOW + 3 * 3600,
        weekly_utilization=0.70, weekly_reset=NOW + 71 * 3600,
        credentials_expired=credentials_expired,
    ))
    img = ov.grab().toImage()
    return bytes(img.constBits())


@pytest.mark.parametrize("theme,mode", VIEWS)
def test_every_view_marks_last_known_numbers_as_stale(theme, mode):
    assert _render(theme, mode, True) != _render(theme, mode, False)


def test_notice_keeps_its_hint_when_it_fits():
    fm = QFontMetrics(mono_font(9))
    full = EXPIRED_NOTICE.upper()
    assert fit_expired_notice(fm, fm.horizontalAdvance(full)) == full


def test_notice_falls_back_to_its_headline_beside_a_wide_title():
    fm = QFontMetrics(mono_font(9))
    assert fit_expired_notice(fm, fm.horizontalAdvance("TOKEN EXPIRED")) == "TOKEN EXPIRED"


# --- The hint never paints over the title row's left side -----------------
#
# Views that put the hint on the title row: the classic bars themes and the
# skins with a LIVE slot there. The hint has to stay clear of the title and
# the subagent counter at every scale, down to SCALE_MIN, where fonts stop
# shrinking at their minimum size while the panel keeps narrowing.

TITLE_ROW_VIEWS = [name for name in sorted(THEMES) if name not in SKIN_MODULES] + [
    "brutalist", "dashboard", "hud", "terminal",
]


def _title_row_render(theme: str, scale: float, subagents: int, expired: bool):
    ov = UsageOverlay({"theme": theme, "osd_scale": scale})
    ov.update_stats(UsageStats(
        session_utilization=0.24, session_reset=NOW + 3 * 3600,
        weekly_utilization=0.30, weekly_reset=NOW + 71 * 3600,
        active_subagent_count=subagents, credentials_expired=expired,
    ))
    return ov.grab().toImage()


def _differs(a: int, b: int, tol: int) -> bool:
    ca, cb = QColor(a), QColor(b)
    return max(abs(ca.red() - cb.red()), abs(ca.green() - cb.green()),
               abs(ca.blue() - cb.blue()), abs(ca.alpha() - cb.alpha())) > tol


def _title_band(img, x0: int, x1: int) -> range:
    """The title row: the first run of rows with text on them, skipping
    full-width rules and borders."""
    rows = range(img.height() // 2)
    bg = Counter(img.pixel(x, y) for y in rows for x in range(x0, x1)).most_common(1)[0][0]

    def has_text(y: int) -> bool:
        inked = sum(_differs(img.pixel(x, y), bg, 24) for x in range(x0, x1))
        return 0 < inked < 0.6 * (x1 - x0)

    y = 0
    while y < len(rows) and not has_text(y):
        y += 1
    top = y
    while y < len(rows) and has_text(y):
        y += 1
    return range(top, y), bg


@pytest.mark.parametrize("subagents", [0, 3, 12])
@pytest.mark.parametrize("scale", [SCALE_MIN, 0.7, 0.8, 1.0, 1.5])
@pytest.mark.parametrize("theme", TITLE_ROW_VIEWS)
def test_expired_hint_stays_clear_of_title_and_subagents(theme, scale, subagents):
    live = _title_row_render(theme, scale, subagents, expired=False)
    stale = _title_row_render(theme, scale, subagents, expired=True)
    # Skip the rounded corners.
    x0, x1 = int(16 * scale), live.width() - int(16 * scale)
    band, bg = _title_band(live, x0, x1)
    title_right = max(x for y in band for x in range(x0, x1)
                      if _differs(live.pixel(x, y), bg, 24))
    # With no LIVE badge or burn alert, the hint is all that changes there.
    hint = [x for y in band for x in range(x0, x1)
            if _differs(stale.pixel(x, y), live.pixel(x, y), 40)]
    assert hint, "the hint should be drawn on the title row"
    assert min(hint) > title_right + 2
