# claude_usage/overlay.py
"""OSD overlay — always-on-top transparent widget in top-right corner."""

import math
from datetime import datetime
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gtk, Gdk, GLib

from claude_usage.collector import UsageStats


# ---------------------------------------------------------------------------
# Layout constants — all defined at scale=1.0 (one logical pixel = one unit).
# Every value used in _on_draw is multiplied by self._scale at draw time, so
# the widget stays proportional across the SCALE_MIN–SCALE_MAX range.
# ---------------------------------------------------------------------------

# Base OSD dimensions (at scale=1.0)
BASE_WIDTH = 260
BASE_HEIGHT = 100
OSD_MARGIN = 16        # Gap between the overlay and the screen edge (pixels)
OSD_RADIUS = 12        # Corner radius of the main background pill
OSD_BAR_HEIGHT = 6     # Height of each progress-bar track
OSD_BAR_RADIUS = 3     # Corner radius of each progress bar (half of height = capsule)
MINIMIZED_HEIGHT = 6   # Window height when minimized — matches bar height exactly

# Scroll-wheel scale limits and step size
SCALE_MIN = 0.6   # Smallest the overlay can shrink to (60 % of base size)
SCALE_MAX = 2.0   # Largest the overlay can grow to (200 % of base size)
SCALE_STEP = 0.1  # Scale change per scroll tick

# Colors — all RGBA tuples in 0.0–1.0 range used as *args to set_source_rgba()
BG_RGBA = (0.08, 0.08, 0.15, 0.75)         # Dark-blue background (alpha overridden by _opacity)
BAR_TRACK_RGBA = (0.25, 0.25, 0.32, 0.6)   # Empty bar track
BAR_BLUE_RGBA = (0.36, 0.61, 0.84, 0.95)   # Normal fill colour (< 60 % usage)
TEXT_RGBA = (0.88, 0.88, 0.92, 0.95)       # Primary text
DIM_RGBA = (0.50, 0.50, 0.58, 0.75)        # Muted/secondary text (title, reset times)
WARN_RGBA = (0.92, 0.70, 0.05, 0.95)       # Warning fill (60–85 % usage)
CRIT_RGBA = (0.94, 0.27, 0.27, 0.95)       # Critical fill (≥ 85 % usage)


def _bar_color(pct: float):
    """Return the correct RGBA bar colour for a given utilisation fraction (0.0–1.0)."""
    if pct < 0.6:
        return BAR_BLUE_RGBA
    if pct < 0.85:
        return WARN_RGBA
    return CRIT_RGBA


def _rounded_rect(cr, x, y, w, h, r):
    """Trace a rounded-rectangle path onto Cairo context *cr*.

    Cairo coordinate system: origin (0, 0) is the top-left of the drawing
    surface, x increases rightward, y increases downward.  Angles are in
    radians; arc() sweeps clockwise because y is flipped relative to the
    standard mathematical convention.

    The four arcs are drawn in clockwise order starting from the top-right
    corner so that close_path() produces a single closed shape that can be
    filled or stroked in one operation.
    """
    # Clamp radius to avoid artifacts on tiny dimensions
    r = min(r, w / 2, h / 2)
    if r < 0.5:
        # Radius too small to matter — fall back to a plain rectangle
        cr.rectangle(x, y, w, h)
        return
    cr.new_sub_path()
    # Top-right arc: centre (x+w-r, y+r), from -π/2 (top) clockwise to 0 (right)
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    # Bottom-right arc: centre (x+w-r, y+h-r), from 0 clockwise to π/2 (bottom)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    # Bottom-left arc: centre (x+r, y+h-r), from π/2 clockwise to π (left)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    # Top-left arc: centre (x+r, y+r), from π clockwise to 3π/2 (top again)
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
    """Borderless, always-on-top OSD overlay showing Claude token utilisation.

    The overlay is a GTK TOPLEVEL window rendered entirely via Cairo.  It has
    no window decorations and is placed in the top-right corner of the primary
    monitor by default.

    Interaction model
    -----------------
    - Scroll wheel (up/down): resize the overlay by adjusting ``_scale``.
    - Left-button drag: move the overlay to any screen position.
    - Right-click: toggle minimized state (full panel <-> thin progress strip).

    Scale system
    ------------
    All drawing dimensions are defined as base values (at ``scale=1.0``) and
    multiplied by ``_scale`` at draw time.  The GTK window is resized to match
    via ``_apply_size()``, so the window geometry always reflects the current
    scale.  This means a single set of layout constants drives both the Cairo
    drawing and the window size without any separate bookkeeping.

    Minimized state
    ---------------
    When minimized the window height is clamped to ``MINIMIZED_HEIGHT`` (6 px)
    regardless of scale, while the width continues to track the scaled
    ``BASE_WIDTH``.  The draw handler detects this state and renders only a
    thin capsule bar representing the current session utilisation instead of
    the full panel.
    """

    def __init__(self, config: dict = None):
        """Initialise the overlay window and connect GTK signals.

        Parameters
        ----------
        config:
            Optional dict from the plugin configuration file.  Recognised
            keys are ``osd_scale`` (float, default 1.0) and ``osd_opacity``
            (float, default 0.75).
        """
        # Current utilisation fractions (0.0–1.0) updated by update()
        self.session_pct = 0.0
        self.weekly_pct = 0.0
        # Unix timestamps for when each limit resets (0 = unknown)
        self.session_reset = 0
        self.weekly_reset = 0

        # Minimized flag — toggled by right-click; True renders the thin bar
        self._minimized = False

        # Drag state: both fields are set together on button-press and cleared
        # on button-release.  _drag_start is the pointer position at the moment
        # the drag began (in root/screen coordinates); _drag_win_start is the
        # window's top-left position at that same moment.  During motion events
        # the delta between the current pointer position and _drag_start is
        # added to _drag_win_start to produce the new window position, giving
        # smooth, flicker-free dragging without touching GTK's built-in
        # begin_move_drag() which requires a window manager.
        self._drag_start = None       # (x_root, y_root) at drag start
        self._drag_win_start = None   # (win_x, win_y) at drag start

        # Scale factor — multiplied by every base dimension before drawing.
        # Changing it resizes both the Cairo content and the GTK window.
        self._scale = (config or {}).get("osd_scale", 1.0)

        # Background alpha; the RGB channels of BG_RGBA are kept fixed while
        # this value replaces the alpha component so the user can dim the overlay
        # without affecting text/bar colours (which have their own alphas).
        self._opacity = (config or {}).get("osd_opacity", 0.75)

        # --- GTK window setup ---
        self._win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)

        # Request an RGBA visual so Cairo can render with a transparent background.
        # Without this the compositor will composite onto an opaque black surface
        # and alpha blending in the draw handler will have no visible effect.
        screen = self._win.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self._win.set_visual(visual)
        # app_paintable tells GTK not to draw its own background before firing
        # the "draw" signal, giving the draw handler full control of every pixel.
        self._win.set_app_paintable(True)

        self._win.set_title("")
        self._win.set_decorated(False)       # No title bar / frame
        self._win.set_keep_above(True)       # Float above all other windows
        self._win.set_skip_taskbar_hint(True)  # Hide from taskbar
        self._win.set_skip_pager_hint(True)    # Hide from workspace pager
        self._win.set_accept_focus(False)    # Never steal keyboard focus
        # NOTIFICATION hint prevents some WMs from applying their own shadows
        # or borders on top of the overlay.
        self._win.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        # resizable=True is required so that _apply_size() can freely change the
        # window dimensions; without this, resize() silently does nothing after
        # the first show.
        self._win.set_resizable(True)
        self._win.set_size_request(1, 1)    # Allow shrinking below default size
        init_w = int(BASE_WIDTH * self._scale)
        init_h = int(BASE_HEIGHT * self._scale)
        self._win.set_default_size(init_w, init_h)

        # Position in the top-right corner of the primary monitor.
        # get_primary_monitor() may return None on some multi-head setups, so
        # fall back to monitor 0.
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        self._win.move(geo.x + geo.width - init_w - OSD_MARGIN, geo.y + OSD_MARGIN)

        # Register for the pointer events needed by drag and scroll-to-scale.
        # POINTER_MOTION_MASK alone would fire on every pixel; in practice GTK
        # throttles it sufficiently for smooth dragging.
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
        """Make the overlay window and all its children visible."""
        self._win.show_all()

    def hide(self):
        """Hide the overlay window without destroying it."""
        self._win.hide()

    def set_opacity(self, value: float):
        """Set the background opacity, clamped to [0.15, 1.0].

        Only affects the background fill; text and bar colours retain their
        own alpha values so legibility is preserved even at low opacity.
        """
        self._opacity = max(0.15, min(1.0, value))
        self._win.queue_draw()

    def _current_size(self):
        """Return the (width, height) the window should have at the current scale."""
        w = int(BASE_WIDTH * self._scale)
        h = int(BASE_HEIGHT * self._scale)
        return w, h

    def _apply_size(self):
        """Resize the GTK window to match the current scale and minimized state.

        When minimized, the height is fixed at MINIMIZED_HEIGHT regardless of
        scale so the thin bar is always a consistent 6-pixel strip.  The width
        still tracks the scale so the bar spans the same horizontal space as
        the full panel would.
        """
        if self._minimized:
            # Keep width proportional to scale; height is the fixed thin-bar value
            w = int(BASE_WIDTH * self._scale)
            self._win.resize(w, MINIMIZED_HEIGHT)
        else:
            w, h = self._current_size()
            self._win.resize(w, h)

    def _on_scroll(self, widget, event):
        """Handle scroll-wheel events to zoom the overlay in or out.

        Scroll up increases _scale; scroll down decreases it.  Both discrete
        (button-style) and smooth (touchpad) scroll events are handled.
        After clamping the new scale to [SCALE_MIN, SCALE_MAX], _apply_size()
        resizes the window and queue_draw() triggers a redraw at the new scale.
        Scrolling while minimized is intentionally ignored — the thin bar has
        no meaningful content to resize.
        """
        if self._minimized:
            return

        # Normalise to direction: +1 = grow, -1 = shrink, 0 = no change
        direction = 0
        if event.direction == Gdk.ScrollDirection.UP:
            direction = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            direction = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            # Smooth scroll delivers fractional deltas; dy > 0 means downward
            _, dx, dy = event.get_scroll_deltas()
            if abs(dy) > 0.01:
                direction = -1 if dy > 0 else 1
        if direction == 0:
            return

        self._scale = max(SCALE_MIN, min(SCALE_MAX, self._scale + direction * SCALE_STEP))
        self._apply_size()
        self._win.queue_draw()

    def _on_button_press(self, widget, event):
        """Handle mouse button presses for drag initiation and minimize toggle.

        Button 1 (left): records the pointer's root-coordinate position and
        the window's current position so that _on_motion() can compute the
        correct new window position as the pointer moves.

        Button 3 (right): toggles the minimized flag, resizes the window to
        match, and queues a redraw so the correct view is rendered immediately.
        """
        if event.button == 1:
            # Snapshot both the pointer position and the window origin so the
            # drag delta can be applied cleanly in _on_motion().
            self._drag_start = (event.x_root, event.y_root)
            pos = self._win.get_position()
            self._drag_win_start = (pos[0], pos[1])
        elif event.button == 3:
            self._minimized = not self._minimized
            self._apply_size()
            self._win.queue_draw()

    def _on_button_release(self, widget, event):
        """Clear drag state when the left button is released."""
        if event.button == 1:
            # Clearing _drag_start is enough; _on_motion checks it before moving
            self._drag_start = None

    def _on_motion(self, widget, event):
        """Move the window while the left button is held down (drag-to-move).

        The drag implementation uses absolute root (screen) coordinates rather
        than window-relative coordinates to avoid the compounding errors that
        occur when the window itself moves beneath the pointer.  The new window
        position is always ``_drag_win_start + delta``, never an incremental
        step, so the overlay tracks the pointer precisely even at low frame rates.
        """
        if self._drag_start:
            # delta from the press origin in screen coordinates
            dx = event.x_root - self._drag_start[0]
            dy = event.y_root - self._drag_start[1]
            self._win.move(
                int(self._drag_win_start[0] + dx),
                int(self._drag_win_start[1] + dy),
            )

    def _on_draw(self, widget, cr):
        """Cairo draw handler — renders the entire overlay surface.

        Cairo coordinate system recap
        ------------------------------
        - Origin (0, 0) is the top-left of the allocated widget area.
        - x increases to the right; y increases downward.
        - Coordinates are in device pixels (already scaled by the monitor's
          HiDPI factor by GTK/Cairo before this handler is called).
        - All layout values are multiplied by ``s = self._scale`` here to
          implement the user-controlled zoom; the base constants are
          intentionally written at scale=1.0 so the code reads naturally.

        Paint order
        -----------
        1. Clear to fully transparent (OPERATOR_SOURCE replaces every pixel).
        2. If minimized: draw only the thin progress capsule and return early.
        3. Otherwise: background pill, title, session row, weekly row.

        Text right-alignment
        --------------------
        Cairo's ``text_extents()`` returns the bounding box of a string at the
        current font size.  To right-align text at position ``right_x``, the
        move_to x coordinate is ``right_x - ext.width``.
        """
        import cairo as _cairo

        # Dimensions of the allocated drawing area in device pixels
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        # Convenience alias used throughout to scale base constants
        s = self._scale

        # --- Step 1: clear to fully transparent ---
        # OPERATOR_SOURCE writes the source colour directly, ignoring whatever
        # was previously on the surface.  This is necessary because GTK may
        # leave stale pixels from a previous frame; without clearing, rounded
        # corners and transparent backgrounds would show ghost artefacts.
        cr.set_operator(_cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)  # Fully transparent black
        cr.paint()
        # Switch back to normal alpha compositing for everything that follows
        cr.set_operator(_cairo.OPERATOR_OVER)

        # --- Step 2: minimized state — render only a thin session bar ---
        if self._minimized:
            # Draw the track (empty portion) across the full window width
            _rounded_rect(cr, 0, 0, w, h, 3)
            cr.set_source_rgba(*BAR_TRACK_RGBA)
            cr.fill()
            if self.session_pct > 0:
                # Fill width is proportional to session_pct, with a 4 px minimum
                # so the bar is always visible even at near-zero usage
                fill_w = max(w * min(self.session_pct, 1.0), 4)
                _rounded_rect(cr, 0, 0, fill_w, h, 3)
                cr.set_source_rgba(*_bar_color(self.session_pct))
                cr.fill()
            return  # Skip the full-panel rendering below

        # --- Step 3: full panel ---

        # Background pill — opacity comes from _opacity so the user can dim
        # the background without washing out the text or bar colours
        bg = BG_RGBA[:3] + (self._opacity,)
        cr.set_source_rgba(*bg)
        _rounded_rect(cr, 0, 0, w, h, OSD_RADIUS * s)
        cr.fill()

        # Pre-compute all scaled layout values once to avoid repeating * s
        pad_x = 14 * s      # Horizontal padding inside the background pill
        pad_y = 10 * s      # Vertical padding at the top
        bar_h = OSD_BAR_HEIGHT * s
        bar_r = OSD_BAR_RADIUS * s
        bar_w = w - 2 * pad_x   # Bar spans the full inner width
        font_label = 10 * s     # Row label / percentage font size
        font_small = 7.5 * s    # Reset-time annotation font size
        font_title = 8 * s      # "CLAUDE" header font size

        # Title — dimmed monospace label at the very top
        cr.select_font_face("monospace", _cairo.FONT_SLANT_NORMAL, _cairo.FONT_WEIGHT_NORMAL)
        cr.set_source_rgba(*DIM_RGBA)
        cr.set_font_size(font_title)
        # move_to sets the text baseline origin; +6*s lifts it below pad_y
        cr.move_to(pad_x, pad_y + 6 * s)
        cr.show_text("CLAUDE")

        # --- Session row ---
        # y is the baseline for the row's label and percentage text
        y = pad_y + 16 * s
        session_pct_i = int(self.session_pct * 100)  # Display as integer percent
        session_reset = _format_reset_short(self.session_reset)

        # "Session" label — left-aligned at pad_x, baseline at y+9*s
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        cr.move_to(pad_x, y + 9 * s)
        cr.show_text("Session")

        # Reset time — right-aligned, placed just to the left of the percentage.
        # The percentage width is measured first so the two strings are spaced
        # consistently: [reset_time]  [percentage]  [pad_x]
        if session_reset:
            cr.set_font_size(font_small)
            cr.set_source_rgba(*DIM_RGBA)
            reset_ext = cr.text_extents(session_reset)
            # Measure the percentage at its own font size to compute the gap
            cr.set_font_size(font_label)
            pct_text = f"{session_pct_i}%"
            pct_ext = cr.text_extents(pct_text)
            # Place reset text so its right edge is 8*s to the left of the percentage
            reset_x = w - pad_x - pct_ext.width - 8 * s - reset_ext.width
            cr.set_font_size(font_small)
            cr.move_to(reset_x, y + 9 * s)
            cr.show_text(session_reset)

        # Percentage — right-aligned at the right edge of the inner area
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        pct_text = f"{session_pct_i}%"
        ext = cr.text_extents(pct_text)
        # Subtract ext.width from the right edge so the text's right side
        # aligns exactly with (w - pad_x)
        cr.move_to(w - pad_x - ext.width, y + 9 * s)
        cr.show_text(pct_text)

        # Progress bar track and fill — drawn below the text row
        bar_y = y + 15 * s  # Vertical position of the bar's top edge
        cr.set_source_rgba(*BAR_TRACK_RGBA)
        _rounded_rect(cr, pad_x, bar_y, bar_w, bar_h, bar_r)
        cr.fill()
        if self.session_pct > 0:
            # Minimum fill width = bar_h so even 1 % is visible as a small circle
            fill_w = max(bar_w * min(self.session_pct, 1.0), bar_h)
            cr.set_source_rgba(*_bar_color(self.session_pct))
            _rounded_rect(cr, pad_x, bar_y, fill_w, bar_h, bar_r)
            cr.fill()

        # --- Weekly row ---
        # Positioned below the session bar with a 10*s gap
        y2 = bar_y + bar_h + 10 * s
        weekly_pct_i = int(self.weekly_pct * 100)
        weekly_reset = _format_reset_short(self.weekly_reset)

        # "Weekly" label
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        cr.move_to(pad_x, y2 + 9 * s)
        cr.show_text("Weekly")

        # Reset time — same right-alignment logic as the session row
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

        # Percentage right-aligned
        cr.set_source_rgba(*TEXT_RGBA)
        cr.set_font_size(font_label)
        pct_text = f"{weekly_pct_i}%"
        ext = cr.text_extents(pct_text)
        cr.move_to(w - pad_x - ext.width, y2 + 9 * s)
        cr.show_text(pct_text)

        # Progress bar track and fill
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
        """Refresh displayed values from a UsageStats snapshot and redraw.

        Parameters
        ----------
        stats:
            Latest usage snapshot from the collector.  Utilisation values are
            fractions in 0.0–1.0; reset values are Unix timestamps.
        """
        self.session_pct = stats.session_utilization
        self.weekly_pct = stats.weekly_utilization
        self.session_reset = stats.session_reset
        self.weekly_reset = stats.weekly_reset
        self._win.queue_draw()
