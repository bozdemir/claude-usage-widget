"""OSD overlay for macOS — always-on-top transparent widget in top-right corner.

This module creates a borderless, always-on-top NSWindow that floats over every
Space and every full-screen app.  All drawing is done with AppKit (NSBezierPath /
NSAttributedString) inside an NSView subclass, so there is no external dependency
on Cairo or Qt.
"""

from datetime import datetime
from typing import Any, Optional

import objc
from AppKit import (
    NSAttributedString,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSScreen,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindow,
)
from Foundation import NSMakePoint, NSMakeRect

from claude_usage.collector import UsageStats

# Type alias for (red, green, blue, alpha) colour tuples — all components in [0, 1].
RGBA = tuple[float, float, float, float]

# ---------------------------------------------------------------------------
# Style-mask compatibility shim
# ---------------------------------------------------------------------------
# The "borderless" style-mask constant was renamed in the macOS 10.12 SDK.
# NSWindowStyleMaskBorderless is the modern name; NSBorderlessWindowMask is the
# legacy alias kept for older PyObjC builds.  Both resolve to the integer 0.
try:
    from AppKit import NSWindowStyleMaskBorderless as _BORDERLESS
except ImportError:
    from AppKit import NSBorderlessWindowMask as _BORDERLESS  # type: ignore

# ---------------------------------------------------------------------------
# Collection-behavior flags
# ---------------------------------------------------------------------------
# NSWindowCollectionBehavior controls how a window interacts with Spaces,
# Mission Control, and the Cmd-Tab / window-cycle features.
#
#   CanJoinAllSpaces  — the window appears on every virtual desktop (Space),
#                       including the one shown in full-screen apps.  Without
#                       this the overlay disappears whenever the user switches
#                       Spaces.
#
#   Stationary        — the window does not participate in the "push aside"
#                       animation when Mission Control is invoked; it stays
#                       pinned at its current position on screen.
#
#   IgnoresCycle      — hides the window from the Cmd-` (cycle through windows
#                       of current app) and from the Exposé/App Exposé window
#                       picker.  The overlay is a HUD, not a document window,
#                       so it should be invisible to normal window management.
#
# All three flags are OR-ed together into a single integer bitmask.
# The try/except guards against very old PyObjC builds that lack these symbols.
try:
    from AppKit import (
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorIgnoresCycle,
    )
    _COLLECTION: int = (
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorIgnoresCycle
    )
except ImportError:
    _COLLECTION: int = 0  # fall back to default behavior; overlay may vanish on Space switch


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

BASE_WIDTH:  int = 260   # base OSD width at scale 1.0 (points)
BASE_HEIGHT: int = 100   # base OSD height at scale 1.0 (points)
OSD_MARGIN:  int = 16    # gap between the overlay and the screen edge (points)
OSD_RADIUS:  int = 12    # corner radius of the background pill
OSD_BAR_HEIGHT: int = 6  # height of each progress bar track
OSD_BAR_RADIUS: int = 3  # corner radius of progress bar caps
MINIMIZED_HEIGHT: int = 6  # height of the overlay when collapsed to a thin bar

SCALE_MIN:  float = 0.6   # minimum scroll-wheel zoom
SCALE_MAX:  float = 2.0   # maximum scroll-wheel zoom
SCALE_STEP: float = 0.1   # zoom increment per scroll tick

# ---------------------------------------------------------------------------
# Color palette — all values are normalized floats in [0, 1], stored as
# (red, green, blue, alpha) tuples so they can be unpacked directly into
# NSColor.colorWithCalibratedRed_green_blue_alpha_().
# ---------------------------------------------------------------------------
BG_RGBA:        RGBA = (0.08, 0.08, 0.15, 0.75)  # dark translucent background
BAR_TRACK_RGBA: RGBA = (0.25, 0.25, 0.32, 0.60)  # empty portion of progress bar
TEXT_RGBA:      RGBA = (0.88, 0.88, 0.92, 0.95)   # primary label text
DIM_RGBA:       RGBA = (0.50, 0.50, 0.58, 0.75)   # secondary / dimmed text
WARN_RGBA:      RGBA = (0.92, 0.70, 0.05, 0.95)   # amber warning (60-85% usage)
CRIT_RGBA:      RGBA = (0.94, 0.27, 0.27, 0.95)   # red critical (>85% usage)
BAR_BLUE_RGBA:  RGBA = (0.36, 0.61, 0.84, 0.95)   # blue normal (<60% usage)


def _bar_color(pct: float) -> RGBA:
    """Return the RGBA tuple for a progress bar fill given a usage fraction.

    Thresholds:
        < 0.60  -- blue (normal)
        < 0.85  -- amber (warning)
        >= 0.85 -- red (critical)
    """
    if pct < 0.6:
        return BAR_BLUE_RGBA
    if pct < 0.85:
        return WARN_RGBA
    return CRIT_RGBA


def _ns_color(r: float, g: float, b: float, a: float = 1.0) -> NSColor:
    """Construct an NSColor from normalized RGBA floats.

    Uses the "calibrated" color space (sRGB-ish), which is appropriate for
    UI elements rendered in a window with a standard display profile.
    """
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


def _fill_rrect(x: float, y: float, w: float, h: float, r: float) -> None:
    """Fill a rounded rectangle using the current NSBezierPath fill color.

    Args:
        x, y: Origin in the current coordinate system.
        w, h: Width and height of the rectangle.
        r:    Corner radius.  Clamped to half the shorter side to prevent
              distortion on very small rectangles (e.g. thin progress bars).
    """
    r = min(r, w / 2, h / 2)
    if r < 0.5:
        # Radius too small to matter; skip the curve math and use a plain rect.
        NSBezierPath.fillRect_(NSMakeRect(x, y, w, h))
        return
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, y, w, h), r, r,
    ).fill()


def _mono_font(size: float) -> NSFont:
    """Return the best available monospaced system font at the given point size.

    Preference order:
        1. monospacedSystemFontOfSize_weight_  -- SF Mono (macOS 10.15+).
        2. Menlo                               -- bundled monospaced font.
        3. systemFontOfSize_                   -- proportional fallback; unlikely
                                                  to be reached in practice.
    """
    try:
        return NSFont.monospacedSystemFontOfSize_weight_(size, 0.0)
    except AttributeError:
        return NSFont.fontWithName_size_("Menlo", size) or NSFont.systemFontOfSize_(size)


def _format_reset_short(reset_ts: float) -> str:
    """Format the time remaining until a usage reset as a compact string.

    Args:
        reset_ts: Unix timestamp of the upcoming reset, or 0 if unknown.

    Returns:
        ""           -- when *reset_ts* is 0 (no information available).
        "soon"       -- when the reset time is in the past or imminent.
        "Xh Ym"     -- when the reset is within 24 hours.
        "Day HH:MM" -- when the reset is more than 24 hours away.
    """
    if reset_ts <= 0:
        return ""
    remaining: int = int(reset_ts - datetime.now().timestamp())
    if remaining <= 0:
        return "soon"
    hours, rem = divmod(remaining, 3600)
    minutes: int = rem // 60
    if hours < 24:
        return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
    return datetime.fromtimestamp(reset_ts).strftime("%a %H:%M")


def _resize_window(win: NSWindow, scale: float, minimized: bool) -> None:
    """Resize the NSWindow while keeping its top-right corner anchored.

    When the user zooms in/out or toggles the minimized state the window size
    changes.  Naively setting a new frame would anchor the bottom-left corner,
    which makes the overlay jump around the screen.  Instead we:

        1. Read the current top-right corner (tr_x, tr_y) from the existing
           frame.  NSWindow.frame() is always in screen coordinates with the
           origin at the bottom-left of the main display (Quartz / CoreGraphics
           convention -- y increases upward).
        2. Compute the new width/height from scale and minimized state.
        3. Set the frame origin so that (origin.x + new_w, origin.y + new_h)
           equals the saved top-right corner.
    """
    frame = win.frame()
    # Compute the invariant top-right corner in screen coordinates.
    tr_x: float = frame.origin.x + frame.size.width
    tr_y: float = frame.origin.y + frame.size.height
    new_w: int = int(BASE_WIDTH * scale)
    new_h: int = MINIMIZED_HEIGHT if minimized else int(BASE_HEIGHT * scale)
    # Derive the new bottom-left origin so that the top-right stays fixed.
    win.setFrame_display_animate_(
        NSMakeRect(tr_x - new_w, tr_y - new_h, new_w, new_h),
        True,   # redraw the window content immediately
        False,  # no animation; size change should feel instant
    )


class OSDView(NSView):
    """NSView subclass that renders the OSD overlay via AppKit drawing.

    Coordinate system note — isFlipped
    -----------------------------------
    By default NSView uses a *flipped-off* (Cartesian) coordinate system where
    the origin is at the bottom-left and y increases upward.  This is
    unintuitive for UI layout where you typically think top-to-bottom.

    Overriding isFlipped() to return True switches to a *flipped* coordinate
    system where the origin is at the top-left and y increases downward — the
    same convention used by UIKit on iOS, most web layout engines, and Cairo.
    All drawRect_ calculations in this class therefore use top-left origins and
    add positive y offsets to move downward.

    ObjC method naming convention
    --------------------------------
    PyObjC exposes Objective-C selectors as Python method names by replacing
    every colon (:) in the selector with an underscore (_).  For example:

        ObjC selector                    Python method name
        ─────────────────────────────── ─────────────────────────────────
        initWithFrame:                   initWithFrame_
        setFrame:display:animate:        setFrame_display_animate_
        colorWithCalibratedRed:green:    colorWithCalibratedRed_green_
          blue:alpha:                      blue_alpha_

    Methods decorated with @objc.python_method are *not* exposed to the ObjC
    runtime at all; they are plain Python helpers called only from Python code.
    This avoids selector-name clashes and is the correct pattern for internal
    helper methods on NSView subclasses.
    """

    def initWithFrame_(self, frame):
        """Designated initializer.  Calls NSView's initWithFrame_ via super."""
        self = objc.super(OSDView, self).initWithFrame_(frame)
        if self is None:
            return None
        # Internal state — all mutable at runtime by UsageOverlay.update().
        self._session_pct = 0.0     # session usage fraction [0, 1]
        self._weekly_pct  = 0.0     # weekly usage fraction  [0, 1]
        self._session_reset = 0     # Unix timestamp of next session reset
        self._weekly_reset  = 0     # Unix timestamp of next weekly reset
        self._minimized = False     # True while collapsed to the thin-bar mode
        self._scale = 1.0           # zoom multiplier applied to all dimensions
        self._opacity = 0.75        # background alpha; overrides BG_RGBA[3]
        self._drag_start_screen = None  # (x, y) screen coords at drag start
        self._drag_start_win    = None  # (x, y) window origin at drag start
        return self

    def isFlipped(self):
        """Return True to use top-left origin with y increasing downward.

        Flipping the coordinate system lets drawRect_ lay out rows by adding
        positive offsets from the top, which is far more readable than
        subtracting from the height.  All x/y values in drawRect_ assume this
        convention.
        """
        return True

    def acceptsFirstMouse_(self, event):
        """Allow the overlay to receive mouse-down even when it is not the key window.

        Without this, the first click on the overlay would merely bring it to
        the front without triggering mouseDown_; a second click would be needed
        to start a drag.
        """
        return True

    def acceptsFirstResponder(self):
        """Allow the view to become first responder so it receives key/scroll events."""
        return True

    # ------------------------------------------------------------------ drawing

    @objc.python_method
    def _draw_str(self, text: str, x: float, y: float, size: float, rgba: RGBA) -> float:
        """Draw a string at (x, y) with the given point size and RGBA color.

        Uses NSAttributedString so font and color are bundled together before
        drawing, avoiding separate setFont/setColor calls.

        Args:
            text: The Python str to render.
            x, y: Top-left origin in the flipped view coordinate system.
            size: Font size in points.
            rgba: (r, g, b, a) tuple.

        Returns:
            The rendered string width in points (used to right-align text).
        """
        font: NSFont = _mono_font(size)
        ns_str = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: font,
             NSForegroundColorAttributeName: _ns_color(*rgba)},
        )
        ns_str.drawAtPoint_(NSMakePoint(x, y))
        return ns_str.size().width

    @objc.python_method
    def _str_w(self, text: str, size: float) -> float:
        """Return the rendered width of a string in points without drawing it.

        Used for right-alignment: the caller subtracts this from the right
        edge to find the x origin that will place the string flush-right.
        """
        ns_str = NSAttributedString.alloc().initWithString_attributes_(
            text, {NSFontAttributeName: _mono_font(size)},
        )
        return ns_str.size().width

    @objc.python_method
    def _font_h(self, size: float) -> float:
        """Return the bounding-box height of the monospaced font at *size* points.

        boundingRectForFont() returns the union rectangle of all glyphs in the
        font, which is a reliable proxy for line height when positioning rows.
        """
        return _mono_font(size).boundingRectForFont().size.height

    def drawRect_(self, rect):
        """Paint the entire overlay content.

        Called by the AppKit display machinery whenever setNeedsDisplay_(True)
        has been called or the view is first shown.  All drawing uses the
        flipped coordinate system (top-left origin, y increases downward).

        Layout passes:
            1. Clear the view to fully transparent (required for the overlay
               glass effect because the window background is also transparent).
            2. If minimized: draw a single thin bar representing session usage.
            3. Otherwise: draw the background pill, the "CLAUDE" title, and
               two rows of (label, percentage, countdown, progress bar) for
               session and weekly usage.
        """
        w = self.bounds().size.width
        s = self._scale  # shorthand; avoids repeated attribute lookup below

        # --- Pass 1: clear to transparent ---
        # The window has setOpaque_(False) and a clear background color, so we
        # must explicitly erase every frame; AppKit does not do it for us.
        NSColor.clearColor().setFill()
        NSBezierPath.fillRect_(self.bounds())

        # --- Minimized mode: render only a thin colored bar ---
        if self._minimized:
            # Draw the empty track first, then the filled portion on top.
            _ns_color(*BAR_TRACK_RGBA).setFill()
            _fill_rrect(0, 0, w, MINIMIZED_HEIGHT, 3)
            if self._session_pct > 0:
                # Clamp the fill width to [4 px, w] so the bar is always
                # visible even at very low usage fractions.
                fw = max(w * min(self._session_pct, 1.0), 4)
                _ns_color(*_bar_color(self._session_pct)).setFill()
                _fill_rrect(0, 0, fw, MINIMIZED_HEIGHT, 3)
            return

        # --- Full mode ---

        # Background pill; use self._opacity instead of BG_RGBA[3] so the
        # user can adjust transparency at runtime without editing the constant.
        _ns_color(BG_RGBA[0], BG_RGBA[1], BG_RGBA[2], self._opacity).setFill()
        _fill_rrect(0, 0, w, self.bounds().size.height, OSD_RADIUS * s)

        # Scale-dependent layout metrics
        pad_x = 14 * s    # horizontal padding inside the background pill
        pad_y = 10 * s    # vertical padding from the top of the pill
        bar_h = OSD_BAR_HEIGHT * s
        bar_r = OSD_BAR_RADIUS * s
        bar_w = w - 2 * pad_x   # progress bar spans the full inner width
        fl  = 10 * s    # font size for main labels and percentages
        fs  = 7.5 * s   # font size for the countdown/reset time strings
        ft  = 8 * s     # font size for the "CLAUDE" title
        lh  = self._font_h(fl)   # line height for main rows
        th  = self._font_h(ft)   # line height for title row

        # Title row — static, dimmed label in the top-left
        self._draw_str("CLAUDE", pad_x, pad_y, ft, DIM_RGBA)

        # --- Session row ---
        # y advances downward from pad_y by the title height plus a small gap.
        y = pad_y + th + 4 * s

        pct_s = f"{int(self._session_pct * 100)}%"
        pct_w = self._str_w(pct_s, fl)

        # Label flush-left; percentage flush-right.
        self._draw_str("Session", pad_x, y, fl, TEXT_RGBA)
        self._draw_str(pct_s, w - pad_x - pct_w, y, fl, TEXT_RGBA)

        # Reset countdown rendered between the percentage and the right edge
        # of the label column, vertically centered within the label row.
        reset_s = _format_reset_short(self._session_reset)
        if reset_s:
            rw = self._str_w(reset_s, fs)
            sh = self._font_h(fs)
            self._draw_str(reset_s,
                           w - pad_x - pct_w - 8 * s - rw,
                           y + (lh - sh) / 2,   # center the smaller text vertically
                           fs, DIM_RGBA)

        # Progress bar: track first, then filled portion on top.
        bar_y = y + lh + 3 * s
        _ns_color(*BAR_TRACK_RGBA).setFill()
        _fill_rrect(pad_x, bar_y, bar_w, bar_h, bar_r)
        if self._session_pct > 0:
            # Enforce a minimum fill width equal to bar_h (a perfect circle) so
            # the bar is always visible; clamp the fraction to 1.0 so it never
            # overflows the track even if the API reports > 100 % usage.
            _ns_color(*_bar_color(self._session_pct)).setFill()
            _fill_rrect(pad_x, bar_y,
                        max(bar_w * min(self._session_pct, 1.0), bar_h),
                        bar_h, bar_r)

        # --- Weekly row ---
        # Starts 10*s points below the bottom of the session progress bar.
        y2 = bar_y + bar_h + 10 * s

        pct_s2 = f"{int(self._weekly_pct * 100)}%"
        pct_w2 = self._str_w(pct_s2, fl)

        self._draw_str("Weekly", pad_x, y2, fl, TEXT_RGBA)
        self._draw_str(pct_s2, w - pad_x - pct_w2, y2, fl, TEXT_RGBA)

        reset_w2 = _format_reset_short(self._weekly_reset)
        if reset_w2:
            rw = self._str_w(reset_w2, fs)
            sh = self._font_h(fs)
            self._draw_str(reset_w2,
                           w - pad_x - pct_w2 - 8 * s - rw,
                           y2 + (lh - sh) / 2,
                           fs, DIM_RGBA)

        bar_y2 = y2 + lh + 3 * s
        _ns_color(*BAR_TRACK_RGBA).setFill()
        _fill_rrect(pad_x, bar_y2, bar_w, bar_h, bar_r)
        if self._weekly_pct > 0:
            _ns_color(*_bar_color(self._weekly_pct)).setFill()
            _fill_rrect(pad_x, bar_y2,
                        max(bar_w * min(self._weekly_pct, 1.0), bar_h),
                        bar_h, bar_r)

    # ------------------------------------------------------------------ events

    def mouseDown_(self, event):
        """Record the drag anchor when the user presses the mouse button.

        NSEvent.mouseLocation() returns the cursor position in *screen*
        coordinates (bottom-left origin, y upward — Quartz convention), which
        is the same coordinate space used by NSWindow.frame().  Storing both
        the screen anchor and the window's origin at drag start lets
        mouseDragged_ compute a clean delta without accumulated floating-point
        drift.
        """
        loc = NSEvent.mouseLocation()
        self._drag_start_screen = (loc.x, loc.y)
        win = self.window()
        if win:
            origin = win.frame().origin
            self._drag_start_win = (origin.x, origin.y)

    def mouseUp_(self, event):
        """Clear the drag anchor when the mouse button is released."""
        self._drag_start_screen = None
        self._drag_start_win = None

    def mouseDragged_(self, event):
        """Move the window by the delta from the recorded drag anchor.

        Using the *initial* anchor (rather than the previous event position)
        avoids the subtle position drift that can occur when using
        event.deltaX()/deltaY(), which accumulates sub-pixel rounding errors
        across many small events.
        """
        if not self._drag_start_screen or not self._drag_start_win:
            return
        loc = NSEvent.mouseLocation()  # current cursor in screen coordinates
        dx = loc.x - self._drag_start_screen[0]
        dy = loc.y - self._drag_start_screen[1]
        win = self.window()
        if win:
            win.setFrameOrigin_(NSMakePoint(
                self._drag_start_win[0] + dx,
                self._drag_start_win[1] + dy,
            ))

    def rightMouseDown_(self, event):
        """Toggle between full and minimized (thin-bar) display modes.

        Calls _resize_window to anchor the top-right corner while collapsing
        or expanding the height, then triggers a redraw.
        """
        self._minimized = not self._minimized
        win = self.window()
        if win:
            _resize_window(win, self._scale, self._minimized)
        self.setNeedsDisplay_(True)

    def scrollWheel_(self, event):
        """Zoom the overlay in or out with the scroll wheel.

        Each scroll tick changes _scale by SCALE_STEP (0.1), clamped to
        [SCALE_MIN, SCALE_MAX].  The window is resized via _resize_window
        (top-right anchor preserved), then the view is redrawn so all
        scale-dependent measurements in drawRect_ take effect immediately.

        Zoom is disabled in minimized mode to avoid confusing state where
        the full-mode height after un-minimizing would not match the visual
        thin bar.
        """
        if self._minimized:
            return
        delta = event.deltaY()  # positive = scroll up = zoom in
        direction = 1 if delta > 0 else (-1 if delta < 0 else 0)
        if not direction:
            return
        self._scale = max(SCALE_MIN, min(SCALE_MAX, self._scale + direction * SCALE_STEP))
        win = self.window()
        if win:
            _resize_window(win, self._scale, self._minimized)
        self.setNeedsDisplay_(True)


class UsageOverlay:
    """Manages the macOS borderless floating OSD window.

    Responsible for constructing the NSWindow / OSDView pair, configuring all
    window attributes required for an always-on-top transparent HUD, and
    exposing a small public API (show_all, hide, set_opacity, update) that the
    platform-agnostic plugin core uses to control the overlay.
    """

    _win: NSWindow
    _view: OSDView

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        """Create the NSWindow and OSDView.

        Args:
            config: Optional dict with keys:
                osd_scale   -- initial zoom multiplier (default 1.0).
                osd_opacity -- initial background alpha  (default 0.75).
        """
        cfg: dict[str, Any] = config or {}
        scale:   float = cfg.get("osd_scale",   1.0)
        opacity: float = cfg.get("osd_opacity", 0.75)

        w: int = int(BASE_WIDTH  * scale)
        h: int = int(BASE_HEIGHT * scale)

        # Position the overlay in the top-right of the *visible* screen area.
        # visibleFrame() excludes the menu bar and Dock, so the overlay does
        # not spawn beneath them.  NSScreen coordinates use the Quartz system
        # (bottom-left origin), so the top-right corner is at
        # (origin.x + width, origin.y + height).
        sv = NSScreen.mainScreen().visibleFrame()
        x: float = sv.origin.x + sv.size.width  - w - OSD_MARGIN
        y: float = sv.origin.y + sv.size.height - h - OSD_MARGIN

        # --- Window creation ---
        # _BORDERLESS (style mask 0) means no title bar, no close/minimize
        # buttons, and no resize handles — just a raw content area.
        # NSBackingStoreBuffered uses an offscreen backing buffer that is
        # composited onto the display; this is the only supported mode on
        # modern macOS.
        # defer=False forces the window's display resources to be created
        # immediately rather than lazily on first show.
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h), _BORDERLESS, NSBackingStoreBuffered, False
        )

        # Make the window fully transparent so OSDView's clear-color erase
        # actually shows whatever is behind the window.
        self._win.setOpaque_(False)
        self._win.setBackgroundColor_(NSColor.clearColor())

        # NSFloatingWindowLevel (~3) sits above normal application windows.
        # Adding 1 ensures the overlay floats above other floating panels
        # (e.g. color pickers, tool palettes) that also use NSFloatingWindowLevel.
        self._win.setLevel_(NSFloatingWindowLevel + 1)

        # Apply the collection-behavior bitmask so the overlay appears on all
        # Spaces and is excluded from window-cycling UI.
        if _COLLECTION:
            self._win.setCollectionBehavior_(_COLLECTION)

        # Allow mouse events to reach OSDView (drag, right-click, scroll).
        # setIgnoresMouseEvents_(False) is the default, but stated explicitly
        # for clarity — a common pattern for overlay windows is to set it True
        # to make them click-through, which we deliberately do NOT want here.
        self._win.setIgnoresMouseEvents_(False)

        self._win.setHasShadow_(False)               # no drop shadow; HUD aesthetic
        self._win.setAcceptsMouseMovedEvents_(True)  # receive mouseMoved_ events if needed
        # Prevent AppKit from releasing (deallocating) the window when it is
        # closed.  Without this, orderOut_ would destroy the window object and
        # a subsequent show_all() call would crash.
        self._win.setReleasedWhenClosed_(False)

        # --- View setup ---
        self._view = OSDView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self._view._scale   = scale
        self._view._opacity = opacity
        # NSViewWidthSizable | NSViewHeightSizable makes the view track the
        # window's content rect exactly when _resize_window changes the frame.
        self._view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._win.setContentView_(self._view)

    def show_all(self) -> None:
        """Make the overlay window visible on screen.

        orderFront_(None) brings the window to the front of its window level
        without making it the key or main window, so the currently focused
        application retains focus.
        """
        self._win.orderFront_(None)

    def hide(self) -> None:
        """Remove the overlay window from the screen without destroying it.

        orderOut_(None) hides the window but keeps it in memory; show_all()
        can restore it without re-creating the NSWindow.
        """
        self._win.orderOut_(None)

    def set_opacity(self, value: float) -> None:
        """Set the background translucency of the overlay.

        Args:
            value: Desired alpha in [0, 1].  Clamped to [0.15, 1.0] so the
                   overlay never becomes completely invisible.
        """
        self._view._opacity = max(0.15, min(1.0, value))
        self._view.setNeedsDisplay_(True)

    def update(self, stats: UsageStats) -> None:
        """Push new usage data into the view and request a redraw.

        Args:
            stats: A UsageStats dataclass with session_utilization,
                   weekly_utilization, session_reset, and weekly_reset fields.
                   Called periodically by the background poller.
        """
        self._view._session_pct   = stats.session_utilization
        self._view._weekly_pct    = stats.weekly_utilization
        self._view._session_reset = stats.session_reset
        self._view._weekly_reset  = stats.weekly_reset
        self._view.setNeedsDisplay_(True)
