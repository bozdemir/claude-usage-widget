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

import pytest
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from claude_usage.collector import UsageStats
from claude_usage.overlay import VIEW_MODE_BARS, VIEW_MODE_GAUGE, UsageOverlay
from claude_usage.skins import SKIN_MODULES
from claude_usage.skins._paint import EXPIRED_NOTICE, fit_expired_notice, mono_font

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
