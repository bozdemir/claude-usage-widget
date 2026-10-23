"""The minimized OSD: a thin capsule showing session utilisation.

Issue #34: on a dark desktop panel the capsule's dark track vanished, so at
a low session % the widget was all but invisible. Its outline must reach the
WCAG 1.4.11 non-text contrast of 3:1 against both a dark and a light panel,
in every theme.

Uses Qt's offscreen platform so the tests run headless on CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from claude_usage.collector import UsageStats
from claude_usage.overlay import UsageOverlay
from claude_usage.themes import THEMES

_app = QApplication.instance() or QApplication([])

# Sampled from the dark KDE panel in issue #34's screenshots; the light one
# is Breeze's default panel.
DARK_PANEL = "#1b2330"
LIGHT_PANEL = "#eff0f1"


def _luminance(c: QColor) -> float:
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.redF()) + 0.7152 * lin(c.greenF()) + 0.0722 * lin(c.blueF())


def _contrast(a: QColor, b: QColor) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _minimized(theme: str, **stats) -> UsageOverlay:
    ov = UsageOverlay({"theme": theme})
    ov.update_stats(UsageStats(**stats))
    ov.toggle_minimized()
    return ov


def _best_contrast_on(panel_hex: str, ov: UsageOverlay) -> float:
    """Highest contrast any capsule pixel reaches against *panel_hex*."""
    grab = ov.grab().toImage()
    img = QImage(grab.size(), QImage.Format_ARGB32)
    panel = QColor(panel_hex)
    img.fill(panel)
    p = QPainter(img)
    p.drawImage(0, 0, grab)
    p.end()
    return max(
        _contrast(QColor(img.pixel(x, y)), panel)
        for x in range(img.width()) for y in range(img.height())
    )


@pytest.mark.parametrize("panel", [DARK_PANEL, LIGHT_PANEL])
@pytest.mark.parametrize("theme", sorted(THEMES))
def test_empty_capsule_stands_out_from_the_panel(theme, panel):
    # 0% session: no fill, so only the track and its outline can show it.
    ov = _minimized(theme, session_utilization=0.0)
    assert _best_contrast_on(panel, ov) >= 3.0
