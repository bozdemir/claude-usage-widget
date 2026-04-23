"""Detailed popup window + application orchestrator (PySide6).

No system-tray icon: the :class:`ClaudeUsageApp` wires the OSD overlay to a
context menu (right-click) and a detail popup (left-click).  All background
data collection runs in a daemon thread and posts results back to the GUI
via a thread-safe signal.
"""

from __future__ import annotations

import os
import sys
import threading
import warnings
from datetime import datetime
from typing import Any

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from claude_usage.collector import UsageStats, collect_all
from claude_usage.forecast import format_forecast
from claude_usage.notifier import UsageNotifier
from claude_usage.overlay import UsageOverlay, _hex_to_qcolor
from claude_usage.pricing import MODEL_PRICING, calculate_cost
from claude_usage.themes import ThemeStyle, get_style, get_theme


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
POPUP_WIDTH = 520
POPUP_PAD = 24
HEATMAP_HEIGHT = 18
SPARKLINE_HEIGHT = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_tokens(n: int) -> str:
    """Format a token count compactly: ``1234567 -> '1.2M'``, ``5400 -> '5.4K'``."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _short_model_name(model: str) -> str:
    """Strip ``claude-`` prefix and trailing date for compact display."""
    m = model.removeprefix("claude-")
    if len(m) >= 9 and m[-9:-8] == "-" and m[-8:].isdigit():
        m = m[:-9]
    return m


def _prettify_project_name(name: str) -> str:
    """Convert Claude Code's dashed path (``-home-user-proj``) to ``~/proj``.

    Claude Code encodes every non-alphanumeric path component character as
    ``-``. On POSIX ``/home/alice/proj`` becomes ``-home-alice-proj``; on
    Windows ``C:\\Users\\alice\\proj`` becomes ``C--Users-alice-proj``
    (verified against real Claude Code output — see anthropics/claude-code
    issue #46071). We build candidate home-dir encodings for both shapes
    so the pretty form renders correctly on every OS.
    """
    if not name:
        return "?"
    home = os.path.expanduser("~")
    # Both POSIX-style ("/home/alice" → "-home-alice") and Windows-style
    # ("C:\\Users\\alice" → "C--Users-alice") — colons AND backslashes map
    # to dashes.
    home_posix = home.replace("/", "-")
    home_windows = home.replace("\\", "-").replace(":", "-")
    candidates = {home_posix, home_windows}
    for home_dashed in candidates:
        if not home_dashed:
            continue
        if name == home_dashed:
            return "~"
        if name.startswith(home_dashed + "-"):
            return "~/" + name[len(home_dashed) + 1:]
    return name


def _format_reset_duration(reset_ts: int) -> str:
    """``'Resets in 3 hr 28 min'`` / ``'Resets in 45 min'`` / ``''``."""
    if reset_ts <= 0:
        return ""
    remaining = int(reset_ts - datetime.now().timestamp())
    if remaining <= 0:
        return "Resets soon"
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    if hours > 0:
        return f"Resets in {hours} hr {minutes} min"
    return f"Resets in {minutes} min"


def _format_reset_day(reset_ts: int) -> str:
    """``'Resets Mon 04:00 PM'`` / ``''``."""
    if reset_ts <= 0:
        return ""
    return datetime.fromtimestamp(reset_ts).strftime("Resets %a %I:%M %p")


def _format_session_duration(total_seconds: int) -> str:
    hours, rem = divmod(total_seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"


# ---------------------------------------------------------------------------
# Custom-painted atomic widgets
# ---------------------------------------------------------------------------

class _ProgressBar(QWidget):
    """Thin rounded bar, fill colour depends on utilisation."""

    def __init__(self, theme: dict[str, str], height: int = 12) -> None:
        super().__init__()
        self._theme = theme
        self._fraction = 0.0
        self.setFixedHeight(height)

    def set_fraction(self, value: float) -> None:
        self._fraction = max(0.0, min(1.0, float(value)))
        self.update()

    def set_theme(self, theme: dict[str, str]) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        p.setPen(Qt.NoPen)
        p.setBrush(_hex_to_qcolor(self._theme["bar_track"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        if self._fraction > 0:
            fill_w = max(w * self._fraction, h)
            p.setBrush(_hex_to_qcolor(self._theme["bar_blue"]))
            p.drawRoundedRect(QRectF(0, 0, fill_w, h), r, r)


class _Sparkline(QWidget):
    """Vertical-bar sparkline of per-bucket utilisation values."""

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme
        self._buckets: list[float] = []
        self.setFixedHeight(SPARKLINE_HEIGHT)

    def set_buckets(self, buckets: list[float]) -> None:
        self._buckets = list(buckets or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(Qt.NoPen)
        p.setBrush(_hex_to_qcolor(self._theme["bar_track"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), 4, 4)

        if not self._buckets:
            return
        n = len(self._buckets)
        gap = 1.0
        bar_w = max(1.0, (w - (n - 1) * gap) / n)
        fill = _hex_to_qcolor(self._theme["bar_blue"])
        p.setBrush(fill)
        for i, v in enumerate(self._buckets):
            if v <= 0:
                continue
            bx = i * (bar_w + gap)
            bh = max(1.0, h * min(float(v), 1.0))
            p.drawRect(QRectF(bx, h - bh, bar_w, bh))


class _Heatmap(QWidget):
    """Single-row heatmap strip (e.g. 90 daily cells)."""

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme
        self._buckets: list[float] = []
        self.setFixedHeight(HEATMAP_HEIGHT)

    def set_buckets(self, buckets: list[float]) -> None:
        self._buckets = list(buckets or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(_hex_to_qcolor(self._theme["bar_track"]))
        p.drawRect(QRectF(0, 0, w, h))

        n = len(self._buckets)
        if n == 0:
            return
        cell_w = w / n
        base = self._theme["bar_blue"]
        for i, v in enumerate(self._buckets):
            if v <= 0:
                continue
            alpha = max(0.0, min(1.0, float(v)))
            p.setBrush(_hex_to_qcolor(base, alpha))
            p.drawRect(QRectF(i * cell_w, 0, cell_w, h))


def _align_calendar_buckets(
    buckets: list[float],
    today_weekday: int | None = None,
) -> list[float]:
    """Align an oldest-first daily series to a 52×7 GitHub-style grid.

    The column-major grid has row 0 = Sunday and today pinned to the
    bottom-right column at its real weekday. Buckets older than the grid
    can hold are dropped; trailing empties are appended so future days of
    the current week render as blank cells.

    ``today_weekday`` is Python's ``datetime.weekday()`` (Mon=0..Sun=6);
    pass ``None`` to use ``datetime.now()``.
    """
    if today_weekday is None:
        today_weekday = datetime.now().weekday()
    # Convert to Sunday-indexed 0..6 to match GitHub's top-row convention.
    today_row = (today_weekday + 1) % 7
    total = 52 * 7
    trailing = 6 - today_row  # empty cells after today within current week
    usable = total - trailing  # number of real daily cells that fit
    if len(buckets) > usable:
        buckets = buckets[-usable:]
    padded = buckets + [0.0] * trailing
    # Pad the head if we had fewer buckets than usable slots.
    missing_head = total - len(padded)
    if missing_head > 0:
        padded = [0.0] * missing_head + padded
    return padded


class _CalendarHeatmap(QWidget):
    """GitHub-style calendar heatmap: 52 weeks × 7 days of peak utilization."""

    CELL_SIZE = 10
    CELL_GAP = 2
    WEEKS = 52
    DAYS = 7

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme
        self._buckets: list[float] = []
        total_w = self.WEEKS * (self.CELL_SIZE + self.CELL_GAP)
        total_h = self.DAYS * (self.CELL_SIZE + self.CELL_GAP)
        self.setFixedSize(total_w, total_h)

    def set_buckets(self, buckets: list[float]) -> None:
        self._buckets = list(buckets or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        track = _hex_to_qcolor(self._theme["bar_track"])
        base = self._theme["bar_blue"]
        # Draw from oldest (top-left) to newest (bottom-right).  The list is
        # already oldest-first, length WEEKS*DAYS = 364.
        n = len(self._buckets)
        for i in range(self.WEEKS * self.DAYS):
            col = i // self.DAYS
            row = i % self.DAYS
            x = col * (self.CELL_SIZE + self.CELL_GAP)
            y = row * (self.CELL_SIZE + self.CELL_GAP)
            v = self._buckets[i] if i < n else 0.0
            if v > 0:
                alpha = max(0.15, min(1.0, float(v)))
                p.setBrush(_hex_to_qcolor(base, alpha))
            else:
                p.setBrush(track)
            p.drawRect(QRectF(x, y, self.CELL_SIZE, self.CELL_SIZE))


class SkinPopupWidget(QWidget):
    """Full-surface paintEvent popup used when a handoff skin is active.

    Unlike the default :class:`UsagePopup`, this widget doesn't lay out any
    child widgets — the whole window is painted by the skin's
    ``paint_popup(painter, rect, data, scale)`` function. A ``QScrollArea``
    wraps it so tall popups still fit on small screens.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        from claude_usage.skins import SKIN_MODULES
        self._config = config
        self._all_skins = SKIN_MODULES
        self._skin = SKIN_MODULES.get(str(config.get("theme", "")))
        self._data = None
        self._scale = 1.0
        # Phase driver for the pre-data "Loading..." animation. Bumps every
        # tick so dots cycle / arcs sweep while we wait for first collect.
        self._loading_phase = 0.0
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(120)
        self._loading_timer.timeout.connect(self._tick_loading)
        self._loading_timer.start()

        self.setWindowTitle("Claude Usage")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_X11NetWmWindowTypeUtility, True)

        # Inner content widget sized to measure_popup output; wrapped in
        # a scroll area so the window is resizable without losing content.
        self._content = QWidget(self)
        self._content.paintEvent = self._paint_content  # type: ignore[method-assign]
        self._scroll = QScrollArea(self)
        self._scroll.setWidget(self._content)
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._scroll)

        self._apply_scrollbar_style()
        self.resize(540, 360)
        self._resize_content()

    def apply_config(self, config: dict[str, Any]) -> None:
        self._config = config
        self._skin = self._all_skins.get(str(config.get("theme", "")))
        self._apply_scrollbar_style()
        self._content.update()

    def _apply_scrollbar_style(self) -> None:
        """Tint the scroll area's chrome with the active skin palette so
        the default grey Qt widgets don't break the visual language."""
        if self._skin is None:
            return
        t = self._skin.THEME
        bg = t.get("bg", "#1a1a2e")
        track = t.get("bar_track", "#333340")
        thumb = t.get("accent", t.get("bar_blue", "#5B9BD5"))
        self._scroll.setStyleSheet(
            f"QScrollArea, QScrollArea QWidget {{ background: {bg}; border: 0; }}"
            f"QScrollBar:vertical {{ background: {bg}; width: 10px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: {thumb}; border-radius: 4px; min-height: 24px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: none; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: {track}; }}"
        )

    def update_stats(self, stats) -> None:
        from claude_usage.skins._adapter import build_popup_data
        self._data = build_popup_data(stats)
        # First-data-in: stop the loading animation and repaint immediately
        # so the placeholder doesn't linger for another timer interval.
        if self._loading_timer.isActive():
            self._loading_timer.stop()
        self._resize_content()
        self._content.update()

    def _tick_loading(self) -> None:
        if self._data is not None:
            self._loading_timer.stop()
            return
        self._loading_phase = (self._loading_phase + 0.12) % 1.0
        self._content.update()

    def _resize_content(self) -> None:
        if self._skin is None:
            return
        width = int(self._skin.METRICS.get("popup_width", 540) * self._scale)
        if self._data is None:
            # No data yet — size the content so the loading indicator has
            # a sensible canvas. 360px covers every skin's paint_loading.
            placeholder_h = int(360 * self._scale)
            self._content.setFixedSize(width, placeholder_h)
            self.resize(width, placeholder_h)
            return
        measure = getattr(self._skin, "measure_popup", None)
        if callable(measure):
            height = int(measure(self._data, self._scale))
        else:
            # Generic-layout skins need roughly this much for the full
            # section stack (plan / calendar / cost / projects / tips /
            # weekly report / ticker footer). 1180 is the observed max
            # across dashboard / hud / receipt / strip / brutalist at 1.0x.
            height = int(1180 * self._scale)
        # Snap to a minimum so short data doesn't leave a tiny postage-
        # stamp window either.
        height = max(height, int(520 * self._scale))
        self._content.setFixedSize(width, height)
        # Size the outer window to exactly wrap the content so we don't
        # leave grey gutters around a small popup. Cap the height at 90%
        # of the available screen so a very tall popup still scrolls
        # inside a sane window frame.
        try:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            max_h = int(screen.availableGeometry().height() * 0.9) if screen else height
        except Exception:
            max_h = height
        # Add scrollbar width when the content is taller than the
        # available space so nothing gets hidden under a floating bar.
        chrome_w = 14 if height > max_h else 0
        window_h = min(height, max_h)
        self.resize(width + chrome_w, window_h)

    def _paint_content(self, _event) -> None:
        if self._skin is None:
            return
        from PySide6.QtCore import QRectF
        p = QPainter(self._content)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        try:
            if self._data is None:
                # First-open placeholder — animated by _tick_loading.
                paint_loading = getattr(self._skin, "paint_loading", None)
                if callable(paint_loading):
                    paint_loading(p, QRectF(self._content.rect()),
                                  self._loading_phase, self._scale)
                return
            self._skin.paint_popup(
                p, QRectF(self._content.rect()), self._data, self._scale,
            )
        except Exception:
            import traceback
            traceback.print_exc()


class _Barcode(QWidget):
    """Decorative 1D barcode — used as the receipt-popup footer stamp.

    Deterministic bar widths (no PRNG) so screenshot runs are byte-stable.
    Doesn't encode anything real; it's pure thermal-chit visual vibe.
    """

    HEIGHT = 32

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(260)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), _hex_to_qcolor(self._theme["bg"]))
        ink = _hex_to_qcolor(self._theme["text_primary"])
        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        # 32 bar units interleaved with 32 gap units, mirroring the design
        # mock's `repeat-in-pattern` approach.
        pattern = (1, 2, 1, 3, 2, 1, 1, 3, 1, 2, 2, 1, 3, 1, 2, 1,
                   1, 3, 1, 2, 1, 3, 2, 1, 1, 2, 3, 1, 2, 1, 3, 1)
        total_units = sum(pattern) * 2
        unit = w / total_units
        cx = 0.0
        for i, wu in enumerate(pattern):
            bw = wu * unit
            if i % 2 == 0:  # even index = solid bar, odd = gap
                p.drawRect(QRectF(cx, 0, bw, h))
            cx += bw


# ---------------------------------------------------------------------------
# Detail popup
# ---------------------------------------------------------------------------

class UsagePopup(QWidget):
    """Scrollable detail window showing all :class:`UsageStats` fields."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = config
        theme_name = str(config.get("theme", "default"))
        self._theme = get_theme(theme_name)
        self._style: ThemeStyle = get_style(theme_name)

        self.setWindowTitle("Claude Usage")
        # Resizable: set a sensible initial size and a minimum, but let the
        # user drag the window edges to widen it. A fixed width makes the
        # scrollbar overlap content and denies power users more horizontal
        # room for the per-model cost breakdown.
        self.resize(POPUP_WIDTH, 640)
        self.setMinimumWidth(420)
        self.setMinimumHeight(360)
        # Qt.Tool keeps the popup hidden from the dock / taskbar — exit is
        # via the OSD right-click menu. WindowCloseButtonHint still gives us
        # a native close button on the title bar for discoverability.
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        # Reinforce "don't show me in the dock" via the NET_WM window-type
        # hint. Utility windows are excluded from KDE/GNOME taskbars by spec.
        self.setAttribute(Qt.WA_X11NetWmWindowTypeUtility, True)

        # Style sheet — applied once per instance.
        self.setStyleSheet(self._build_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Most-recent stats snapshot — stored while the popup is hidden so
        # we can flush it on show without rebuilding the tree every 30 s
        # for a popup nobody's looking at.
        self._pending_stats: UsageStats | None = None

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        root.addWidget(self._scroll)

        # Content container.  We rebuild its layout on every update().
        self._content = QWidget()
        self._content.setObjectName("popupRoot")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(POPUP_PAD, POPUP_PAD, POPUP_PAD, POPUP_PAD)
        self._layout.setSpacing(0)
        self._scroll.setWidget(self._content)

    # ------------------------------------------------------------------ QSS

    def _build_qss(self) -> str:
        t = self._theme
        return f"""
            QWidget#popupRoot, QScrollArea {{ background-color: {t['bg']}; }}
            QLabel {{ color: {t['text_primary']}; }}
            QLabel[role="header"] {{ font-size: 14px; font-weight: bold; color: {t['text_primary']}; }}
            QLabel[role="sub"]    {{ font-size: 11px; color: {t['text_secondary']}; }}
            QLabel[role="dim"]    {{ font-size: 11px; color: {t['text_dim']}; }}
            QLabel[role="metric"] {{ font-size: 13px; font-weight: bold; color: {t['text_primary']}; }}
            QLabel[role="pct"]    {{ font-size: 12px; color: {t['text_secondary']}; }}
            QLabel[role="link"]   {{ font-size: 11px; color: {t['text_link']}; }}
            QLabel[role="error"]  {{ font-size: 11px; color: {t['error']}; }}
        """

    # -------------------------------------------------------------- helpers

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _label(self, text: str, role: str = "") -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        # Default to plain text — never interpret user-sourced content
        # (prompt previews, AI report output, project paths) as rich HTML.
        lbl.setTextFormat(Qt.PlainText)
        if role:
            lbl.setProperty("role", role)
        return lbl

    def _add_section_header(self, title: str, right: str = "") -> None:
        from PySide6.QtWidgets import QHBoxLayout, QFrame

        row = QFrame()
        row.setStyleSheet("QFrame { background: transparent; }")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 10)

        title_lbl = self._label(title, "header")
        hl.addWidget(title_lbl, 1, Qt.AlignLeft)

        if right:
            right_lbl = self._label(right, "sub")
            hl.addWidget(right_lbl, 0, Qt.AlignRight)

        self._layout.addWidget(row)

    def _add_usage_row(self, label: str, subtitle: str, fraction: float) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QFrame

        row = QFrame()
        row.setStyleSheet("QFrame { background: transparent; }")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 14)
        hl.setSpacing(12)

        # Left: label + subtitle
        left = QWidget()
        left.setFixedWidth(140)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        name = self._label(label, "metric")
        left_layout.addWidget(name)
        if subtitle:
            left_layout.addWidget(self._label(subtitle, "sub"))
        hl.addWidget(left)

        # Middle: bar
        bar = _ProgressBar(self._theme, height=12)
        bar.set_fraction(fraction)
        hl.addWidget(bar, 1)

        # Right: percentage
        pct = self._label(f"{min(int(fraction * 100), 100)}% used", "pct")
        pct.setFixedWidth(72)
        pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(pct)

        self._layout.addWidget(row)

    def _add_dim_line(self, text: str, role: str = "dim", margin_bottom: int = 6) -> None:
        lbl = self._label(text, role)
        lbl.setContentsMargins(0, 0, 0, margin_bottom)
        self._layout.addWidget(lbl)

    def _add_sparkline(self, buckets: list[float], caption: str) -> None:
        sp = _Sparkline(self._theme)
        sp.set_buckets(buckets)
        self._layout.addWidget(sp)
        self._add_dim_line(caption, margin_bottom=12)

    def _add_heatmap(self, buckets: list[float], caption: str) -> None:
        hm = _Heatmap(self._theme)
        hm.set_buckets(buckets)
        self._layout.addWidget(hm)
        self._add_dim_line(caption, margin_bottom=12)

    def _add_calendar_heatmap(self, buckets: list[float], caption: str) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QFrame
        row = QFrame()
        row.setStyleSheet("QFrame { background: transparent; }")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        cal = _CalendarHeatmap(self._theme)
        cal.set_buckets(_align_calendar_buckets(list(buckets)))
        hl.addWidget(cal)
        hl.addStretch(1)
        self._layout.addWidget(row)
        self._add_dim_line(caption, margin_bottom=12)

    def _add_separator(self) -> None:
        from PySide6.QtWidgets import QFrame
        # Spacer above the hairline
        self._layout.addSpacing(6)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(
            f"background-color: {self._theme['separator']}; border: none;"
        )
        self._layout.addWidget(sep)
        # Spacer below the hairline
        self._layout.addSpacing(14)

    # --------------------------------------------------------------- update

    def apply_config(self, config: dict[str, Any]) -> None:
        """Re-read theme/opacity in case the user changed it at runtime."""
        self._config = config
        theme_name = str(config.get("theme", "default"))
        self._theme = get_theme(theme_name)
        self._style = get_style(theme_name)
        self.setStyleSheet(self._build_qss())

    @Slot(object)
    def update_stats(self, stats: UsageStats) -> None:
        """Rebuild the popup contents from *stats*.

        Hidden popups skip the full layout teardown+rebuild — when the user
        opens it again we re-run with the then-current stats (see ``show``
        override below).
        """
        self._pending_stats = stats
        if not self.isVisible():
            return
        self._rebuild_from(stats)

    def showEvent(self, event) -> None:  # noqa: N802
        # First show after stats arrived while we were hidden — flush.
        if self._pending_stats is not None and self._layout.count() == 0:
            self._rebuild_from(self._pending_stats)
        super().showEvent(event)

    def _rebuild_from(self, stats: UsageStats) -> None:
        self._clear_layout()

        # --- Plan usage limits ---
        self._add_section_header("Plan usage limits")
        self._add_usage_row(
            "Current session",
            _format_reset_duration(stats.session_reset),
            stats.session_utilization,
        )
        s_fc = format_forecast(stats.session_forecast)
        if s_fc:
            self._add_dim_line(s_fc)
        self._add_sparkline(stats.session_history, "Last 5 hours")
        self._add_separator()

        # --- Weekly limits ---
        self._add_section_header("Weekly limits")
        self._add_usage_row(
            "All models",
            _format_reset_day(stats.weekly_reset),
            stats.weekly_utilization,
        )
        w_fc = format_forecast(stats.weekly_forecast)
        if w_fc:
            self._add_dim_line(w_fc)
        self._add_sparkline(stats.weekly_history, "Last 7 days")

        # 90-day heatmap
        heatmap = getattr(stats, "daily_heatmap", []) or []
        if any(v > 0 for v in heatmap):
            self._add_heatmap(heatmap, "Last 90 days")

        # 52-week × 7-day calendar heatmap (GitHub-style)
        yearly = getattr(stats, "yearly_heatmap", []) or []
        if any(v > 0 for v in yearly):
            self._add_calendar_heatmap(yearly, "Last 52 weeks")
        self._add_separator()

        # --- Anomaly banner ---
        anomaly = getattr(stats, "anomaly", None)
        if anomaly is not None and getattr(anomaly, "is_anomaly", False):
            self._add_section_header("⚠ Unusual activity")
            self._add_dim_line(anomaly.message, margin_bottom=12)
            self._add_separator()

        # --- Cost / API-equivalent value ---
        self._render_cost_section(stats)

        # --- Top projects ---
        self._render_top_projects(stats)

        # --- Tips ---
        tips = getattr(stats, "tips", []) or []
        if tips:
            self._add_section_header("💡 Tips")
            for tip in tips:
                self._add_dim_line(tip, margin_bottom=6)
            self._add_separator()

        # --- Cache savings opportunities ---
        self._render_cache_opportunities(stats)

        # --- Weekly Claude-authored report ---
        self._render_weekly_report(stats)

        # --- Active sessions ---
        self._render_active_sessions(stats)

        # --- Footer ---
        self._render_footer(stats)

    # ------------------------------------------------------------ sections

    def _render_cost_section(self, stats: UsageStats) -> None:
        today_cost = float(getattr(stats, "today_cost", 0.0) or 0.0)
        if today_cost <= 0:
            return

        cache_savings = float(getattr(stats, "cache_savings", 0.0) or 0.0)
        sub = (getattr(stats, "subscription_type", "") or "").lower()
        is_subscriber = sub in ("pro", "max", "team", "enterprise")

        # Short header; detailed framing lives in the dim sub-line below so the
        # popup width doesn't force the title onto two lines.
        if is_subscriber:
            self._add_section_header("Cost (today)", right=f"{sub.capitalize()} plan")
            self._add_dim_line(f"${today_cost:.2f}", role="metric", margin_bottom=4)
            self._add_dim_line(
                "API pay-as-you-go equivalent — included in your plan",
                margin_bottom=4,
            )
        else:
            self._add_section_header("Cost (today)")
            self._add_dim_line(f"${today_cost:.2f}", role="metric", margin_bottom=4)

        if cache_savings > 0:
            self._add_dim_line(f"${cache_savings:.2f} saved by cache", margin_bottom=8)

        by_model = getattr(stats, "today_by_model_detailed", {}) or {}
        if by_model:
            self._render_per_model_breakdown(by_model)

        self._add_separator()

    def _render_per_model_breakdown(self, by_model: dict) -> None:
        total_in = total_out = total_cr = total_cc = 0
        rows = []
        for model, counts in by_model.items():
            in_t = int(counts.get("input", 0) or 0)
            out_t = int(counts.get("output", 0) or 0)
            cr_t = int(counts.get("cache_read", 0) or 0)
            cc_t = int(counts.get("cache_creation", 0) or 0)
            total_in += in_t
            total_out += out_t
            total_cr += cr_t
            total_cc += cc_t
            bk = calculate_cost(model, in_t, out_t, cr_t, cc_t)
            rows.append((_short_model_name(model), model, in_t, out_t, cr_t, cc_t, bk))
        rows.sort(key=lambda r: r[6]["total"], reverse=True)

        self._add_dim_line(
            f"Tokens: {_format_tokens(total_in)} in • "
            f"{_format_tokens(total_out)} out • "
            f"{_format_tokens(total_cr)} cache read • "
            f"{_format_tokens(total_cc)} cache write",
            margin_bottom=6,
        )

        for short, model, in_t, out_t, cr_t, cc_t, bk in rows:
            if bk["total"] < 0.01:
                continue
            rates = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
            self._add_dim_line(f"  {short}: ${bk['total']:.2f} total", margin_bottom=2)
            if in_t > 0:
                self._add_dim_line(
                    f"     input:  {_format_tokens(in_t):>7} × ${rates['input']:.2f}/M = ${bk['input']:.2f}",
                    margin_bottom=2,
                )
            if out_t > 0:
                self._add_dim_line(
                    f"     output: {_format_tokens(out_t):>7} × ${rates['output']:.2f}/M = ${bk['output']:.2f}",
                    margin_bottom=2,
                )
            if cr_t > 0:
                self._add_dim_line(
                    f"     cache read:  {_format_tokens(cr_t):>7} × ${rates['cache_read']:.2f}/M = ${bk['cache_read']:.2f}",
                    margin_bottom=2,
                )
            if cc_t > 0:
                self._add_dim_line(
                    f"     cache write: {_format_tokens(cc_t):>7} × ${rates['cache_creation']:.2f}/M = ${bk['cache_creation']:.2f}",
                    margin_bottom=4,
                )

    def _render_top_projects(self, stats: UsageStats) -> None:
        projects = getattr(stats, "today_by_project", {}) or {}
        if not projects:
            return
        self._add_section_header("Top projects today")
        items = sorted(projects.items(), key=lambda kv: kv[1], reverse=True)
        for name, tokens in items[:5]:
            try:
                tok = int(tokens)
            except (TypeError, ValueError):
                tok = 0
            self._add_dim_line(
                f"{_prettify_project_name(name)}: {_format_tokens(tok)} tokens",
                margin_bottom=4,
            )
        self._add_separator()

    def _render_cache_opportunities(self, stats: UsageStats) -> None:
        opps = getattr(stats, "cache_opportunities", []) or []
        if not opps:
            return
        total = sum(float(o.potential_savings_usd) for o in opps)
        self._add_section_header(
            "💰 Cache opportunities",
            right=f"~${total:.2f}/wk savings" if total > 0 else "",
        )
        for o in opps[:5]:
            name = _prettify_project_name(getattr(o, "project", "") or "?")
            preview = (getattr(o, "prefix_preview", "") or "").strip()
            if len(preview) > 70:
                preview = preview[:67] + "…"
            self._add_dim_line(
                f"{name}: {getattr(o, 'occurrences', 0)}× × "
                f"{_format_tokens(getattr(o, 'token_count', 0))} tokens → "
                f"${float(getattr(o, 'potential_savings_usd', 0.0)):.2f}",
                margin_bottom=2,
            )
            if preview:
                self._add_dim_line(f"    “{preview}”", margin_bottom=6)
        self._add_separator()

    def _render_weekly_report(self, stats: UsageStats) -> None:
        text = (getattr(stats, "weekly_report_text", "") or "").strip()
        if not text:
            return
        self._add_section_header("🪄 Your week with Claude")
        self._add_dim_line(text, margin_bottom=12)
        self._add_separator()

    def _render_active_sessions(self, stats: UsageStats) -> None:
        self._add_section_header(
            "Active sessions",
            f"{len(stats.active_sessions)} running",
        )
        if stats.active_sessions:
            for sess in stats.active_sessions:
                started = datetime.fromtimestamp(sess.get("startedAt", 0) / 1000)
                duration = datetime.now() - started
                cwd = sess.get("cwd", "?").replace(os.path.expanduser("~"), "~")
                dur = _format_session_duration(int(duration.total_seconds()))
                self._add_dim_line(f"{cwd}    {dur}", role="link", margin_bottom=4)
        else:
            self._add_dim_line("No active sessions", margin_bottom=4)

    def _render_footer(self, stats: UsageStats) -> None:
        self._add_separator()
        self._add_dim_line("Last updated: just now", margin_bottom=0)
        if stats.rate_limit_error:
            self._add_dim_line(f"API: {stats.rate_limit_error}", role="error", margin_bottom=0)

        # Receipt-skin statement stamp: "— END OF STATEMENT —" + 1D barcode
        # + a version line. Matches the thermal-chit popup footer in the
        # Claude Design source.
        if self._style.decoration == "receipt":
            from PySide6.QtWidgets import QHBoxLayout, QFrame
            self._layout.addSpacing(8)
            end_line = self._label("— END OF STATEMENT —", role="dim")
            end_line.setAlignment(Qt.AlignHCenter)
            self._layout.addWidget(end_line)

            bar_row = QFrame()
            bar_row.setStyleSheet("QFrame { background: transparent; }")
            h_layout = QHBoxLayout(bar_row)
            h_layout.setContentsMargins(0, 8, 0, 4)
            barcode = _Barcode(self._theme)
            h_layout.addStretch(1)
            h_layout.addWidget(barcode)
            h_layout.addStretch(1)
            self._layout.addWidget(bar_row)

            from claude_usage import __version__ as _v
            ver_line = self._label(
                f"CLAUDE-USAGE-WIDGET-{_v}", role="dim",
            )
            ver_line.setAlignment(Qt.AlignHCenter)
            self._layout.addWidget(ver_line)


# ---------------------------------------------------------------------------
# Application orchestrator
# ---------------------------------------------------------------------------

class ClaudeUsageApp(QObject):
    """Wires OSD, popup, timer, refresh thread, webhooks, and notifier."""

    # Emitted on the GUI thread once background collection completes.
    stats_ready = Signal(object)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self.config = config
        self.stats = UsageStats()
        self._alive = True
        self._refreshing = False
        self._last_daily_report_date: str = ""

        # UI components — we keep BOTH popup implementations around:
        # the default one (full QLayout + child widgets) handles the five
        # classic themes, and the skin popup delegates its whole paintEvent
        # to the active direction module. `_show_popup` picks whichever
        # matches the current theme.
        self.overlay = UsageOverlay(config)
        self.popup = UsagePopup(config)
        self.skin_popup = SkinPopupWidget(config)

        # Context menu shown on right-click of the OSD.
        self._context_menu = QMenu()
        self._build_context_menu()

        # Webhook dispatcher + notifier
        from claude_usage.webhooks import WebhookDispatcher
        self._webhooks = WebhookDispatcher(config.get("webhooks", {}))
        self.notifier = UsageNotifier(
            config,
            on_threshold=lambda scope, t: self._webhooks.fire(
                "threshold_crossed", {"scope": scope, "threshold": t},
            ),
        )

        # Optional: localhost JSON API server. Bind failures (port in use,
        # permission denied) are non-fatal — the widget still starts, just
        # without the HTTP surface.
        self._api_server = None
        if config.get("api_server_enabled"):
            from claude_usage.api_server import UsageAPIServer
            try:
                self._api_server = UsageAPIServer(
                    host=config.get("api_server_host", "127.0.0.1"),
                    port=int(config.get("api_server_port", 8765)),
                    get_stats=lambda: self.stats,
                )
                self._api_server.start()
            except OSError as exc:
                print(
                    f"claude-usage: API server failed to start: {exc}",
                    file=sys.stderr,
                )
                self._api_server = None

        # --- Wire signals ---
        self.overlay.clicked.connect(self._on_overlay_click)
        self.overlay.rightClicked.connect(self._on_overlay_right_click)
        self.stats_ready.connect(self._apply_stats)

        # Show the overlay and kick off the first refresh.
        self.overlay.show()
        self._refresh_async()

        # Periodic refresh timer (runs on the GUI thread).
        refresh_secs = int(config.get("refresh_seconds", 30))
        self._timer = QTimer()
        self._timer.setInterval(refresh_secs * 1000)
        self._timer.timeout.connect(self._refresh_async)
        self._timer.start()

        # One-shot GitHub release check.
        self._latest_tag: str | None = None
        threading.Thread(target=self._check_update, daemon=True).start()

        # Tracks whether a weekly-report generation is already in flight, so
        # the hourly check doesn't spawn multiple Haiku calls in parallel.
        self._weekly_report_in_flight = False

    # ----------------------------------------------------------- menu build

    def _build_context_menu(self) -> None:
        m = self._context_menu

        act_details = QAction("Details…", m)
        act_details.triggered.connect(self._show_popup)
        m.addAction(act_details)

        act_refresh = QAction("Refresh", m)
        act_refresh.triggered.connect(self._refresh_async)
        m.addAction(act_refresh)

        m.addSeparator()

        opacity_menu = m.addMenu("OSD Opacity")
        for pct in (100, 75, 50, 25):
            a = QAction(f"{pct}%", opacity_menu)
            a.triggered.connect(lambda _checked=False, v=pct / 100.0: self.overlay.set_opacity(v))
            opacity_menu.addAction(a)

        # View mode submenu — bars vs gauges, radio-grouped.
        from PySide6.QtGui import QActionGroup as _QActionGroup
        from claude_usage.overlay import VIEW_MODES
        view_menu = m.addMenu("OSD View")
        self._view_group = _QActionGroup(view_menu)
        self._view_group.setExclusive(True)
        self._view_actions: dict[str, QAction] = {}
        for mode in VIEW_MODES:
            a = QAction(mode.capitalize(), view_menu)
            a.setCheckable(True)
            a.setActionGroup(self._view_group)
            a.triggered.connect(lambda _checked=False, md=mode: self._on_pick_view_mode(md))
            view_menu.addAction(a)
            self._view_actions[mode] = a

        # Theme submenu — radio group so only one is ticked at a time. The
        # selection auto-persists to the user config so a restart keeps it.
        from PySide6.QtGui import QActionGroup
        from claude_usage.themes import THEMES
        theme_menu = m.addMenu("Theme")
        self._theme_group = QActionGroup(theme_menu)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for name in sorted(THEMES.keys()):
            a = QAction(name, theme_menu)
            a.setCheckable(True)
            a.setActionGroup(self._theme_group)
            a.triggered.connect(lambda _checked=False, n=name: self._on_pick_theme(n))
            theme_menu.addAction(a)
            self._theme_actions[name] = a

        act_minimize = QAction("Minimize / Restore", m)
        act_minimize.triggered.connect(self.overlay.toggle_minimized)
        m.addAction(act_minimize)

        self._act_ticker = QAction("Show cost ticker", m)
        self._act_ticker.setCheckable(True)
        self._act_ticker.setChecked(self.overlay.is_ticker_enabled())
        self._act_ticker.toggled.connect(self._on_toggle_ticker)
        m.addAction(self._act_ticker)
        m.aboutToShow.connect(self._sync_menu_state)

        m.addSeparator()

        act_quit = QAction("Quit", m)
        act_quit.triggered.connect(self._on_quit)
        m.addAction(act_quit)

    def _on_toggle_ticker(self, checked: bool) -> None:
        self.overlay.set_ticker_enabled(checked)
        self.config["show_ticker"] = bool(checked)
        self._persist_config()

    def _on_pick_theme(self, name: str) -> None:
        # If either popup is open, close it — switching themes swaps the
        # painter/layout wholesale, and leaving the old window visible
        # causes a jarring mid-paint flicker. User can re-open to see the
        # new theme.
        if self.popup.isVisible():
            self.popup.hide()
        if self.skin_popup.isVisible():
            self.skin_popup.hide()
        self.overlay.set_theme(name)
        merged = {**self.config, "theme": name}
        self.popup.apply_config(merged)
        self.skin_popup.apply_config(merged)
        self.config["theme"] = name
        self._persist_config()

    def _on_pick_view_mode(self, mode: str) -> None:
        self.overlay.set_view_mode(mode)
        self.config["osd_view_mode"] = mode
        self._persist_config()

    def _sync_menu_state(self) -> None:
        """Refresh the tick marks on checkable items when the menu opens."""
        self._act_ticker.setChecked(self.overlay.is_ticker_enabled())
        current_theme = str(self.config.get("theme", "default"))
        theme_act = self._theme_actions.get(current_theme)
        if theme_act is not None:
            theme_act.setChecked(True)
        current_view = self.overlay.view_mode()
        view_act = self._view_actions.get(current_view)
        if view_act is not None:
            view_act.setChecked(True)

    def _persist_config(self) -> None:
        """Write the in-memory config to the user's XDG config file.

        Best-effort: if the filesystem is read-only (sandboxed installs,
        full disk) we swallow the error rather than crashing the GUI.
        The change still applies for the remainder of the session.
        """
        from claude_usage.config import save_config, user_config_path
        try:
            save_config(user_config_path(), self.config)
        except OSError:
            pass

    # ------------------------------------------------------------- refresh

    def _refresh_async(self) -> None:
        if self._refreshing or not self._alive:
            return
        self._refreshing = True

        def _worker() -> None:
            try:
                stats = collect_all(self.config)
            except Exception:
                stats = UsageStats(rate_limit_error="Collection failed")
            # Emit cross-thread signal; the slot runs on the GUI thread.
            if self._alive:
                self.stats_ready.emit(stats)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(object)
    def _apply_stats(self, stats: UsageStats) -> None:
        self._refreshing = False
        if not self._alive:
            return
        self.stats = stats

        self.overlay.update_stats(stats)
        self.popup.update_stats(stats)
        self.skin_popup.update_stats(stats)
        self.notifier.check_stats(stats)

        # Webhook: anomaly
        if getattr(stats.anomaly, "is_anomaly", False):
            self._webhooks.fire("anomaly", {
                "ratio": stats.anomaly.ratio,
                "z_score": stats.anomaly.z_score,
                "message": stats.anomaly.message,
            })

        # Weekly report: kick off a background regeneration if the on-disk
        # cache is stale and we're not already generating. Pass a snapshot
        # of the stats so the worker never observes a torn mid-refresh mix
        # of fields.
        if not stats.weekly_report_text and not self._weekly_report_in_flight:
            self._weekly_report_in_flight = True
            threading.Thread(
                target=self._generate_weekly_report,
                args=(stats,),
                daemon=True,
            ).start()

        # Webhook: daily report (first refresh of each local day)
        today_iso = datetime.now().strftime("%Y-%m-%d")
        if today_iso != self._last_daily_report_date:
            self._last_daily_report_date = today_iso
            self._webhooks.fire("daily_report", {
                "date": today_iso,
                "session_utilization": stats.session_utilization,
                "weekly_utilization": stats.weekly_utilization,
                "today_cost": stats.today_cost,
                "today_tokens": stats.today_tokens,
            })

    # -------------------------------------------------------------- slots

    def _on_overlay_click(self) -> None:
        self._show_popup()

    def _on_overlay_right_click(self, global_pos: QPoint) -> None:
        self._context_menu.popup(global_pos)

    def _show_popup(self) -> None:
        # Pick the popup implementation that matches the active theme:
        # classic themes use the layout-based popup; the 6 handoff skins
        # use SkinPopupWidget (pure paintEvent).
        from claude_usage.skins import SKIN_MODULES
        theme_name = str(self.config.get("theme", "default"))
        target = self.skin_popup if theme_name in SKIN_MODULES else self.popup
        # Hide the other so both windows aren't on-screen simultaneously.
        other = self.popup if target is self.skin_popup else self.skin_popup
        if other.isVisible():
            other.hide()
        target.show()
        target.raise_()
        target.activateWindow()

    def _generate_weekly_report(self, snapshot: UsageStats) -> None:
        try:
            from claude_usage.ai_report import generate_report
            from claude_usage.collector import _load_credentials
            claude_dir = self.config["claude_dir"]
            summary = {
                "week_cost": snapshot.week_cost,
                "week_tokens": snapshot.week_tokens,
                "week_messages": snapshot.week_messages,
                "subscription_type": snapshot.subscription_type,
                "top_projects": sorted(
                    snapshot.today_by_project.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:3],
                "by_model": snapshot.today_by_model_detailed,
            }
            generate_report(
                claude_dir=claude_dir,
                summary=summary,
                token_loader=lambda: _load_credentials(claude_dir),
            )
        except Exception:
            pass
        finally:
            self._weekly_report_in_flight = False

    def _check_update(self) -> None:
        try:
            from claude_usage import __version__ as v
            from claude_usage.updater import check_latest_version
            tag, available = check_latest_version(v)
            if available and tag:
                self._latest_tag = tag
                # Show a one-time system notification.
                self.notifier._send(
                    f"Claude Usage {tag} available",
                    "Update with: pip install --upgrade claude-usage-widget",
                )
        except Exception:
            pass

    def _on_quit(self) -> None:
        self._alive = False
        self._timer.stop()
        if self._api_server is not None:
            try:
                self._api_server.stop()
            except Exception:
                pass
        QApplication.instance().quit()
