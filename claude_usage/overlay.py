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

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
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
from claude_usage.ticker import TickerItem


# Base OSD dimensions (at scale=1.0). Ticker adds ~22px to the bottom of
# the panel; when it's toggled off we collapse back to the original height.
BASE_WIDTH = 260
BASE_HEIGHT = 100
TICKER_STRIP_HEIGHT = 22
# Gauge view is slightly taller than bars because the rings + label + reset
# stack vertically inside each column. No ticker in this view (it would
# collide with the reset line under each ring).
GAUGE_HEIGHT = 130

# Supported OSD view modes. Kept as string constants so config files and
# tests don't have to import an enum.
VIEW_MODE_BARS = "bars"
VIEW_MODE_GAUGE = "gauge"
VIEW_MODES = (VIEW_MODE_BARS, VIEW_MODE_GAUGE)
OSD_MARGIN = 16
OSD_RADIUS = 12
OSD_BAR_HEIGHT = 6
OSD_BAR_RADIUS = 3
MINIMIZED_HEIGHT = 6

# Ticker animation: seconds-per-full-loop scales inversely with viewport
# width; we use a pixels-per-second rate instead so scale changes don't
# affect perceived speed. 30 px/s feels unhurried but still alive.
TICKER_SCROLL_PX_PER_SEC = 30.0
TICKER_FRAME_INTERVAL_MS = 40  # ~25 fps — smooth without waking the CPU

# Scroll-wheel scale limits
SCALE_MIN = 0.6
SCALE_MAX = 2.0
SCALE_STEP = 0.1

# Distance the mouse must move between press and release before a left-click
# is treated as a drag rather than a click.
DRAG_THRESHOLD = 5


def _ticker_quartile_thresholds(items: list[TickerItem]) -> tuple[float, float, float]:
    """Return (cool, warm, hot) cost cutoffs based on quartiles of *items*.

    With < 4 items the buffer is too small to quartile meaningfully, so
    we collapse to a single tier by returning sentinels that force every
    item into the "cool" bucket. This avoids flickering colours during the
    first seconds after startup.
    """
    if len(items) < 4:
        return (0.0, float("inf"), float("inf"))
    costs = sorted(it.cost_usd for it in items)
    n = len(costs)
    return (costs[n // 4], costs[n // 2], costs[3 * n // 4])


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
        self._live_tpm: float = 0.0      # tokens/min over the last few minutes
        self._is_live: bool = False       # show the "● LIVE" dot
        self._active_subagents: int = 0  # count of running Task-tool subagents
        # Ticker tape: newest-first. The paint loop walks them oldest→newest
        # so the newest item rides in from the right edge like a news ticker.
        self._ticker_items: list[TickerItem] = []
        self._ticker_offset: float = 0.0  # pixels scrolled so far; grows each frame
        # User toggle — default on, overridable via config; runtime flip
        # lives in the right-click menu.
        self._ticker_enabled: bool = bool(cfg.get("show_ticker", True))
        # "bars" (default) or "gauge" — the right-click menu toggles this and
        # persists to config.
        raw_mode = str(cfg.get("osd_view_mode", VIEW_MODE_BARS))
        self._view_mode: str = raw_mode if raw_mode in VIEW_MODES else VIEW_MODE_BARS

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

        # Ticker animation timer — advances _ticker_offset each frame. We
        # only start it when there are items to scroll so the OSD stays
        # CPU-idle during quiet periods.
        self._ticker_timer = QTimer(self)
        self._ticker_timer.setInterval(TICKER_FRAME_INTERVAL_MS)
        self._ticker_timer.timeout.connect(self._advance_ticker)

    # ------------------------------------------------------------------ API

    def update_stats(self, stats: UsageStats) -> None:
        """Apply the latest :class:`UsageStats` and trigger a repaint."""
        self._session_pct = max(0.0, min(1.0, float(stats.session_utilization)))
        self._weekly_pct = max(0.0, min(1.0, float(stats.weekly_utilization)))
        self._session_reset = int(stats.session_reset)
        self._weekly_reset = int(stats.weekly_reset)
        live = getattr(stats, "live_activity", None)
        if live is not None:
            self._is_live = bool(getattr(live, "is_live", False))
            self._live_tpm = float(getattr(live, "tokens_per_minute", 0.0) or 0.0)
        else:
            self._is_live = False
            self._live_tpm = 0.0
        self._active_subagents = max(0, int(getattr(stats, "active_subagent_count", 0) or 0))
        self._ticker_items = list(getattr(stats, "ticker_items", []) or [])
        # Only animate when the ticker is on, items exist, and the OSD is in
        # its full (non-minimized) form.
        if self._ticker_enabled and self._ticker_items and not self._minimized:
            if not self._ticker_timer.isActive():
                self._ticker_timer.start()
        else:
            self._ticker_timer.stop()
            self._ticker_offset = 0.0
        self.update()  # schedule a paintEvent

    def set_view_mode(self, mode: str) -> None:
        """Switch between bar and gauge rendering; resizes the OSD to match."""
        if mode not in VIEW_MODES or mode == self._view_mode:
            return
        self._view_mode = mode
        self._apply_size()
        # Gauge view has no ticker — stop the animation to save CPU.
        if mode == VIEW_MODE_GAUGE:
            self._ticker_timer.stop()
        elif self._ticker_enabled and self._ticker_items and not self._minimized:
            self._ticker_timer.start()
        self.update()

    def view_mode(self) -> str:
        return self._view_mode

    def set_ticker_enabled(self, enabled: bool) -> None:
        """Show/hide the ticker strip. Resizes the OSD to match."""
        enabled = bool(enabled)
        if enabled == self._ticker_enabled:
            return
        self._ticker_enabled = enabled
        self._apply_size()
        if not enabled:
            self._ticker_timer.stop()
            self._ticker_offset = 0.0
        elif self._ticker_items and not self._minimized:
            self._ticker_timer.start()
        self.update()

    def is_ticker_enabled(self) -> bool:
        return self._ticker_enabled

    def _advance_ticker(self) -> None:
        """One frame of ticker scroll — called by the animation timer."""
        self._ticker_offset += TICKER_SCROLL_PX_PER_SEC * (TICKER_FRAME_INTERVAL_MS / 1000.0)
        self.update()

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
        # Minimized view has no ticker — stop the animation to save CPU.
        if self._minimized:
            self._ticker_timer.stop()
        elif self._ticker_items:
            self._ticker_timer.start()
        self.update()

    # ------------------------------------------------------------- internals

    def _apply_size(self) -> None:
        """Resize the window to match ``_scale``, view mode, and chrome state."""
        width = int(BASE_WIDTH * self._scale)
        if self._view_mode == VIEW_MODE_GAUGE:
            # Gauge mode has no ticker — the reset line under each ring
            # already occupies that footer real estate.
            base = GAUGE_HEIGHT
        else:
            base = BASE_HEIGHT + (TICKER_STRIP_HEIGHT if self._ticker_enabled else 0)
        height = MINIMIZED_HEIGHT if self._minimized else int(base * self._scale)
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

        if self._view_mode == VIEW_MODE_GAUGE:
            self._paint_gauge(p, w, h)
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

    def _paint_gauge(self, p: QPainter, w: int, h: int) -> None:
        """Two circular-ring gauges (Session + Weekly) side-by-side.

        Each ring fills clockwise from 12 o'clock as utilisation rises. The
        ring colour tracks ``_bar_color`` so a turning-red session is just as
        alarming here as in bars mode.
        """
        s = self._scale
        radius = OSD_RADIUS * s

        # Background panel.
        bg = _hex_to_qcolor(self._theme["bg"], self._opacity)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # Two columns splitting the panel; each column is one gauge stack.
        col_w = w / 2
        ring_d = max(50.0, min(col_w * 0.58, 80 * s))
        ring_stroke = max(4.0, 7 * s)
        # Centre each ring inside its column, with room below for labels.
        for idx, (label, pct, reset_ts) in enumerate((
            ("Session", self._session_pct, self._session_reset),
            ("Weekly",  self._weekly_pct,  self._weekly_reset),
        )):
            cx = col_w * idx + col_w / 2
            cy = 12 * s + ring_d / 2
            fill_color = _bar_color(pct, self._theme)
            self._draw_ring(p, cx, cy, ring_d, ring_stroke, pct, fill_color)

            # Percentage text centred in the ring.
            pct_text = f"{int(pct * 100)}%"
            pct_font_pt = max(10, int(13 * s))
            p.setFont(QFont("monospace", pct_font_pt, QFont.Bold))
            p.setPen(_hex_to_qcolor(self._theme["text_primary"]))
            fm = p.fontMetrics()
            pct_w = fm.horizontalAdvance(pct_text)
            p.drawText(QPointF(cx - pct_w / 2, cy + fm.ascent() / 2 - 2 * s), pct_text)

            # Label + reset beneath the ring.
            label_y = cy + ring_d / 2 + 14 * s
            label_font_pt = max(8, int(9 * s))
            p.setFont(QFont("monospace", label_font_pt, QFont.Bold))
            p.setPen(_hex_to_qcolor(self._theme["text_primary"]))
            fm = p.fontMetrics()
            lw = fm.horizontalAdvance(label)
            p.drawText(QPointF(cx - lw / 2, label_y), label)

            reset_label = _format_reset_short(reset_ts)
            if reset_label:
                reset_font_pt = max(7, int(7.5 * s))
                p.setFont(QFont("monospace", reset_font_pt))
                p.setPen(_hex_to_qcolor(self._theme["text_dim"]))
                fm = p.fontMetrics()
                rw = fm.horizontalAdvance(reset_label)
                p.drawText(QPointF(cx - rw / 2, label_y + 12 * s), reset_label)

    def _draw_ring(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        diameter: float,
        stroke: float,
        fraction: float,
        fill_color: QColor,
    ) -> None:
        """Draw the track + filled-arc pair that make up one gauge."""
        from PySide6.QtGui import QPen
        track_pen = QPen(_hex_to_qcolor(self._theme["bar_track"], 0.7))
        track_pen.setWidthF(stroke)
        track_pen.setCapStyle(Qt.FlatCap)
        p.setPen(track_pen)
        p.setBrush(Qt.NoBrush)
        rect = QRectF(cx - diameter / 2, cy - diameter / 2, diameter, diameter)
        p.drawEllipse(rect)

        if fraction <= 0:
            return

        # Fill arc — Qt measures angles in sixteenths of a degree. 90° * 16
        # starts at 12 o'clock; a negative span sweeps clockwise as fraction
        # grows, matching how the bar version fills left→right.
        fill_pen = QPen(fill_color)
        fill_pen.setWidthF(stroke)
        fill_pen.setCapStyle(Qt.RoundCap)
        p.setPen(fill_pen)
        start_angle = 90 * 16
        span = -int(min(1.0, max(0.0, fraction)) * 360 * 16)
        p.drawArc(rect, start_angle, span)

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
        title_y = pad_y + 7 * s
        p.drawText(QPointF(pad_x, title_y), "CLAUDE")

        # Subagent rozet — only shown when > 0 so single-session users aren't
        # bothered by a permanent "0 agents" noise. Rendered just right of
        # CLAUDE in the theme's link colour to signal "active thing".
        if self._active_subagents > 0:
            title_w = p.fontMetrics().horizontalAdvance("CLAUDE")
            rozet = f"⚙ {self._active_subagents}"
            p.setPen(_hex_to_qcolor(self._theme["text_link"]))
            p.drawText(QPointF(pad_x + title_w + 6 * s, title_y), rozet)

        # Live indicator — only drawn when there's recent assistant activity.
        # Renders as `● LIVE 1.2k tok/min` right-aligned against the title.
        if self._is_live and self._live_tpm > 0:
            tpm = self._live_tpm
            tpm_text = f"{tpm / 1000:.1f}k" if tpm >= 1000 else f"{int(tpm)}"
            live_text = f"● LIVE {tpm_text} tok/min"
            live_width = p.fontMetrics().horizontalAdvance(live_text)
            live_x = w - pad_x - live_width
            # Green-ish per-theme accent; fallback covers older themes.
            p.setPen(_hex_to_qcolor(self._theme.get("live_indicator", "#4ade80")))
            p.drawText(QPointF(live_x, pad_y + 7 * s), live_text)

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

        # --- Ticker strip (below the weekly row) ---
        if self._ticker_enabled:
            ticker_y = y2 + 15 * s + bar_h + 6 * s
            self._draw_ticker(p, ticker_y, w, pad_x, s)

    def _draw_ticker(
        self,
        p: QPainter,
        y: float,
        w: int,
        pad_x: float,
        s: float,
    ) -> None:
        """Right-to-left scrolling tape of recent per-turn costs."""
        if not self._ticker_items:
            return

        # Tape geometry: clipped to the interior width so text doesn't spill
        # past the rounded corners of the OSD.
        tape_x = pad_x
        tape_w = max(0.0, w - 2 * pad_x)
        tape_h = 14 * s
        p.save()
        p.setClipRect(QRectF(tape_x, y - tape_h * 0.1, tape_w, tape_h * 1.2))

        # Monospace keeps item widths predictable as values change.
        font = QFont("monospace", max(7, int(7.5 * s)))
        p.setFont(font)
        fm = p.fontMetrics()
        sep_gap = int(14 * s)
        baseline = y + tape_h - 3 * s

        # Build display items oldest-first so the newest rides in from the
        # right edge as offset grows. Duplicated list makes seamless looping
        # cheap: as soon as the first copy fully scrolls off-screen, the
        # second is already visible at its tail.
        ordered = list(reversed(self._ticker_items))
        strings = [self._format_ticker_item(it) for it in ordered]
        widths = [fm.horizontalAdvance(s_) + sep_gap for s_ in strings]
        strip_width = sum(widths) or 1

        # x_start: the left edge of the first copy of the strip in absolute
        # coordinates. Subtract the scrolling offset (modulo strip_width) so
        # it drifts left indefinitely without integer overflow.
        x_start = tape_x + tape_w - (self._ticker_offset % strip_width)
        cost_colors = {
            "hot":    _hex_to_qcolor(self._theme["crit"]),
            "warm":   _hex_to_qcolor(self._theme["warn"]),
            "cool":   _hex_to_qcolor(self._theme["bar_blue"]),
            "dim":    _hex_to_qcolor(self._theme["text_dim"]),
        }
        thresholds = _ticker_quartile_thresholds(self._ticker_items)
        # Enough copies to cover the viewport even when the strip is short —
        # two copies only works when strip_width ≥ tape_w.
        copies = max(2, int(tape_w // strip_width) + 2)
        for repeat in range(copies):
            x = x_start + repeat * strip_width
            for item, text, width in zip(ordered, strings, widths):
                if x + width < tape_x:
                    x += width
                    continue
                if x > tape_x + tape_w:
                    break
                p.setPen(self._ticker_color_for(item, cost_colors, thresholds))
                p.drawText(QPointF(x, baseline), text)
                x += width

        p.restore()

    @staticmethod
    def _format_ticker_item(item: TickerItem) -> str:
        """Compact tape label: ``$0.156 ← Read · 2.3k``."""
        cost = item.cost_usd
        if cost >= 1.0:
            cost_text = f"${cost:.2f}"
        elif cost >= 0.01:
            cost_text = f"${cost:.3f}"
        else:
            cost_text = f"${cost:.4f}"
        tool = item.tool or "turn"
        out = item.output_tokens
        if out >= 1000:
            out_text = f"{out / 1000:.1f}k"
        else:
            out_text = str(out)
        return f"{cost_text} ← {tool} · {out_text}"

    @staticmethod
    def _ticker_color_for(
        item: TickerItem,
        palette: dict,
        thresholds: tuple[float, float, float],
    ) -> QColor:
        """Color each item by its quartile rank in the current buffer.

        Using relative thresholds instead of fixed dollar tiers keeps the
        tape visually informative across wildly different workflows —
        Haiku-only sessions and Opus tool-heavy sessions both show the full
        colour range. Cheapest 25% dim, next 25% blue, next 25% amber,
        top 25% red.
        """
        cool_thr, warm_thr, hot_thr = thresholds
        if item.cost_usd >= hot_thr:
            return palette["hot"]
        if item.cost_usd >= warm_thr:
            return palette["warm"]
        if item.cost_usd >= cool_thr:
            return palette["cool"]
        return palette["dim"]

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
