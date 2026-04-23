#!/usr/bin/env python3
"""Render OSD + popup screenshots for every theme, offscreen.

Uses Qt's ``offscreen`` platform plugin so nothing actually pops up on the
user's desktop — the widgets render into a memory buffer and we save each
frame with ``QWidget.grab()``.

Run from the repo root:
    .venv/bin/python scripts/gen_screenshots.py

Outputs: ``screenshots/osd-<theme>.png`` and ``screenshots/popup-<theme>.png``
for every theme in :mod:`claude_usage.themes`.
"""

from __future__ import annotations

import os
import sys

# Must be set before QApplication construction.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Make the package importable when running from the repo root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from claude_usage.collector import collect_all
from claude_usage.config import load_config
from claude_usage.overlay import (
    VIEW_MODE_BARS,
    VIEW_MODE_GAUGE,
    UsageOverlay,
)
from claude_usage.themes import THEMES
from claude_usage.ticker import TickerItem
from claude_usage.skins import SKIN_MODULES
from claude_usage.widget import SkinPopupWidget, UsagePopup


OUTPUT_DIR = os.path.join(REPO_ROOT, "screenshots")
POPUP_WIDTH = 540


def _config_path() -> str:
    """Prefer the project's config.json, else fall back to the example."""
    project_cfg = os.path.join(REPO_ROOT, "config.json")
    if os.path.isfile(project_cfg):
        return project_cfg
    return os.path.join(REPO_ROOT, "config.json.example")


def _pump(app: QApplication, ms: int = 50) -> None:
    """Let Qt process pending layout + paint events before we grab."""
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.start(ms)
    while deadline.isActive():
        app.processEvents()


def main() -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    app = QApplication([])
    cfg = load_config(_config_path())

    print("Collecting live stats (may take a few seconds)…")
    stats = collect_all(cfg)

    # Redact anything resembling a real local path so these screenshots are
    # safe to publish in the README. We keep the numerics honest — the point
    # is to show the widget layout, not the user's projects.
    stats.today_by_project = {
        "-home-user-project-alpha": 361_800,
        "-home-user-project-beta": 169_800,
        "-home-user-project-gamma": 95_300,
    }
    # Synthetic active sessions so the new [07] section has rows to show.
    import time as _time
    _now = _time.time()
    stats.active_sessions = [
        {"cwd": "/home/user/project-alpha", "startedAt": int((_now - 47 * 60) * 1000)},
        {"cwd": "/home/user/project-beta",  "startedAt": int((_now - 2 * 3600 - 14 * 60) * 1000)},
    ]
    stats.weekly_report_text = (
        "Productive week — 626k output tokens across three projects, "
        "all on Opus 4.7. Cache is pulling ~5x its own weight; expensive "
        "turns stayed under $0.30 each. Consider shifting light edits to "
        "Sonnet next week for easy savings."
    )
    # Demo ticker items — cover each quartile colour tier so the
    # screenshots actually demonstrate the feature even when the user's
    # real session hasn't produced recent turns.
    demo_now = stats.session_reset or 0
    demo_items = [
        ("Bash",       0.0342, 156),
        ("Read",       0.0891, 412),
        ("Edit",       0.1243, 780),
        ("TaskUpdate", 0.1811, 91),
        ("Write",      0.2054, 2571),
        ("Bash",       0.0527, 208),
        ("",           0.1604, 306),
        ("Read+2",     0.2873, 1840),
    ]
    stats.ticker_items = [
        TickerItem(
            ts=float(demo_now - i * 30),
            msg_id=f"demo_{i}",
            cost_usd=cost,
            tool=tool,
            output_tokens=out,
            model="claude-opus-4-7",
        )
        for i, (tool, cost, out) in enumerate(demo_items)
    ]
    stats.active_subagent_count = 3  # show the ⚙ rozet in the gallery

    for theme_name in sorted(THEMES.keys()):
        # Force opacity=1.0 for screenshots. The transparent default looks
        # great on a real desktop but renders as a grey rectangle on a flat
        # README background.
        tcfg = {**cfg, "theme": theme_name, "show_ticker": True, "osd_opacity": 1.0}
        print(f"  → {theme_name}")

        # Bars view.
        bars_cfg = {**tcfg, "osd_view_mode": VIEW_MODE_BARS}
        overlay = UsageOverlay(bars_cfg)
        overlay.update_stats(stats)
        # Advance the ticker into mid-scroll so the static shot actually
        # shows items on the tape (at offset=0 the items haven't entered
        # the viewport from the right yet).
        overlay._ticker_offset = 260.0
        overlay.show()
        _pump(app)
        overlay.grab().save(
            os.path.join(OUTPUT_DIR, f"osd-{theme_name}.png"), "PNG",
        )
        overlay.close()

        # Gauge view — same stats, different renderer.
        gauge_cfg = {**tcfg, "osd_view_mode": VIEW_MODE_GAUGE}
        gauge = UsageOverlay(gauge_cfg)
        gauge.update_stats(stats)
        gauge.show()
        _pump(app)
        gauge.grab().save(
            os.path.join(OUTPUT_DIR, f"osd-gauge-{theme_name}.png"), "PNG",
        )
        gauge.close()

        popup_path = os.path.join(OUTPUT_DIR, f"popup-{theme_name}.png")
        if theme_name in SKIN_MODULES:
            # Skin themes paint through SkinPopupWidget's paintEvent stack
            # — grab the inner content widget for a chrome-free capture.
            skin_popup = SkinPopupWidget(tcfg)
            skin_popup.update_stats(stats)
            skin_popup.show()
            _pump(app, ms=200)
            skin_popup._content.grab().save(popup_path, "PNG")
            skin_popup.close()
        else:
            popup = UsagePopup(tcfg)
            popup.resize(POPUP_WIDTH, 400)
            popup.update_stats(stats)
            popup.show()
            _pump(app, ms=120)
            content = popup._content
            content.adjustSize()
            _pump(app, ms=80)
            content.grab().save(popup_path, "PNG")
            popup.close()

    print(f"\nSaved to {OUTPUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
