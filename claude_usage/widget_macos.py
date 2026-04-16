"""macOS menu bar app and detailed popup window.

Architecture overview
---------------------
- ClaudeUsageTray  : the rumps.App subclass that owns the menu-bar icon and
                     drives the entire lifecycle.
- UsagePopup       : a plain NSWindow with a custom-drawn NSView (PopupView).
- PopupView        : Core Graphics drawing via AppKit — no nibs, no storyboards.
- _PopupDelegate   : minimal NSObject window-delegate that intercepts the close
                     button so we hide rather than destroy the window.

Threading model
---------------
Data collection (collect_all) runs in a daemon thread to avoid blocking the
main/UI thread.  Results are posted to a Queue, which is drained by a
rumps.timer callback that fires every second on the main thread.  This avoids
any need for explicit locks because only the timer callback (always on the
main run-loop thread) writes to shared UI state.
"""

from __future__ import annotations

import os
import queue
import threading
from datetime import datetime
from typing import Any

import objc
import rumps
from AppKit import (
    NSWindow, NSView, NSObject,
    NSBackingStoreBuffered,
    NSColor, NSBezierPath, NSFont,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSAttributedString,
    NSScreen,
    NSApp,
    NSViewWidthSizable, NSViewHeightSizable,
)
from Foundation import NSMakeRect, NSMakePoint

# NSWindowStyleMask constants were renamed in newer SDK headers.
# Try importing the symbolic names; fall back to the raw integer values that
# have been stable across macOS versions.
try:
    from AppKit import (
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskClosable,
    )
    _POPUP_MASK = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
except ImportError:
    _POPUP_MASK = 1 | 2  # NSWindowStyleMaskTitled | NSWindowStyleMaskClosable

# Pre-fetch the dark-mode NSAppearance object so we can force the popup into
# dark mode regardless of the system setting.  If the class is unavailable on
# older macOS we simply skip appearance forcing.
try:
    from AppKit import NSAppearance
    _DARK_APPEARANCE = NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
except Exception:
    _DARK_APPEARANCE = None

from claude_usage.collector import collect_all, UsageStats
from claude_usage.notifier import UsageNotifier
from claude_usage.overlay_macos import UsageOverlay

ICON_PATH: str = os.path.join(os.path.dirname(__file__), "icons", "claude-tray.svg")

# Type alias for normalised RGBA colour tuples (r, g, b, a) in 0.0–1.0 sRGB.
_RGBA = tuple[float, float, float, float]

# ---------------------------------------------------------------------------
# Popup color palette — all values are normalised (0.0–1.0) sRGB + alpha.
# Using named constants keeps the drawing code readable and makes palette
# changes a single-location edit.
# ---------------------------------------------------------------------------
_BG:    _RGBA = (0.102, 0.102, 0.180, 1.0)   # deep navy background
_PRI:   _RGBA = (0.878, 0.878, 0.910, 1.0)   # primary text (near-white)
_SEC:   _RGBA = (0.541, 0.541, 0.604, 1.0)   # secondary / muted text
_DIM:   _RGBA = (0.333, 0.333, 0.408, 1.0)   # dimmed text (timestamps, labels)
_LINK:  _RGBA = (0.420, 0.643, 0.851, 1.0)   # session path text (blue-ish)
_BAR:   _RGBA = (0.357, 0.608, 0.835, 1.0)   # progress bar fill
_TRACK: _RGBA = (0.200, 0.200, 0.251, 1.0)   # progress bar track (empty portion)
_SEP:   _RGBA = (0.165, 0.165, 0.220, 1.0)   # separator line
_ERR:   _RGBA = (0.937, 0.267, 0.267, 1.0)   # error text (red)

# ---------------------------------------------------------------------------
# Layout constants — all in points.
# PAD_X   : horizontal inset from both left and right edges.
# PAD_TOP : space above the first section header.
# PAD_BTM : space below the last element before the bottom edge.
# POPUP_W : fixed popup width (height is computed dynamically).
# ---------------------------------------------------------------------------
PAD_X:   int = 24
PAD_TOP: int = 20
PAD_BTM: int = 20
POPUP_W: int = 520


# ---------------------------------------------------------------------------
# Low-level drawing helpers
# ---------------------------------------------------------------------------

def _ns_color(r: float, g: float, b: float, a: float = 1.0) -> Any:
    """Convert a normalised RGBA tuple to an NSColor object."""
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


def _fill_rrect(x: float, y: float, w: float, h: float, r: float = 6.0) -> None:
    """Fill a rounded rectangle.

    Clamps the corner radius so it never exceeds half the shorter dimension,
    which avoids CoreGraphics rendering artifacts.  Falls back to a plain rect
    when the radius would be sub-pixel.
    """
    r = min(r, w / 2, h / 2)
    if r < 0.5:
        # Radius too small to matter — use the faster fillRect_ path.
        NSBezierPath.fillRect_(NSMakeRect(x, y, w, h))
        return
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, y, w, h), r, r
    ).fill()


def _sys_font(size: float, bold: bool = False) -> Any:
    """Return a system font at the given point size, optionally bold."""
    if bold:
        return NSFont.boldSystemFontOfSize_(size)
    return NSFont.systemFontOfSize_(size)


def _draw_str(text: str, x: float, y: float, font: Any, rgba: _RGBA) -> Any:
    """Draw *text* at AppKit point (x, y) using the given font and colour.

    Because PopupView.isFlipped() returns True, the coordinate system has its
    origin at the top-left corner and y increases downward — the same as web /
    iOS layout.  All callers use this flipped convention.

    Returns the NSSize of the rendered string so callers can advance y.
    """
    ns_str = NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font,
               NSForegroundColorAttributeName: _ns_color(*rgba)}
    )
    ns_str.drawAtPoint_(NSMakePoint(x, y))
    return ns_str.size()


def _str_size(text: str, font: Any) -> Any:
    """Return the NSSize (width, height) of *text* rendered in *font*.

    Used to compute layout positions before drawing (e.g. right-aligning text
    or centering a bar vertically within a row).
    """
    ns_str = NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font}
    )
    return ns_str.size()


def _format_reset_duration(reset_ts: float) -> str:
    """Return a human-readable countdown string to *reset_ts* (Unix epoch).

    Returns an empty string when the timestamp is not available, and
    "Resets soon" once the deadline has passed but the counter hasn't
    refreshed yet.
    """
    if reset_ts <= 0:
        return ""
    remaining = int(reset_ts - datetime.now().timestamp())
    if remaining <= 0:
        return "Resets soon"
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    return f"Resets in {hours} hr {minutes} min" if hours > 0 else f"Resets in {minutes} min"


def _format_reset_day(reset_ts: float) -> str:
    """Return a short day/time string for a weekly reset timestamp.

    Example: "Resets Mon 09:00 AM".
    """
    if reset_ts <= 0:
        return ""
    return datetime.fromtimestamp(reset_ts).strftime("Resets %a %I:%M %p")


def _format_session_duration(seconds: int) -> str:
    """Return a compact elapsed-time string like "2h 5m" or "47m"."""
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"


def _calc_popup_height(n_sessions: int) -> int:
    """Compute the total pixel height required for the popup content.

    The popup has a fixed width (POPUP_W) but a variable height that depends
    on how many active sessions need to be shown.  We accumulate each logical
    section's height here so the window can be resized to exactly fit.

    Sections (top to bottom):
      - PAD_TOP
      - "Plan usage limits" header + usage row
      - separator
      - "Weekly limits" header + usage row
      - separator
      - "Active sessions" header + session rows (1-8, or placeholder)
      - separator
      - footer
      - PAD_BTM
    """
    y = PAD_TOP
    y += 26   # "Plan usage limits" header text height
    y += 12   # spacing below header
    y += 52   # usage row: label + progress bar (label_h + bar area + bottom margin)
    y += 25   # separator (1 px line + surrounding padding)
    y += 26   # "Weekly limits" header
    y += 12
    y += 52   # usage row
    y += 25   # separator
    y += 26   # "Active sessions" header
    y += 12
    rows = max(1, min(n_sessions, 8))  # at least 1 row ("No active sessions")
    y += rows * 24                     # each session row is 24 pts tall
    y += 25   # separator
    y += 22   # footer line
    y += PAD_BTM
    return y


# ---------------------------------------------------------------------------
# NSView subclass — all drawing is done in drawRect_
# ---------------------------------------------------------------------------

class PopupView(NSView):
    """Custom AppKit view that draws the entire popup UI with Core Graphics.

    There are no sub-views, no Auto Layout constraints, and no nibs.  Every
    pixel is painted in drawRect_ using NSBezierPath and NSAttributedString.
    The view uses a *flipped* coordinate system (origin top-left, y down) to
    make layout math match the natural reading direction.

    Data flow: the owning UsagePopup writes a new UsageStats object into
    ``_stats`` and then calls setNeedsDisplay_(True) to trigger a redraw.
    """

    _stats: UsageStats | None

    def initWithFrame_(self, frame: Any) -> PopupView | None:
        """Initialise the view and set up internal state."""
        self = objc.super(PopupView, self).initWithFrame_(frame)
        if self is None:
            return None
        # _stats holds the most-recently pushed UsageStats snapshot.
        # None means "no data yet" — drawRect_ skips content drawing in that case.
        self._stats = None
        return self

    def isFlipped(self) -> bool:
        """Return True to make y=0 the top of the view (flipped coordinates).

        AppKit normally places y=0 at the bottom-left.  By returning True here
        we invert the y-axis, so y increases downward — matching the mental
        model of "drawing top to bottom" used throughout this file.
        """
        return True

    def drawRect_(self, rect: Any) -> None:
        """Paint the entire popup.

        Called by AppKit whenever the view needs to be redrawn (after
        setNeedsDisplay_(True) or a window resize).  All drawing is done from
        scratch on each call — there is no retained drawing state.

        Layout proceeds top-to-bottom using a running ``y`` cursor that each
        helper method both reads and advances.  The helpers return the updated
        y position so the pattern is: ``y = self._some_section(args, y, ...)``.
        """
        w = self.bounds().size.width

        # Fill the entire view with the dark navy background colour before
        # drawing any content.  This prevents transparency / ghosting artefacts
        # when the window is resized.
        _ns_color(*_BG).setFill()
        NSBezierPath.fillRect_(self.bounds())

        # Guard: if no stats have been pushed yet, show only the background.
        if self._stats is None:
            return

        stats = self._stats
        bar_w = 200   # fixed width for all progress bars (in points)
        y = PAD_TOP   # running y cursor, advances downward

        # ---- Section 1: Plan usage limits (current session) ----
        y = self._section_header("Plan usage limits", y, w)
        y = self._usage_row(
            "Current session",
            _format_reset_duration(stats.session_reset),
            stats.session_utilization,
            y, w, bar_w,
        )
        y = self._draw_separator(y)

        # ---- Section 2: Weekly limits ----
        y = self._section_header("Weekly limits", y, w)
        y = self._usage_row(
            "All models",
            _format_reset_day(stats.weekly_reset),
            stats.weekly_utilization,
            y, w, bar_w,
        )
        y = self._draw_separator(y)

        # ---- Section 3: Active sessions ----
        n = len(stats.active_sessions)
        y = self._section_header("Active sessions", y, w,
                                  right_text=f"{n} running")
        if stats.active_sessions:
            # Cap at 8 rows so the popup doesn't grow unboundedly.
            for sess in stats.active_sessions[:8]:
                y = self._session_row(sess, y, w)
        else:
            f = _sys_font(11)
            _draw_str("No active sessions", PAD_X, y, f, _DIM)
            y += _str_size("X", f).height + 8   # advance past the placeholder row

        y = self._draw_separator(y)

        # ---- Footer: last-updated timestamp + optional error message ----
        f_upd = _sys_font(11)
        _draw_str("Last updated: just now", PAD_X, y, f_upd, _DIM)
        if stats.rate_limit_error:
            # Right-align the error text so it doesn't overlap the timestamp.
            err_text = f"API: {stats.rate_limit_error}"
            sz = _str_size(err_text, f_upd)
            _draw_str(err_text, w - PAD_X - sz.width, y, f_upd, _ERR)

    # ------------------------------------------------------------------
    # Private drawing helpers
    # All helpers are decorated with @objc.python_method so that the
    # Objective-C runtime does not try to expose them as selectors.  This
    # is required for methods whose names don't follow ObjC naming rules
    # (e.g. they have keyword arguments or Python-only signatures).
    # ------------------------------------------------------------------

    @objc.python_method
    def _section_header(self, title: str, y: float, w: float,
                        right_text: str = "") -> float:
        """Draw a bold section heading and an optional right-aligned label.

        The right label (e.g. "3 running") is vertically centred relative to
        the larger title so they appear on the same baseline visually:

            "Active sessions"          (bold 14pt, left)
            "3 running"                (regular 12pt, right, centred on title)

        Coordinate math for vertical centering of right_text:
            title_h   = height of the 14pt bold text
            right_h   = height of the 12pt text
            offset    = (title_h - right_h) / 2
            right_y   = y + offset          <- shifts right text down by offset

        Returns the y position immediately after the header + bottom spacing.
        """
        f_title = _sys_font(14, bold=True)
        _draw_str(title, PAD_X, y, f_title, _PRI)
        if right_text:
            f_right = _sys_font(12)
            sz = _str_size(right_text, f_right)
            # Vertically centre the smaller right label against the taller title.
            _draw_str(right_text, w - PAD_X - sz.width,
                      y + (_str_size(title, f_title).height - sz.height) / 2,
                      f_right, _SEC)
        # Return y advanced by the title height plus 12 pts of bottom padding.
        return y + _str_size(title, f_title).height + 12

    @objc.python_method
    def _usage_row(self, label: str, subtitle: str, fraction: float,
                   y: float, w: float, bar_w: float) -> float:
        """Draw one usage row: name/subtitle on the left, bar in the middle,
        percentage on the right.

        Layout (all coordinates in the flipped system, y increases downward):

            [PAD_X]  label (bold 13pt)             [bar]   [pct%]  [PAD_X]
                     subtitle (11pt, below label)

        The row height is determined by the label + optional subtitle stack.
        The progress bar and the percentage label are both centred vertically
        within that row height so they align with the visual midpoint of the
        text block.

        Coordinate math:
            row_h  = label_h + (sub_h + 2)   if subtitle else label_h
            bar_y  = y + (row_h - bar_h) / 2  <- vertically centres the 12pt-tall bar
            pct_y  = y + (row_h - pct_h) / 2  <- same logic for the percentage label

        The fill width is clamped to [bar_h, bar_w] so the filled portion is
        always at least as wide as the corner radius (bar_h == 12), preventing
        the rounded rectangle from looking like two separate half-circles.

        Returns y advanced past the row plus 16 pts of bottom spacing.
        """
        f_name = _sys_font(13, bold=True)
        f_sub  = _sys_font(11)
        f_pct  = _sys_font(12)

        label_h = _str_size(label, f_name).height
        sub_h   = _str_size("X", f_sub).height if subtitle else 0
        pct_h   = _str_size("X", f_pct).height
        # Total row height = label + optional subtitle gap + subtitle
        row_h   = label_h + (sub_h + 2 if subtitle else 0)

        left_w = 140  # reserved width for the name/subtitle column

        # --- Left column: name and subtitle ---
        _draw_str(label, PAD_X, y, f_name, _PRI)
        if subtitle:
            # Subtitle sits 2 pts below the label baseline.
            _draw_str(subtitle, PAD_X, y + label_h + 2, f_sub, _SEC)

        # --- Middle: progress bar ---
        # bar_x is placed immediately after the fixed left column.
        bar_x = PAD_X + left_w
        bar_h = 12   # bar height in points (also the corner radius)
        # Vertically centre the bar within the row.
        bar_y = y + (row_h - bar_h) / 2

        # Draw the empty track first (full width, dimmer colour).
        _ns_color(*_TRACK).setFill()
        _fill_rrect(bar_x, bar_y, bar_w, bar_h, 6)

        # Draw the filled portion on top, clamped so we never overshoot 100%.
        if fraction > 0:
            # Ensure the fill is at least bar_h wide so corner radius renders cleanly.
            fill_w = max(bar_w * min(fraction, 1.0), bar_h)
            _ns_color(*_BAR).setFill()
            _fill_rrect(bar_x, bar_y, fill_w, bar_h, 6)

        # --- Right column: percentage label (right-aligned to PAD_X margin) ---
        pct_text = f"{int(fraction * 100)}% used"
        pct_sz = _str_size(pct_text, f_pct)
        # Right edge of text = w - PAD_X; so x = w - PAD_X - text_width.
        _draw_str(pct_text, w - PAD_X - pct_sz.width,
                  y + (row_h - pct_h) / 2, f_pct, _SEC)

        return y + row_h + 16   # 16 pts of bottom padding after the row

    @objc.python_method
    def _draw_separator(self, y: float) -> float:
        """Draw a 1-point-tall horizontal rule and return the y after it.

        The rule is inset PAD_X from both sides.  We add 4 pts before the line
        and the line occupies 1 pt, for a total section gap of 25 pts.
        """
        _ns_color(*_SEP).setFill()
        # y + 4 gives a small gap above the line; height is exactly 1 point.
        NSBezierPath.fillRect_(NSMakeRect(PAD_X, y + 4, POPUP_W - 2 * PAD_X, 1))
        return y + 25   # total vertical space consumed by the separator

    @objc.python_method
    def _session_row(self, sess: dict[str, Any], y: float, w: float) -> float:
        """Draw one active-session row: working directory on the left, elapsed
        time on the right.

        The cwd is shortened with a leading ellipsis if it would overflow into
        the duration text.  The tilde-abbreviation is applied first so that
        paths under the home directory are as compact as possible before the
        overflow check runs.

        Truncation loop:
            We repeatedly strip characters from the front of the cwd string
            and prepend "..." until the rendered width fits within max_cwd_w.
            ``len(cwd) > 3`` guards against an infinite loop on very narrow
            widths — at that point we just accept the overflow.

        Returns y advanced by the row height (font height + 8 pts padding).
        """
        f = _sys_font(11)

        # Convert the stored millisecond epoch to a datetime, then compute age.
        started = datetime.fromtimestamp(sess.get("startedAt", 0) / 1000)
        duration = datetime.now() - started
        cwd = sess.get("cwd", "?").replace(os.path.expanduser("~"), "~")

        # Draw the duration right-aligned first so we know exactly how much
        # horizontal space it occupies before placing the cwd text.
        dur_text = _format_session_duration(int(duration.total_seconds()))
        dur_sz = _str_size(dur_text, f)
        _draw_str(dur_text, w - PAD_X - dur_sz.width, y, f, _DIM)

        # Compute the maximum width available for the cwd text.
        # 16 pts gap between the cwd and the duration label.
        max_cwd_w = w - 2 * PAD_X - dur_sz.width - 16
        # Progressively shorten cwd from the front until it fits.
        while cwd and _str_size(cwd, f).width > max_cwd_w and len(cwd) > 3:
            # Jump back up to 30 chars from the end to avoid O(n²) behaviour
            # on very long paths.
            cwd = "…" + cwd[max(1, len(cwd) - 30):]

        _draw_str(cwd, PAD_X, y, f, _LINK)
        return y + _str_size("X", f).height + 8   # fixed-height row advance


# ---------------------------------------------------------------------------
# NSObject window delegate — intercepts the close button
# ---------------------------------------------------------------------------

class _PopupDelegate(NSObject):
    """Window delegate that hides the popup instead of closing (destroying) it.

    The window delegate pattern in AppKit works as follows:
      1. The NSWindow sends ``windowShouldClose:`` to its delegate when the
         user clicks the red close button or presses Cmd-W.
      2. If the delegate returns True the window is closed and deallocated.
      3. By returning False and calling ``orderOut_`` ourselves we keep the
         window alive in memory while making it invisible — so the next call
         to ``show()`` can bring it back instantly without re-creating it.
    """

    def windowShouldClose_(self, sender: Any) -> bool:
        """Intercept the close event: hide the window and veto the close.

        ``sender`` is the NSWindow that wants to close.  Calling
        ``orderOut_(None)`` removes it from the screen without releasing it.
        Returning False tells AppKit not to proceed with the normal close
        (and deallocation) sequence.
        """
        sender.orderOut_(None)
        return False


# ---------------------------------------------------------------------------
# High-level popup controller
# ---------------------------------------------------------------------------

class UsagePopup:
    """Controller that owns a single NSWindow for the detailed usage popup.

    The window is created once in __init__ and then shown/hidden on demand.
    It is never destroyed — hiding uses ``orderOut_`` (window off screen but
    still in memory) so there is no allocation cost on subsequent shows.

    Window centering math
    ---------------------
    macOS window coordinates have their origin at the bottom-left of the
    *screen*, so to place the popup in the centre of the visible area:

        x = screen_left   + (screen_width  - popup_width)  / 2
        y = screen_bottom + (screen_height - popup_height) / 2

    ``visibleFrame()`` excludes the Dock and menu bar, so the popup lands in
    the actual usable region rather than under system chrome.
    """

    def __init__(self) -> None:
        """Create the NSWindow and set up its content view and delegate."""
        # Start with zero sessions so we can compute an initial window height.
        h = _calc_popup_height(0)

        # visibleFrame() excludes the Dock and menu bar area.
        sv = NSScreen.mainScreen().visibleFrame()

        # Centre horizontally and vertically within the visible screen area.
        # Note: macOS y-origin is bottom-left, so "centre vertically" means
        # placing the window's bottom edge at (screen_centre_y - h/2).
        x = sv.origin.x + (sv.size.width - POPUP_W) / 2
        y = sv.origin.y + (sv.size.height - h) / 2

        # Allocate the NSWindow with a titled, closable style mask.
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, POPUP_W, h), _POPUP_MASK, NSBackingStoreBuffered, False
        )
        self._win.setTitle_("Claude Usage")

        # Force the dark appearance even if the user's system theme is light,
        # so the dark colour palette (_BG, _PRI, etc.) looks as designed.
        if _DARK_APPEARANCE:
            self._win.setAppearance_(_DARK_APPEARANCE)

        # Prevent the window from being made too short to display content.
        self._win.setMinSize_((POPUP_W, 300))

        # Attach the hide-instead-of-close delegate (see _PopupDelegate).
        self._delegate = _PopupDelegate.alloc().init()
        self._win.setDelegate_(self._delegate)

        # Create the custom-drawn content view, sized to fill the window.
        self._view = PopupView.alloc().initWithFrame_(NSMakeRect(0, 0, POPUP_W, h))
        # Allow the view to resize with the window in both dimensions.
        self._view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._win.setContentView_(self._view)

    def update(self, stats: UsageStats) -> None:
        """Push new stats into the view and resize the window to fit.

        Resizing keeps the *top edge* of the window fixed so that the header
        doesn't jump — only the bottom edge moves up or down as the session
        list grows or shrinks.

        Top-edge preservation math (macOS y-origin at bottom-left):
            top_y    = current_origin_y + current_height
            new_y    = top_y - new_height          <- new bottom-left y
            new_rect = (origin_x, new_y, width, new_height)
        """
        self._view._stats = stats

        # Compute the new height from the number of active sessions.
        n = len(stats.active_sessions)
        new_h = _calc_popup_height(n)

        frame = self._win.frame()
        # Calculate where the top edge currently is (bottom-left origin system).
        top_y = frame.origin.y + frame.size.height
        # Move the bottom edge so the top stays fixed.
        self._win.setFrame_display_(
            NSMakeRect(frame.origin.x, top_y - new_h, POPUP_W, new_h), True
        )
        # Ask AppKit to redraw the view with the new data.
        self._view.setNeedsDisplay_(True)

    def show(self) -> None:
        """Bring the popup to the front and make it the key window."""
        # activateIgnoringOtherApps_(True) is required because the menu-bar
        # app may not be the active application when the user clicks the tray
        # icon.  Without this call, makeKeyAndOrderFront_ would bring the
        # window on screen but it would not receive keyboard focus.
        NSApp.activateIgnoringOtherApps_(True)
        self._win.makeKeyAndOrderFront_(None)

    def hide(self) -> None:
        """Remove the popup from the screen without destroying it."""
        self._win.orderOut_(None)


# ---------------------------------------------------------------------------
# Menu bar application
# ---------------------------------------------------------------------------

class ClaudeUsageTray(rumps.App):
    """Menu bar application that displays Claude API usage in the system tray.

    Lifecycle
    ---------
    1. __init__ builds menu items, creates UsagePopup and UsageOverlay, and
       kicks off the first background data collection via _do_refresh().
    2. Two timers run on the main thread:
       - _check_queue  : @rumps.timer(1) — fires every second, drains the
                         update queue and applies any pending stats snapshot.
       - _auto_refresh : rumps.Timer started with the configured interval —
                         fires periodically to trigger fresh data collection.
    3. _do_refresh() spawns a daemon thread (_collect_worker) that calls
       collect_all() and posts the result onto _update_queue.
    4. _check_queue drains the queue and calls _apply_stats() which updates
       all UI elements (menu labels, tray title, popup, overlay).

    The rumps.timer decorator
    -------------------------
    @rumps.timer(N) registers the decorated method as a recurring NSTimer
    that fires every N seconds on the main run-loop thread.  This is
    important: AppKit UI operations must happen on the main thread.  The
    decorator-based timer is used for the fast queue-drain poll (1 s).

    For the user-configurable refresh interval, a rumps.Timer object is
    constructed explicitly so the period can come from config at runtime
    rather than being baked in as a decorator argument.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Set up the menu bar icon, menu items, popup, and overlay.

        Parameters
        ----------
        config : dict
            Application configuration (API keys, refresh interval, thresholds,
            etc.) passed through to the data collector and the overlay widget.
        """
        # Attempt to load the SVG tray icon.  If the file is missing (e.g.
        # in a dev checkout without assets) fall back to the default rumps
        # icon rather than crashing.
        icon = ICON_PATH if os.path.isfile(ICON_PATH) else None
        super().__init__(
            name="Claude Usage",
            icon=icon,
            template=True,    # template=True makes the icon adapt to light/dark menu bars
            quit_button=None, # we supply our own Quit item for consistent ordering
        )
        self.config = config
        self.stats = UsageStats()

        # _update_queue is the bridge between the background collector thread
        # and the main-thread timer (_check_queue).  Using a Queue is the
        # simplest thread-safe hand-off: the worker puts(), the timer gets().
        self._update_queue: queue.Queue[UsageStats] = queue.Queue()

        # Guard flag: prevents launching a second collection thread while one
        # is already running.  Set to True in _do_refresh(), cleared to False
        # in _collect_worker's finally block regardless of success or failure.
        self._refreshing = False

        # ---- Menu item construction ----
        # Static display items (titles are overwritten by _apply_stats).
        self.mi_session = rumps.MenuItem("Session: —")
        self.mi_week    = rumps.MenuItem("Weekly: —")

        # Action items with callbacks.
        self.mi_details = rumps.MenuItem("Details…",    callback=self._on_show_details)
        self.mi_refresh = rumps.MenuItem("Refresh",     callback=self._on_refresh)
        self.mi_osd     = rumps.MenuItem("OSD Overlay", callback=self._on_toggle_osd)
        self.mi_osd.state = 1  # checked (overlay starts visible)

        # Sub-menu for OSD opacity.
        opacity_menu = rumps.MenuItem("OSD Opacity")
        for pct in [100, 75, 50, 25]:
            # Default-argument capture (p=pct) is essential here: without it
            # all lambdas would close over the same loop variable and always
            # call _on_set_opacity with the last value (25).
            mi = rumps.MenuItem(f"{pct}%",
                                callback=lambda s, p=pct: self._on_set_opacity(p))
            opacity_menu.add(mi)

        mi_quit = rumps.MenuItem("Quit", callback=self._on_quit)

        # Assemble the menu.  None inserts a separator line.
        self.menu = [
            self.mi_session,
            self.mi_week,
            None,
            self.mi_details,
            self.mi_refresh,
            None,
            self.mi_osd,
            opacity_menu,
            None,
            mi_quit,
        ]

        # Create the popup and overlay now so they are ready when the first
        # data arrives (avoids a visible delay on the first show).
        self.popup  = UsagePopup()
        self.overlay = UsageOverlay(config)
        self.overlay.show_all()
        self.notifier = UsageNotifier(config)

        # Prime the pump: start the first data collection immediately so the
        # tray icon shows real data as soon as the app is ready.
        self._do_refresh()

        # Start the configurable auto-refresh timer.  rumps.Timer wraps an
        # NSTimer and fires _auto_refresh on the main run-loop thread at the
        # interval specified in config["refresh_seconds"].
        refresh_timer = rumps.Timer(self._auto_refresh, config["refresh_seconds"])
        refresh_timer.start()

    # ------------------------------------------------------------------
    # rumps timer callbacks (always run on the main thread)
    # ------------------------------------------------------------------

    @rumps.timer(1)
    def _check_queue(self, _: rumps.Timer) -> None:
        """Drain the update queue and apply the most-recent stats snapshot.

        This timer fires every second on the main run-loop thread.  It reads
        all items currently in the queue but only applies the *last* one -- any
        intermediate results are discarded because showing stale intermediate
        states would cause flicker with no benefit.

        Queue draining loop:
            We call get_nowait() in a tight loop until queue.Empty is raised,
            keeping a reference to the last item we received.  After the loop,
            if latest is not None we have a fresh snapshot to apply.

        Why one second?
            A 1-second poll is imperceptibly fast for users while still being
            cheap (the queue is almost always empty).  The actual collection
            takes several seconds, so the timer will typically find the queue
            empty on most ticks.
        """
        latest: UsageStats | None = None
        while True:
            try:
                latest = self._update_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._apply_stats(latest)

    def _auto_refresh(self, _: rumps.Timer) -> None:
        """Trigger a background data refresh on the configured interval.

        Called by the rumps.Timer started in __init__.  Delegates immediately
        to _do_refresh() which guards against concurrent collection runs.
        """
        self._do_refresh()

    # ------------------------------------------------------------------
    # Data collection helpers
    # ------------------------------------------------------------------

    def _do_refresh(self) -> None:
        """Start a background data-collection thread (idempotent).

        If a collection is already in flight (_refreshing is True) this method
        returns immediately without spawning a second thread.  This prevents
        queuing up multiple concurrent requests when the user hammers Refresh
        or the auto-refresh timer fires while a previous collection is slow.
        """
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._collect_worker, daemon=True).start()

    def _collect_worker(self) -> None:
        """Background thread: collect stats and post the result to the queue.

        This method runs on a daemon thread (not the main thread) so it is
        safe to do blocking I/O (filesystem reads, API calls) here.  The
        result -- either a valid UsageStats or an error placeholder -- is posted
        to _update_queue for the main-thread timer to pick up.

        The finally block guarantees _refreshing is reset to False even if an
        unexpected exception escapes the inner try, preventing a permanent
        "locked out" state where no further refreshes would be possible.

        Daemon threads are automatically killed when the main process exits,
        so we don't need explicit cleanup.
        """
        try:
            try:
                stats = collect_all(self.config)
            except Exception:
                # Surface collection failures as a visible error in the popup
                # footer rather than silently swallowing them.
                stats = UsageStats(rate_limit_error="Collection failed")
            # put() is thread-safe; the main-thread timer will drain this.
            self._update_queue.put(stats)
        finally:
            # Always clear the guard flag so future refreshes are not blocked.
            self._refreshing = False

    def _apply_stats(self, stats: UsageStats) -> None:
        """Apply a new UsageStats snapshot to all UI surfaces.

        Called exclusively from the main thread (via _check_queue) so all
        AppKit calls here are safe.  Updates:
          - Menu item titles (Session %, Weekly %)
          - Tray icon label (the percentage shown next to the icon)
          - The details popup content and window size
          - The on-screen overlay widget
        """
        self.stats = stats

        s_pct = int(stats.session_utilization * 100)
        w_pct = int(stats.weekly_utilization  * 100)

        self.mi_session.title = f"Session: {s_pct}% used"
        self.mi_week.title    = f"Weekly: {w_pct}% used"
        # self.title sets the text displayed in the menu bar next to the icon.
        self.title = f"{s_pct}%"

        self.popup.update(stats)
        self.overlay.update(stats)
        self.notifier.check_stats(stats)

    # ------------------------------------------------------------------
    # Menu item action callbacks
    # ------------------------------------------------------------------

    def _on_show_details(self, _: rumps.MenuItem) -> None:
        """Show the detailed usage popup window."""
        self.popup.show()

    def _on_refresh(self, _: rumps.MenuItem) -> None:
        """Manually trigger an immediate data refresh."""
        self._do_refresh()

    def _on_toggle_osd(self, sender: rumps.MenuItem) -> None:
        """Toggle the on-screen display overlay on or off.

        sender.state is 1 (checked) when the overlay is currently visible.
        We toggle the state and show/hide the overlay accordingly.
        """
        sender.state = 0 if sender.state else 1
        if sender.state:
            self.overlay.show_all()
        else:
            self.overlay.hide()

    def _on_set_opacity(self, pct: int) -> None:
        """Set the OSD overlay opacity to *pct* percent (0-100)."""
        self.overlay.set_opacity(pct / 100.0)

    def _on_quit(self, _: rumps.MenuItem) -> None:
        """Quit the application cleanly via rumps."""
        rumps.quit_application()
