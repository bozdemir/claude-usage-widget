"""macOS menu bar app and detailed popup window."""

import os
import queue
import threading
from datetime import datetime

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

try:
    from AppKit import (
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskClosable,
    )
    _POPUP_MASK = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
except ImportError:
    _POPUP_MASK = 1 | 2  # NSWindowStyleMaskTitled | NSWindowStyleMaskClosable

try:
    from AppKit import NSAppearance
    _DARK_APPEARANCE = NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
except Exception:
    _DARK_APPEARANCE = None

from claude_usage.collector import collect_all, UsageStats
from claude_usage.overlay_macos import UsageOverlay

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons", "claude-tray.svg")

# Popup colors (r, g, b, a)
_BG    = (0.102, 0.102, 0.180, 1.0)
_PRI   = (0.878, 0.878, 0.910, 1.0)
_SEC   = (0.541, 0.541, 0.604, 1.0)
_DIM   = (0.333, 0.333, 0.408, 1.0)
_LINK  = (0.420, 0.643, 0.851, 1.0)
_BAR   = (0.357, 0.608, 0.835, 1.0)
_TRACK = (0.200, 0.200, 0.251, 1.0)
_SEP   = (0.165, 0.165, 0.220, 1.0)
_ERR   = (0.937, 0.267, 0.267, 1.0)

PAD_X = 24
PAD_TOP = 20
PAD_BTM = 20
POPUP_W = 520


def _ns_color(r, g, b, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


def _fill_rrect(x, y, w, h, r=6.0):
    r = min(r, w / 2, h / 2)
    if r < 0.5:
        NSBezierPath.fillRect_(NSMakeRect(x, y, w, h))
        return
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, y, w, h), r, r
    ).fill()


def _sys_font(size, bold=False):
    if bold:
        return NSFont.boldSystemFontOfSize_(size)
    return NSFont.systemFontOfSize_(size)


def _draw_str(text, x, y, font, rgba):
    """Draw text at (x, y) — with isFlipped=True, y=0 is top."""
    ns_str = NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font,
               NSForegroundColorAttributeName: _ns_color(*rgba)}
    )
    ns_str.drawAtPoint_(NSMakePoint(x, y))
    return ns_str.size()


def _str_size(text, font):
    ns_str = NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font}
    )
    return ns_str.size()


def _format_reset_duration(reset_ts):
    if reset_ts <= 0:
        return ""
    remaining = int(reset_ts - datetime.now().timestamp())
    if remaining <= 0:
        return "Resets soon"
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    return f"Resets in {hours} hr {minutes} min" if hours > 0 else f"Resets in {minutes} min"


def _format_reset_day(reset_ts):
    if reset_ts <= 0:
        return ""
    return datetime.fromtimestamp(reset_ts).strftime("Resets %a %I:%M %p")


def _format_session_duration(seconds):
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"


def _calc_popup_height(n_sessions):
    """Calculate the needed popup content height."""
    y = PAD_TOP
    y += 26   # "Plan usage limits" header
    y += 12   # header bottom margin
    y += 52   # usage row (label + bar)
    y += 25   # separator
    y += 26   # "Weekly limits" header
    y += 12
    y += 52   # usage row
    y += 25   # separator
    y += 26   # "Active sessions" header
    y += 12
    rows = max(1, min(n_sessions, 8))  # at least "No active sessions"
    y += rows * 24
    y += 25   # separator
    y += 22   # footer
    y += PAD_BTM
    return y


class PopupView(NSView):
    """Custom-drawn content view for the details popup."""

    def initWithFrame_(self, frame):
        self = objc.super(PopupView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._stats = None
        return self

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        w = self.bounds().size.width

        # Dark background
        _ns_color(*_BG).setFill()
        NSBezierPath.fillRect_(self.bounds())

        if self._stats is None:
            return

        stats = self._stats
        bar_w = 200
        y = PAD_TOP

        # ---- Plan usage limits ----
        y = self._section_header("Plan usage limits", y, w)
        y = self._usage_row(
            "Current session",
            _format_reset_duration(stats.session_reset),
            stats.session_utilization,
            y, w, bar_w,
        )
        y = self._draw_separator(y)

        # ---- Weekly limits ----
        y = self._section_header("Weekly limits", y, w)
        y = self._usage_row(
            "All models",
            _format_reset_day(stats.weekly_reset),
            stats.weekly_utilization,
            y, w, bar_w,
        )
        y = self._draw_separator(y)

        # ---- Active sessions ----
        n = len(stats.active_sessions)
        y = self._section_header("Active sessions", y, w,
                                  right_text=f"{n} running")
        if stats.active_sessions:
            for sess in stats.active_sessions[:8]:
                y = self._session_row(sess, y, w)
        else:
            f = _sys_font(11)
            _draw_str("No active sessions", PAD_X, y, f, _DIM)
            y += _str_size("X", f).height + 8

        y = self._draw_separator(y)

        # ---- Footer ----
        f_upd = _sys_font(11)
        _draw_str("Last updated: just now", PAD_X, y, f_upd, _DIM)
        if stats.rate_limit_error:
            err_text = f"API: {stats.rate_limit_error}"
            sz = _str_size(err_text, f_upd)
            _draw_str(err_text, w - PAD_X - sz.width, y, f_upd, _ERR)

    # ------------------------------------------------------------------ helpers

    @objc.python_method
    def _section_header(self, title, y, w, right_text=""):
        f_title = _sys_font(14, bold=True)
        _draw_str(title, PAD_X, y, f_title, _PRI)
        if right_text:
            f_right = _sys_font(12)
            sz = _str_size(right_text, f_right)
            _draw_str(right_text, w - PAD_X - sz.width,
                      y + (_str_size(title, f_title).height - sz.height) / 2,
                      f_right, _SEC)
        return y + _str_size(title, f_title).height + 12

    @objc.python_method
    def _usage_row(self, label, subtitle, fraction, y, w, bar_w):
        f_name = _sys_font(13, bold=True)
        f_sub  = _sys_font(11)
        f_pct  = _sys_font(12)

        label_h = _str_size(label, f_name).height
        sub_h   = _str_size("X", f_sub).height if subtitle else 0
        pct_h   = _str_size("X", f_pct).height
        row_h   = label_h + (sub_h + 2 if subtitle else 0)

        left_w = 140
        # Name label
        _draw_str(label, PAD_X, y, f_name, _PRI)
        if subtitle:
            _draw_str(subtitle, PAD_X, y + label_h + 2, f_sub, _SEC)

        # Bar (center-aligned vertically in row)
        bar_x = PAD_X + left_w
        bar_h = 12
        bar_y = y + (row_h - bar_h) / 2
        _ns_color(*_TRACK).setFill()
        _fill_rrect(bar_x, bar_y, bar_w, bar_h, 6)
        if fraction > 0:
            fill_w = max(bar_w * min(fraction, 1.0), bar_h)
            _ns_color(*_BAR).setFill()
            _fill_rrect(bar_x, bar_y, fill_w, bar_h, 6)

        # Percentage label (right-aligned)
        pct_text = f"{int(fraction * 100)}% used"
        pct_sz = _str_size(pct_text, f_pct)
        _draw_str(pct_text, w - PAD_X - pct_sz.width,
                  y + (row_h - pct_h) / 2, f_pct, _SEC)

        return y + row_h + 16

    @objc.python_method
    def _draw_separator(self, y):
        _ns_color(*_SEP).setFill()
        NSBezierPath.fillRect_(NSMakeRect(PAD_X, y + 4, POPUP_W - 2 * PAD_X, 1))
        return y + 25

    @objc.python_method
    def _session_row(self, sess, y, w):
        f = _sys_font(11)
        started = datetime.fromtimestamp(sess.get("startedAt", 0) / 1000)
        duration = datetime.now() - started
        cwd = sess.get("cwd", "?").replace(os.path.expanduser("~"), "~")

        dur_text = _format_session_duration(int(duration.total_seconds()))
        dur_sz = _str_size(dur_text, f)
        _draw_str(dur_text, w - PAD_X - dur_sz.width, y, f, _DIM)

        # Truncate cwd to fit
        max_cwd_w = w - 2 * PAD_X - dur_sz.width - 16
        while cwd and _str_size(cwd, f).width > max_cwd_w and len(cwd) > 3:
            cwd = "…" + cwd[max(1, len(cwd) - 30):]

        _draw_str(cwd, PAD_X, y, f, _LINK)
        return y + _str_size("X", f).height + 8


class _PopupDelegate(NSObject):
    """Window delegate that hides instead of closing."""
    def windowShouldClose_(self, sender):
        sender.orderOut_(None)
        return False


class UsagePopup:
    """Detailed stats popup window."""

    def __init__(self):
        h = _calc_popup_height(0)
        sv = NSScreen.mainScreen().visibleFrame()
        x = sv.origin.x + (sv.size.width - POPUP_W) / 2
        y = sv.origin.y + (sv.size.height - h) / 2

        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, POPUP_W, h), _POPUP_MASK, NSBackingStoreBuffered, False
        )
        self._win.setTitle_("Claude Usage")
        if _DARK_APPEARANCE:
            self._win.setAppearance_(_DARK_APPEARANCE)
        self._win.setMinSize_(NSMakePoint(POPUP_W, 300))

        self._delegate = _PopupDelegate.alloc().init()
        self._win.setDelegate_(self._delegate)

        self._view = PopupView.alloc().initWithFrame_(NSMakeRect(0, 0, POPUP_W, h))
        self._view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._win.setContentView_(self._view)

    def update(self, stats: UsageStats):
        self._view._stats = stats
        # Resize window to fit content
        n = len(stats.active_sessions)
        new_h = _calc_popup_height(n)
        frame = self._win.frame()
        # Keep top edge fixed (macOS origin is bottom-left)
        top_y = frame.origin.y + frame.size.height
        self._win.setFrame_display_(
            NSMakeRect(frame.origin.x, top_y - new_h, POPUP_W, new_h), True
        )
        self._view.setNeedsDisplay_(True)

    def show(self):
        NSApp.activateIgnoringOtherApps_(True)
        self._win.makeKeyAndOrderFront_(None)

    def hide(self):
        self._win.orderOut_(None)


class ClaudeUsageTray(rumps.App):
    """Menu bar application."""

    def __init__(self, config: dict):
        # Try SVG icon; fall back gracefully if unsupported
        icon = ICON_PATH if os.path.isfile(ICON_PATH) else None
        super().__init__(
            name="Claude Usage",
            icon=icon,
            template=True,
            quit_button=None,
        )
        self.config = config
        self.stats = UsageStats()
        self._update_queue: queue.Queue = queue.Queue()
        self._refreshing = False

        # Menu items
        self.mi_session = rumps.MenuItem("Session: —")
        self.mi_week    = rumps.MenuItem("Weekly: —")
        self.mi_details = rumps.MenuItem("Details…",    callback=self._on_show_details)
        self.mi_refresh = rumps.MenuItem("Refresh",     callback=self._on_refresh)
        self.mi_osd     = rumps.MenuItem("OSD Overlay", callback=self._on_toggle_osd)
        self.mi_osd.state = 1  # checked

        opacity_menu = rumps.MenuItem("OSD Opacity")
        for pct in [100, 75, 50, 25]:
            mi = rumps.MenuItem(f"{pct}%",
                                callback=lambda s, p=pct: self._on_set_opacity(p))
            opacity_menu.add(mi)

        mi_quit = rumps.MenuItem("Quit", callback=self._on_quit)

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

        self.popup  = UsagePopup()
        self.overlay = UsageOverlay(config)
        self.overlay.show_all()

        # Kick off the first refresh
        self._do_refresh()

    # ------------------------------------------------------------------ timers

    @rumps.timer(1)
    def _check_queue(self, _):
        """Drain the update queue on the main thread."""
        try:
            stats = self._update_queue.get_nowait()
            self._apply_stats(stats)
        except queue.Empty:
            pass

    @rumps.timer(30)  # secondary auto-refresh fallback
    def _auto_refresh(self, _):
        self._do_refresh()

    # ------------------------------------------------------------------ actions

    def _do_refresh(self):
        """Launch background data collection (guards against concurrent runs)."""
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._collect_worker, daemon=True).start()

    def _collect_worker(self):
        try:
            stats = collect_all(self.config)
        except Exception:
            stats = UsageStats(rate_limit_error="Collection failed")
        self._update_queue.put(stats)

    def _apply_stats(self, stats: UsageStats):
        self._refreshing = False
        self.stats = stats
        s_pct = int(stats.session_utilization * 100)
        w_pct = int(stats.weekly_utilization * 100)

        self.mi_session.title = f"Session: {s_pct}% used"
        self.mi_week.title    = f"Weekly: {w_pct}% used"
        self.title = f"{s_pct}%"

        self.popup.update(stats)
        self.overlay.update(stats)

    def _on_show_details(self, _):
        self.popup.show()

    def _on_refresh(self, _):
        self._do_refresh()

    def _on_toggle_osd(self, sender):
        sender.state = not sender.state
        if sender.state:
            self.overlay.show_all()
        else:
            self.overlay.hide()

    def _on_set_opacity(self, pct):
        self.overlay.set_opacity(pct / 100.0)

    def _on_quit(self, _):
        rumps.quit_application()
