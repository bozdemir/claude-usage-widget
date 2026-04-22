"""Frameless, transparent OSD overlay — PySide6 implementation.

The OSD sits at the top-right corner of the primary screen, always on top,
showing session and weekly utilization bars with reset countdowns.

Interactions:
    Left-click (no drag)  — emit ``clicked`` (opens the detail popup)
    Left-click + drag     — move the overlay
    Right-click           — emit ``rightClicked`` (shows context menu)
    Scroll wheel          — resize (0.6x -- 2.0x)
    Right-click-drag      — not used
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from claude_usage.collector import UsageStats
from claude_usage.themes import get_theme


# Base OSD dimensions (at scale=1.0)
BASE_WIDTH = 260
BASE_HEIGHT = 100
OSD_MARGIN = 16
OSD_RADIUS = 12
OSD_BAR_HEIGHT = 6
OSD_BAR_RADIUS = 3
MINIMIZED_HEIGHT = 6

# Scroll-wheel scale limits
SCALE_MIN = 0.6
SCALE_MAX = 2.0
SCALE_STEP = 0.1

# Distance the mouse must move between press and release before a left-click
# is treated as a drag rather than a click.
DRAG_THRESHOLD = 5


def _hex_to_qcolor(hex_str: str, alpha: float = 1.0) -> QColor:
    """Convert ``#RRGGBB`` to ``QColor`` with the given alpha (0.0 -- 1.0)."""
    h = hex_str.lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return QColor(r, g, b, int(alpha * 255))


def _format_reset_short(reset_ts: int) -> str:
    """Compact reset label: '2h 31m' (< 24h) or 'Mon 16:00' (>= 24h)."""
    if reset_ts <= 0:
        return ""
    remaining = int(reset_ts - datetime.now().timestamp())
    if remaining <= 0:
        return "soon"
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    if hours < 24:
        return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
    return datetime.fromtimestamp(reset_ts).strftime("%a %H:%M")


def _bar_color(pct: float, theme: dict[str, str]) -> QColor:
    """Return the progress-bar fill colour for *pct* (0.0 -- 1.0)."""
    if pct < 0.6:
        return _hex_to_qcolor(theme["bar_blue"])
    if pct < 0.85:
        return _hex_to_qcolor(theme["warn"])
    return _hex_to_qcolor(theme["crit"])


class UsageOverlay(QWidget):
    """Transparent, frameless OSD showing session + weekly utilisation."""

    # Emitted when the user left-clicks (without dragging).
    clicked = Signal()
    # Emitted when the user right-clicks. Handler should show a context menu.
    rightClicked = Signal(QPoint)

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        cfg = config or {}
        self._theme = get_theme(str(cfg.get("theme", "default")))
        self._scale: float = float(cfg.get("osd_scale", 1.0))
        self._opacity: float = float(cfg.get("osd_opacity", 0.75))
        self._minimized: bool = False

        # Live stats — updated externally via update_stats()
        self._session_pct: float = 0.0
        self._weekly_pct: float = 0.0
        self._session_reset: int = 0
        self._weekly_reset: int = 0

        # Drag tracking
        self._press_pos: QPoint | None = None        # mouse pos on press (global)
        self._press_win_pos: QPoint | None = None    # window pos on press
        self._dragging: bool = False

        # Window setup — frameless, transparent, always on top, no taskbar.
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool                      # tool window, should stay above normal ones
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus  # typing doesn't steal focus from other apps
            | Qt.BypassWindowManagerHint   # KDE/GNOME: skip window-manager decoration entirely
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # NET_WM hint: tell the window manager this is a Notification, so dock
        # / taskbar / Alt-Tab overlays all skip it.
        self.setAttribute(Qt.WA_X11NetWmWindowTypeNotification, True)

        # Initial size + position (top-right of primary screen).
        self._apply_size()
        self._move_to_default_position()

    # ------------------------------------------------------------------ API

    def update_stats(self, stats: UsageStats) -> None:
        """Apply the latest :class:`UsageStats` and trigger a repaint."""
        self._session_pct = max(0.0, min(1.0, float(stats.session_utilization)))
        self._weekly_pct = max(0.0, min(1.0, float(stats.weekly_utilization)))
        self._session_reset = int(stats.session_reset)
        self._weekly_reset = int(stats.weekly_reset)
        self.update()  # schedule a paintEvent

    def set_opacity(self, value: float) -> None:
        """Set background opacity (0.15 -- 1.0)."""
        self._opacity = max(0.15, min(1.0, float(value)))
        self.update()

    def set_theme(self, name: str) -> None:
        """Switch to a named theme and repaint."""
        self._theme = get_theme(name)
        self.update()

    def toggle_minimized(self) -> None:
        """Collapse to a thin progress bar or restore the full panel."""
        self._minimized = not self._minimized
        self._apply_size()
        self.update()

    # ------------------------------------------------------------- internals

    def _apply_size(self) -> None:
        """Resize the window to match ``_scale`` and ``_minimized``."""
        width = int(BASE_WIDTH * self._scale)
        height = MINIMIZED_HEIGHT if self._minimized else int(BASE_HEIGHT * self._scale)
        # Preserve the top-right corner when resizing so the overlay doesn't
        # visually drift as the user scrolls to scale.
        if self.isVisible():
            tr = self.frameGeometry().topRight()
            self.resize(width, height)
            self.move(tr.x() - width, tr.y())
        else:
            self.resize(width, height)

    def _move_to_default_position(self) -> None:
        """Anchor the overlay at the top-right of the primary screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + geo.width() - self.width() - OSD_MARGIN
        y = geo.y() + OSD_MARGIN
        self.move(x, y)

    # --------------------------------------------------------------- events

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_win_pos = self.frameGeometry().topLeft()
            self._dragging = False
        elif event.button() == Qt.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_pos is None:
            return
        delta = event.globalPosition().toPoint() - self._press_pos
        if not self._dragging and (abs(delta.x()) > DRAG_THRESHOLD or abs(delta.y()) > DRAG_THRESHOLD):
            self._dragging = True
        if self._dragging and self._press_win_pos is not None:
            self.move(self._press_win_pos + delta)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._press_pos is not None and not self._dragging:
            # It was a click (no drag) — open detail popup.
            self.clicked.emit()
        self._press_pos = None
        self._press_win_pos = None
        self._dragging = False

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._minimized:
            return
        # angleDelta().y() is +120 per "tick" upward, -120 downward.
        delta = event.angleDelta().y()
        if delta == 0:
            return
        step = SCALE_STEP if delta > 0 else -SCALE_STEP
        new_scale = max(SCALE_MIN, min(SCALE_MAX, self._scale + step))
        if new_scale != self._scale:
            self._scale = new_scale
            self._apply_size()
            self.update()

    # ----------------------------------------------------------- painting

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Clear to fully transparent — WA_TranslucentBackground already does
        # this, but we set CompositionMode_Source explicitly for reliability
        # across drivers.
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        if self._minimized:
            self._paint_minimized(p, w, h)
            return

        self._paint_full(p, w, h)

    def _paint_minimized(self, p: QPainter, w: int, h: int) -> None:
        """Thin capsule showing session utilisation."""
        track = _hex_to_qcolor(self._theme["bar_track"], 0.6)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), 3, 3)
        if self._session_pct > 0:
            fill_w = max(w * min(self._session_pct, 1.0), 4)
            p.setBrush(_bar_color(self._session_pct, self._theme))
            p.drawRoundedRect(QRectF(0, 0, fill_w, h), 3, 3)

    def _paint_full(self, p: QPainter, w: int, h: int) -> None:
        s = self._scale
        radius = OSD_RADIUS * s

        # Background
        bg = _hex_to_qcolor(self._theme["bg"], self._opacity)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        pad_x = 14 * s
        pad_y = 10 * s
        bar_h = OSD_BAR_HEIGHT * s
        bar_r = OSD_BAR_RADIUS * s
        bar_w = w - 2 * pad_x
        font_label = max(9, 10 * s)
        font_small = max(7, 7.5 * s)
        font_title = max(7, 8 * s)

        # Title
        title_font = QFont("monospace", int(font_title))
        p.setFont(title_font)
        p.setPen(_hex_to_qcolor(self._theme["text_dim"]))
        p.drawText(QPointF(pad_x, pad_y + 7 * s), "CLAUDE")

        # --- Session row ---
        y = pad_y + 16 * s
        self._draw_row(
            p, y, w, pad_x, bar_w, bar_h, bar_r, font_label, font_small,
            label="Session",
            pct=self._session_pct,
            reset_label=_format_reset_short(self._session_reset),
        )

        # --- Weekly row ---
        y2 = y + 15 * s + bar_h + 10 * s
        self._draw_row(
            p, y2, w, pad_x, bar_w, bar_h, bar_r, font_label, font_small,
            label="Weekly",
            pct=self._weekly_pct,
            reset_label=_format_reset_short(self._weekly_reset),
        )

    def _draw_row(
        self,
        p: QPainter,
        y: float,
        w: int,
        pad_x: float,
        bar_w: float,
        bar_h: float,
        bar_r: float,
        font_label: float,
        font_small: float,
        label: str,
        pct: float,
        reset_label: str,
    ) -> None:
        """Draw one row: label on the left, reset + percentage on the right, bar below."""
        # Label + percentage baseline
        p.setFont(QFont("monospace", int(font_label)))
        p.setPen(_hex_to_qcolor(self._theme["text_primary"]))
        baseline = y + 10 * self._scale
        p.drawText(QPointF(pad_x, baseline), label)

        pct_text = f"{int(pct * 100)}%"
        pct_width = p.fontMetrics().horizontalAdvance(pct_text)
        p.drawText(QPointF(w - pad_x - pct_width, baseline), pct_text)

        # Reset-time (between label and percentage, small font)
        if reset_label:
            p.setFont(QFont("monospace", int(font_small)))
            p.setPen(_hex_to_qcolor(self._theme["text_dim"]))
            rw = p.fontMetrics().horizontalAdvance(reset_label)
            p.drawText(
                QPointF(w - pad_x - pct_width - 8 * self._scale - rw, baseline),
                reset_label,
            )

        # Bar track
        bar_y = y + 14 * self._scale
        p.setPen(Qt.NoPen)
        p.setBrush(_hex_to_qcolor(self._theme["bar_track"], 0.6))
        p.drawRoundedRect(QRectF(pad_x, bar_y, bar_w, bar_h), bar_r, bar_r)

        # Bar fill
        if pct > 0:
            fill_w = max(bar_w * min(pct, 1.0), bar_h)
            p.setBrush(_bar_color(pct, self._theme))
            p.drawRoundedRect(QRectF(pad_x, bar_y, fill_w, bar_h), bar_r, bar_r)
