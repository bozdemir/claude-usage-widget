"""OSD overlay for macOS — always-on-top transparent widget in top-right corner."""

from datetime import datetime

import objc
from AppKit import (
    NSView, NSWindow,
    NSBackingStoreBuffered,
    NSColor, NSBezierPath, NSFont,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSAttributedString,
    NSScreen,
    NSFloatingWindowLevel,
    NSViewWidthSizable, NSViewHeightSizable,
    NSEvent,
)
from Foundation import NSMakeRect, NSMakePoint

from claude_usage.collector import UsageStats

try:
    from AppKit import NSWindowStyleMaskBorderless as _BORDERLESS
except ImportError:
    from AppKit import NSBorderlessWindowMask as _BORDERLESS  # type: ignore

try:
    from AppKit import (
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorIgnoresCycle,
    )
    _COLLECTION = (
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorIgnoresCycle
    )
except ImportError:
    _COLLECTION = 0


# Base OSD dimensions (at scale=1.0)
BASE_WIDTH = 260
BASE_HEIGHT = 100
OSD_MARGIN = 16
OSD_RADIUS = 12
OSD_BAR_HEIGHT = 6
OSD_BAR_RADIUS = 3
MINIMIZED_HEIGHT = 6

SCALE_MIN, SCALE_MAX, SCALE_STEP = 0.6, 2.0, 0.1

# Colors (r, g, b, a)
BG_RGBA        = (0.08, 0.08, 0.15, 0.75)
BAR_TRACK_RGBA = (0.25, 0.25, 0.32, 0.60)
TEXT_RGBA      = (0.88, 0.88, 0.92, 0.95)
DIM_RGBA       = (0.50, 0.50, 0.58, 0.75)
WARN_RGBA      = (0.92, 0.70, 0.05, 0.95)
CRIT_RGBA      = (0.94, 0.27, 0.27, 0.95)
BAR_BLUE_RGBA  = (0.36, 0.61, 0.84, 0.95)


def _bar_color(pct):
    if pct < 0.6:
        return BAR_BLUE_RGBA
    if pct < 0.85:
        return WARN_RGBA
    return CRIT_RGBA


def _ns_color(r, g, b, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


def _fill_rrect(x, y, w, h, r):
    """Fill a rounded rectangle."""
    r = min(r, w / 2, h / 2)
    if r < 0.5:
        NSBezierPath.fillRect_(NSMakeRect(x, y, w, h))
        return
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, y, w, h), r, r
    ).fill()


def _mono_font(size):
    try:
        return NSFont.monospacedSystemFontOfSize_weight_(size, 0.0)
    except AttributeError:
        return NSFont.fontWithName_size_("Menlo", size) or NSFont.systemFontOfSize_(size)


def _format_reset_short(reset_ts):
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


def _resize_window(win, scale, minimized):
    """Resize the window keeping the top-right corner anchored."""
    frame = win.frame()
    tr_x = frame.origin.x + frame.size.width
    tr_y = frame.origin.y + frame.size.height
    new_w = int(BASE_WIDTH * scale)
    new_h = MINIMIZED_HEIGHT if minimized else int(BASE_HEIGHT * scale)
    win.setFrame_display_animate_(
        NSMakeRect(tr_x - new_w, tr_y - new_h, new_w, new_h),
        True, False,
    )


class OSDView(NSView):
    """NSView subclass that renders the OSD overlay via AppKit drawing."""

    def initWithFrame_(self, frame):
        self = objc.super(OSDView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._session_pct = 0.0
        self._weekly_pct = 0.0
        self._session_reset = 0
        self._weekly_reset = 0
        self._minimized = False
        self._scale = 1.0
        self._opacity = 0.75
        self._drag_start_screen = None
        self._drag_start_win = None
        return self

    def isFlipped(self):
        return True  # top-left origin — matches Cairo coordinate space

    def acceptsFirstMouse_(self, event):
        return True

    # ------------------------------------------------------------------ drawing

    @objc.python_method
    def _draw_str(self, text, x, y, size, rgba):
        """Draw text; returns drawn width."""
        font = _mono_font(size)
        ns_str = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: font,
             NSForegroundColorAttributeName: _ns_color(*rgba)},
        )
        ns_str.drawAtPoint_(NSMakePoint(x, y))
        return ns_str.size().width

    @objc.python_method
    def _str_w(self, text, size):
        ns_str = NSAttributedString.alloc().initWithString_attributes_(
            text, {NSFontAttributeName: _mono_font(size)}
        )
        return ns_str.size().width

    @objc.python_method
    def _font_h(self, size):
        return _mono_font(size).boundingRectForFont().size.height

    def drawRect_(self, rect):
        w = self.bounds().size.width
        s = self._scale

        # Always clear to transparent first
        NSColor.clearColor().setFill()
        NSBezierPath.fillRect_(self.bounds())

        if self._minimized:
            _ns_color(*BAR_TRACK_RGBA).setFill()
            _fill_rrect(0, 0, w, MINIMIZED_HEIGHT, 3)
            if self._session_pct > 0:
                fw = max(w * min(self._session_pct, 1.0), 4)
                _ns_color(*_bar_color(self._session_pct)).setFill()
                _fill_rrect(0, 0, fw, MINIMIZED_HEIGHT, 3)
            return

        # Background
        _ns_color(BG_RGBA[0], BG_RGBA[1], BG_RGBA[2], self._opacity).setFill()
        _fill_rrect(0, 0, w, self.bounds().size.height, OSD_RADIUS * s)

        pad_x = 14 * s
        pad_y = 10 * s
        bar_h = OSD_BAR_HEIGHT * s
        bar_r = OSD_BAR_RADIUS * s
        bar_w = w - 2 * pad_x
        fl = 10 * s    # label font size
        fs = 7.5 * s   # small font size
        ft = 8 * s     # title font size
        lh = self._font_h(fl)
        th = self._font_h(ft)

        # Title
        self._draw_str("CLAUDE", pad_x, pad_y, ft, DIM_RGBA)

        # --- Session row ---
        y = pad_y + th + 4 * s
        pct_s = f"{int(self._session_pct * 100)}%"
        pct_w = self._str_w(pct_s, fl)
        self._draw_str("Session", pad_x, y, fl, TEXT_RGBA)
        self._draw_str(pct_s, w - pad_x - pct_w, y, fl, TEXT_RGBA)
        reset_s = _format_reset_short(self._session_reset)
        if reset_s:
            rw = self._str_w(reset_s, fs)
            sh = self._font_h(fs)
            self._draw_str(reset_s, w - pad_x - pct_w - 8 * s - rw,
                           y + (lh - sh) / 2, fs, DIM_RGBA)

        bar_y = y + lh + 3 * s
        _ns_color(*BAR_TRACK_RGBA).setFill()
        _fill_rrect(pad_x, bar_y, bar_w, bar_h, bar_r)
        if self._session_pct > 0:
            _ns_color(*_bar_color(self._session_pct)).setFill()
            _fill_rrect(pad_x, bar_y, max(bar_w * min(self._session_pct, 1.0), bar_h), bar_h, bar_r)

        # --- Weekly row ---
        y2 = bar_y + bar_h + 10 * s
        pct_w2 = self._str_w(f"{int(self._weekly_pct * 100)}%", fl)
        pct_s2 = f"{int(self._weekly_pct * 100)}%"
        self._draw_str("Weekly", pad_x, y2, fl, TEXT_RGBA)
        self._draw_str(pct_s2, w - pad_x - pct_w2, y2, fl, TEXT_RGBA)
        reset_w2 = _format_reset_short(self._weekly_reset)
        if reset_w2:
            rw = self._str_w(reset_w2, fs)
            sh = self._font_h(fs)
            self._draw_str(reset_w2, w - pad_x - pct_w2 - 8 * s - rw,
                           y2 + (lh - sh) / 2, fs, DIM_RGBA)

        bar_y2 = y2 + lh + 3 * s
        _ns_color(*BAR_TRACK_RGBA).setFill()
        _fill_rrect(pad_x, bar_y2, bar_w, bar_h, bar_r)
        if self._weekly_pct > 0:
            _ns_color(*_bar_color(self._weekly_pct)).setFill()
            _fill_rrect(pad_x, bar_y2, max(bar_w * min(self._weekly_pct, 1.0), bar_h), bar_h, bar_r)

    # ------------------------------------------------------------------ events

    def mouseDown_(self, event):
        loc = NSEvent.mouseLocation()
        self._drag_start_screen = (loc.x, loc.y)
        win = self.window()
        if win:
            origin = win.frame().origin
            self._drag_start_win = (origin.x, origin.y)

    def mouseUp_(self, event):
        self._drag_start_screen = None
        self._drag_start_win = None

    def mouseDragged_(self, event):
        if not self._drag_start_screen or not self._drag_start_win:
            return
        loc = NSEvent.mouseLocation()
        dx = loc.x - self._drag_start_screen[0]
        dy = loc.y - self._drag_start_screen[1]
        win = self.window()
        if win:
            win.setFrameOrigin_(NSMakePoint(
                self._drag_start_win[0] + dx,
                self._drag_start_win[1] + dy,
            ))

    def rightMouseDown_(self, event):
        self._minimized = not self._minimized
        win = self.window()
        if win:
            _resize_window(win, self._scale, self._minimized)
        self.setNeedsDisplay_(True)

    def scrollWheel_(self, event):
        if self._minimized:
            return
        delta = event.deltaY()
        direction = 1 if delta > 0 else (-1 if delta < 0 else 0)
        if not direction:
            return
        self._scale = max(SCALE_MIN, min(SCALE_MAX, self._scale + direction * SCALE_STEP))
        win = self.window()
        if win:
            _resize_window(win, self._scale, self._minimized)
        self.setNeedsDisplay_(True)


class UsageOverlay:
    """Manages the macOS borderless floating OSD window."""

    def __init__(self, config=None):
        cfg = config or {}
        scale = cfg.get("osd_scale", 1.0)
        opacity = cfg.get("osd_opacity", 0.75)

        w = int(BASE_WIDTH * scale)
        h = int(BASE_HEIGHT * scale)

        # Position: top-right of main screen visible area
        sv = NSScreen.mainScreen().visibleFrame()
        x = sv.origin.x + sv.size.width - w - OSD_MARGIN
        y = sv.origin.y + sv.size.height - h - OSD_MARGIN

        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h), _BORDERLESS, NSBackingStoreBuffered, False
        )
        self._win.setOpaque_(False)
        self._win.setBackgroundColor_(NSColor.clearColor())
        self._win.setLevel_(NSFloatingWindowLevel + 1)
        if _COLLECTION:
            self._win.setCollectionBehavior_(_COLLECTION)
        self._win.setIgnoresMouseEvents_(False)
        self._win.setHasShadow_(False)
        self._win.setAcceptsMouseMovedEvents_(True)

        self._view = OSDView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self._view._scale = scale
        self._view._opacity = opacity
        self._view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._win.setContentView_(self._view)

    def show_all(self):
        self._win.orderFront_(None)

    def hide(self):
        self._win.orderOut_(None)

    def set_opacity(self, value: float):
        self._view._opacity = max(0.15, min(1.0, value))
        self._view.setNeedsDisplay_(True)

    def update(self, stats: UsageStats):
        self._view._session_pct = stats.session_utilization
        self._view._weekly_pct = stats.weekly_utilization
        self._view._session_reset = stats.session_reset
        self._view._weekly_reset = stats.weekly_reset
        self._view.setNeedsDisplay_(True)
