# claude_usage/overlay.py
"""OSD overlay — always-on-top transparent widget in top-right corner."""

import math
from datetime import datetime
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gtk, Gdk, GLib

from claude_usage.collector import UsageStats


# Base OSD dimensions (at scale=1.0)
BASE_WIDTH = 260
BASE_HEIGHT = 100
OSD_MARGIN = 16
OSD_RADIUS = 12
OSD_BAR_HEIGHT = 6
OSD_BAR_RADIUS = 3
MINIMIZED_HEIGHT = 6

# Scale limits
SCALE_MIN = 0.6
SCALE_MAX = 2.0
SCALE_STEP = 0.1

# Colors
BG_RGBA = (0.08, 0.08, 0.15, 0.75)
BAR_TRACK_RGBA = (0.25, 0.25, 0.32, 0.6)
BAR_BLUE_RGBA = (0.36, 0.61, 0.84, 0.95)
TEXT_RGBA = (0.88, 0.88, 0.92, 0.95)
DIM_RGBA = (0.50, 0.50, 0.58, 0.75)
WARN_RGBA = (0.92, 0.70, 0.05, 0.95)
CRIT_RGBA = (0.94, 0.27, 0.27, 0.95)


def _bar_color(pct: float):
    if pct < 0.6:
        return BAR_BLUE_RGBA
    if pct < 0.85:
        return WARN_RGBA
    return CRIT_RGBA


def _rounded_rect(cr, x, y, w, h, r):
    # Clamp radius to avoid artifacts on tiny dimensions
    r = min(r, w / 2, h / 2)
    if r < 0.5:
        cr.rectangle(x, y, w, h)
        return
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _format_reset_short(reset_ts: int) -> str:
    """Compact reset label: '2h 31m' or 'Mon 16:00'."""
    if reset_ts <= 0:
        return ""
    now = datetime.now().timestamp()
    remaining = int(reset_ts - now)
    if remaining <= 0:
        return "soon"
    hours, remainder = divmod(remaining, 3600)
    minutes = remainder // 60
    if hours < 24:
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    dt = datetime.fromtimestamp(reset_ts)
    return dt.strftime("%a %H:%M")


class UsageOverlay:
    """Borderless OSD overlay in the top-right corner.

    Scroll wheel to resize. Left-drag to move. Right-click to minimize/restore.
    """

    def __init__(self, config: dict = None):
        self.session_pct = 0.0
        self.weekly_pct = 0.0
        self.session_reset = 0
        self.weekly_reset = 0
        self._minimized = False
        self._drag_start = None
        self._drag_win_start = None
        self._scale = (config or {}).get("osd_scale", 1.0)
        self._opacity = (config or {}).get("osd_opacity", 0.75)

        self._win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)

        screen = self._win.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self._win.set_visual(visual)
        self._win.set_app_paintable(True)

        self._win.set_title("")
        self._win.set_decorated(False)
        self._win.set_keep_above(True)
        self._win.set_skip_taskbar_hint(True)
        self._win.set_skip_pager_hint(True)
        self._win.set_accept_focus(False)
        self._win.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        # Must allow resizing for scroll-to-scale and minimize/restore
        self._win.set_resizable(True)
        self._win.set_size_request(1, 1)
        init_w = int(BASE_WIDTH * self._scale)
        init_h = int(BASE_HEIGHT * self._scale)
        self._win.set_default_size(init_w, init_h)

        # Position top-right
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        self._win.move(geo.x + geo.width - init_w - OSD_MARGIN, geo.y + OSD_MARGIN)

        self._win.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK
        )
        self._win.connect("draw", self._on_draw)
        self._win.connect("button-press-event", self._on_button_press)
        self._win.connect("button-release-event", self._on_button_release)
        self._win.connect("motion-notify-event", self._on_motion)
        self._win.connect("scroll-event", self._on_scroll)

    def show_all(self):
        self._win.show_all()

    def hide(self):
        self._win.hide()

    def set_opacity(self, value: float):
        self._opacity = max(0.15, min(1.0, value))
        self._win.queue_draw()

    def _current_size(self):
        w = int(BASE_WIDTH * self._scale)
        h = int(BASE_HEIGHT * self._scale)
        return w, h

    def _apply_size(self):
        if self._minimized:
            w = int(BASE_WIDTH * self._scale)
            self._win.resize(w, MINIMIZED_HEIGHT)
        else:
            w, h = self._current_size()
            self._win.resize(w, h)

    def _on_scroll(self, widget, event):
        if self._minimized:
            return

        # Determine scroll direction (handle both discrete and smooth scrolling)
        direction = 0  # -1 = down, +1 = up
        if event.direction == Gdk.ScrollDirection.UP:
            direction = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            direction = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dx, dy = event.get_scroll_deltas()
            if abs(dy) > 0.01:
                direction = -1 if dy > 0 else 1
        if direction == 0:
            return

        self._scale = max(SCALE_MIN, min(SCALE_MAX, self._scale + direction * SCALE_STEP))
        self._apply_size()
        self._win.queue_draw()

    def _on_button_press(self, widget, event):
        if event.button == 1:
            self._drag_start = (event.x_root, event.y_root)
            pos = self._win.get_position()
            self._drag_win_start = (pos[0], pos[1])
        elif event.button == 3:
            self._minimized = not self._minimized
            self._apply_size()
            self._win.queue_draw()

    def _on_button_release(self, widget, event):
        if event.button == 1:
            self._drag_start = None

    def _on_motion(self, widget, event):
        if self._drag_start:
            dx = event.x_root - self._drag_start[0]
            dy = event.y_root - self._drag_start[1]
            self._win.move(
                int(self._drag_win_start[0] + dx),
                int(self._drag_win_start[1] + dy),
            )

    def _on_draw(self, widget, cr):
        import cairo as _cairo

        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        s = self._scale

        # Clear to fully transparent
        cr.set_operator(_cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(_cairo.OPERATOR_OVER)

        if self._minimized:
            # Thin bar showing session usage
            _rounded_rect(cr, 0, 0, w, h, 3)
            cr.set_source_rgba(*BAR_TRACK_RGBA)
            cr.fill()
            if self.session_pct > 0:
                fill_w = max(w * min(self.session_pct, 1.0), 4)
                _rounded_rect(cr, 0, 0, fill_w, h, 3)
                cr.set_source_rgba(*_bar_color(self.session_pct))
                cr.fill()
            return

        # Background (opacity controlled by user)
        bg = BG_RGBA[:3] + (self._opacity,)
        cr.set_source_rgba(*bg)
        _rounded_rect(cr, 0, 0, w, h, OSD_RADIUS * s)
        cr.fill()

        pad_x = 14 * s
        pad_y = 10 * s
        bar_h = OSD_BAR_HEIGHT * s
        bar_r = OSD_BAR_RADIUS * s
        bar_w = w - 2 * pad_x
        font_label = 10 * s
        font_small = 7.5 * s
        font_title = 8 * s

        # Title
        cr.select_font_face("monospace", _cairo.FONT_SLANT_NORMAL, _cairo.FONT_WEIGHT_NORMAL)
        cr.set_source_rgba(*DIM_RGBA)
        cr.set_font_size(font_title)
        cr.move_to(pad_x, pad_y + 6 * s)
        cr.show_text("CLAUDE")

        # --- Session row ---
        y = pad_y + 16 * s
        session_pct_i = int(self.session_pct * 100)
        session_reset = _format_reset_short(self.session_reset)

        # "Session" label
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        cr.move_to(pad_x, y + 9 * s)
        cr.show_text("Session")

        # Reset time — right-aligned, before percentage
        if session_reset:
            cr.set_font_size(font_small)
            cr.set_source_rgba(*DIM_RGBA)
            reset_ext = cr.text_extents(session_reset)
            # Percentage will be at far right, reset time just before it
            cr.set_font_size(font_label)
            pct_text = f"{session_pct_i}%"
            pct_ext = cr.text_extents(pct_text)
            reset_x = w - pad_x - pct_ext.width - 8 * s - reset_ext.width
            cr.set_font_size(font_small)
            cr.move_to(reset_x, y + 9 * s)
            cr.show_text(session_reset)

        # Percentage right-aligned
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        pct_text = f"{session_pct_i}%"
        ext = cr.text_extents(pct_text)
        cr.move_to(w - pad_x - ext.width, y + 9 * s)
        cr.show_text(pct_text)

        # Bar
        bar_y = y + 15 * s
        cr.set_source_rgba(*BAR_TRACK_RGBA)
        _rounded_rect(cr, pad_x, bar_y, bar_w, bar_h, bar_r)
        cr.fill()
        if self.session_pct > 0:
            fill_w = max(bar_w * min(self.session_pct, 1.0), bar_h)
            cr.set_source_rgba(*_bar_color(self.session_pct))
            _rounded_rect(cr, pad_x, bar_y, fill_w, bar_h, bar_r)
            cr.fill()

        # --- Weekly row ---
        y2 = bar_y + bar_h + 10 * s
        weekly_pct_i = int(self.weekly_pct * 100)
        weekly_reset = _format_reset_short(self.weekly_reset)

        # "Weekly" label
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        cr.move_to(pad_x, y2 + 9 * s)
        cr.show_text("Weekly")

        # Reset time
        if weekly_reset:
            cr.set_font_size(font_small)
            cr.set_source_rgba(*DIM_RGBA)
            reset_ext = cr.text_extents(weekly_reset)
            cr.set_font_size(font_label)
            pct_text = f"{weekly_pct_i}%"
            pct_ext = cr.text_extents(pct_text)
            reset_x = w - pad_x - pct_ext.width - 8 * s - reset_ext.width
            cr.set_font_size(font_small)
            cr.move_to(reset_x, y2 + 9 * s)
            cr.show_text(weekly_reset)

        # Percentage
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        pct_text = f"{weekly_pct_i}%"
        ext = cr.text_extents(pct_text)
        cr.move_to(w - pad_x - ext.width, y2 + 9 * s)
        cr.show_text(pct_text)

        # Bar
        bar_y2 = y2 + 15 * s
        cr.set_source_rgba(*BAR_TRACK_RGBA)
        _rounded_rect(cr, pad_x, bar_y2, bar_w, bar_h, bar_r)
        cr.fill()
        if self.weekly_pct > 0:
            fill_w = max(bar_w * min(self.weekly_pct, 1.0), bar_h)
            cr.set_source_rgba(*_bar_color(self.weekly_pct))
            _rounded_rect(cr, pad_x, bar_y2, fill_w, bar_h, bar_r)
            cr.fill()

    def update(self, stats: UsageStats):
        self.session_pct = stats.session_utilization
        self.weekly_pct = stats.weekly_utilization
        self.session_reset = stats.session_reset
        self.weekly_reset = stats.weekly_reset
        self._win.queue_draw()
