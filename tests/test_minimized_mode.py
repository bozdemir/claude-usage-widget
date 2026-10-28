"""The minimized OSD: a thin capsule showing session utilisation.

Issue #34: on a dark desktop panel the capsule's dark track vanished, so at
a low session % the widget was all but invisible. Its outline must reach the
WCAG 1.4.11 non-text contrast of 3:1 against both a dark and a light panel,
in every theme.

Issue #35: hovering the minimized capsule shows the numbers it hides, as a
tooltip (the full view already shows them, so it has none).

Issue #38: a capsule dragged next to the clock reopened somewhere else. At
startup the custom position was clamped for the full-size panel, and only
then did the controller restore the minimized state.

Uses Qt's offscreen platform so the tests run headless on CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from datetime import datetime

import pytest
from PySide6.QtCore import Qt
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


def _stats(**extra) -> dict:
    now = int(time.time())
    base = dict(
        session_utilization=0.05, session_reset=now + 2 * 3600 + 10 * 60 + 30,
        weekly_utilization=0.93, weekly_reset=now + 3 * 86400,
    )
    base.update(extra)
    return base


def test_minimized_tooltip_shows_session_and_weekly():
    stats = _stats()
    weekly_reset = datetime.fromtimestamp(stats["weekly_reset"]).strftime("%a %H:%M")
    ov = _minimized("default", **stats)
    assert ov.toolTip() == f"Session: 5% · 2h 10m\nWeekly: 93% · {weekly_reset}"


def test_full_view_has_no_tooltip():
    ov = UsageOverlay({"theme": "default"})
    ov.update_stats(UsageStats(**_stats()))
    assert ov.toolTip() == ""


def test_restoring_the_full_view_clears_the_tooltip():
    ov = _minimized("default", **_stats())
    ov.toggle_minimized()
    assert ov.toolTip() == ""


def test_tooltip_follows_new_stats_while_minimized():
    ov = _minimized("default", **_stats())
    ov.update_stats(UsageStats(**_stats(session_utilization=0.41)))
    assert ov.toolTip().startswith("Session: 41% · ")


def test_tooltip_leads_with_the_expired_token_hint():
    ov = _minimized("default", **_stats(credentials_expired=True))
    lines = ov.toolTip().splitlines()
    assert lines[0] == "token expired · run claude"
    assert lines[1].startswith("Session: 5% · ")


def test_tooltip_lists_scoped_and_codex_rows():
    ov = _minimized("default", **_stats(
        scoped_utilization=0.4, scoped_label="Fable",
        codex_available=True, codex_has_session=False,
        codex_weekly_utilization=0.48,
    ))
    lines = ov.toolTip().splitlines()
    assert [line.split(":")[0] for line in lines] == ["Session", "Weekly", "Fable", "Codex 7d"]
    assert lines[2] == "Fable: 40%"
    assert lines[3] == "Codex 7d: 48%"


def test_tooltip_shows_while_the_osd_is_inactive():
    # The OSD never takes focus, and Qt only shows tooltips for inactive
    # windows with this attribute set, including after a pin toggle
    # re-creates the native window.
    ov = UsageOverlay({"theme": "default"})
    assert ov.testAttribute(Qt.WA_AlwaysShowToolTips)
    ov.set_always_on_top(not ov.is_always_on_top())
    assert ov.testAttribute(Qt.WA_AlwaysShowToolTips)


def _capsule_dropped_at_bottom_right() -> tuple[int, int]:
    """Where a user drags the capsule: down by the clock, flush with the
    bottom of the available screen area."""
    geo = _app.primaryScreen().availableGeometry()
    probe = _minimized("default")
    return (geo.x() + geo.width() - probe.width() - 20,
            geo.y() + geo.height() - probe.height() - 2)


def _restarted_minimized(xy: tuple[int, int]) -> UsageOverlay:
    # The config the controller persisted after the drag, then its startup
    # order: build the overlay, then restore the minimized state.
    ov = UsageOverlay({"theme": "default", "osd_position": "custom",
                       "osd_x": xy[0], "osd_y": xy[1], "osd_minimized": True})
    ov.toggle_minimized()
    return ov


def test_dragged_capsule_reopens_where_it_was_dropped():
    xy = _capsule_dropped_at_bottom_right()
    assert _restarted_minimized(xy).pos().toTuple() == xy


def test_full_view_restored_near_the_bottom_stays_on_screen():
    xy = _capsule_dropped_at_bottom_right()
    ov = _restarted_minimized(xy)
    ov.toggle_minimized()  # back to the full panel
    geo = _app.primaryScreen().availableGeometry()
    assert ov.geometry().bottom() <= geo.bottom()
    ov.toggle_minimized()  # and down to the capsule again
    assert ov.pos().toTuple() == xy
