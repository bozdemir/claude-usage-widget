"""System tray icon and detailed popup window."""

import math
import os
import threading
from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import Gtk, GLib, Gdk, Pango
from gi.repository import AyatanaAppIndicator3 as AppIndicator

from claude_usage.collector import collect_all, UsageStats
from claude_usage.overlay import UsageOverlay


ICON_PATH = os.path.join(os.path.dirname(__file__), "icons", "claude-tray.svg")

# Colors matching Claude web dashboard
BAR_BLUE = "#5B9BD5"
BAR_TRACK = "#333340"
BG_COLOR = "#1a1a2e"
TEXT_PRIMARY = "#e0e0e8"
TEXT_SECONDARY = "#8a8a9a"
TEXT_DIM = "#555568"
TEXT_LINK = "#6BA4D9"
SEPARATOR_COLOR = "#2a2a38"


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _format_reset_duration(reset_ts: int) -> str:
    """Format reset timestamp as 'Resets in X hr Y min'."""
    if reset_ts <= 0:
        return ""
    remaining = int(reset_ts - datetime.now().timestamp())
    if remaining <= 0:
        return "Resets soon"
    hours, remainder = divmod(remaining, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"Resets in {hours} hr {minutes} min"
    return f"Resets in {minutes} min"


def _format_reset_day(reset_ts: int) -> str:
    """Format reset timestamp as 'Resets Mon 4:00 PM'."""
    if reset_ts <= 0:
        return ""
    return datetime.fromtimestamp(reset_ts).strftime("Resets %a %I:%M %p")


def _format_session_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


CSS = f"""
window {{
    background-color: {BG_COLOR};
}}
.section-header {{
    color: {TEXT_PRIMARY};
    font-size: 14px;
    font-weight: bold;
}}
.section-right {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
    font-style: italic;
}}
.metric-label {{
    color: {TEXT_PRIMARY};
    font-size: 13px;
    font-weight: bold;
}}
.metric-sub {{
    color: {TEXT_SECONDARY};
    font-size: 11px;
}}
.pct-label {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
}}
.dim-text {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
.session-text {{
    color: {TEXT_LINK};
    font-size: 11px;
}}
.updated-text {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
.error-text {{
    color: #ef4444;
    font-size: 11px;
}}
separator {{
    background-color: {SEPARATOR_COLOR};
    min-height: 1px;
}}
""".encode()


class UsagePopup(Gtk.Window):
    """Detailed popup window showing usage bars, sessions, and model breakdown."""

    def __init__(self, config: dict):
        super().__init__(title="Claude Usage", type=Gtk.WindowType.TOPLEVEL)
        self.config = config
        self.set_default_size(520, -1)
        self.set_resizable(False)
        self.set_decorated(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_position(Gtk.WindowPosition.MOUSE)
        self.connect("delete-event", self._on_delete)

        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._main_box.set_margin_top(20)
        self._main_box.set_margin_bottom(20)
        self._main_box.set_margin_start(24)
        self._main_box.set_margin_end(24)
        self.add(self._main_box)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._main_box.pack_start(self._content_box, False, False, 0)

    def _on_delete(self, *args):
        self.hide()
        return True

    def _clear(self):
        for child in self._content_box.get_children():
            child.destroy()

    def _add_section_header(self, title: str, right_text: str = ""):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label=title)
        lbl.get_style_context().add_class("section-header")
        lbl.set_halign(Gtk.Align.START)
        box.pack_start(lbl, True, True, 0)

        if right_text:
            r = Gtk.Label(label=right_text)
            r.get_style_context().add_class("section-right")
            box.pack_end(r, False, False, 0)

        self._content_box.pack_start(box, False, False, 0)

    def _add_usage_row(self, label: str, subtitle: str, fraction: float):
        """Add a row: Label [====bar====] XX% used"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        row.set_margin_bottom(16)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_size_request(140, -1)

        name_lbl = Gtk.Label(label=label)
        name_lbl.get_style_context().add_class("metric-label")
        name_lbl.set_halign(Gtk.Align.START)
        left.pack_start(name_lbl, False, False, 0)

        if subtitle:
            sub_lbl = Gtk.Label(label=subtitle)
            sub_lbl.get_style_context().add_class("metric-sub")
            sub_lbl.set_halign(Gtk.Align.START)
            left.pack_start(sub_lbl, False, False, 0)

        row.pack_start(left, False, False, 0)

        bar = Gtk.DrawingArea()
        bar.set_size_request(200, 12)
        bar.set_valign(Gtk.Align.CENTER)

        def draw_bar(widget, cr):
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            r, g, b = _hex_to_rgb(BAR_TRACK)
            cr.set_source_rgb(r, g, b)
            _rounded_rect(cr, 0, 0, w, h, 6)
            cr.fill()
            if fraction > 0:
                fill_w = max(w * min(fraction, 1.0), h)
                r, g, b = _hex_to_rgb(BAR_BLUE)
                cr.set_source_rgb(r, g, b)
                _rounded_rect(cr, 0, 0, fill_w, h, 6)
                cr.fill()

        bar.connect("draw", draw_bar)
        row.pack_start(bar, True, True, 0)

        pct_lbl = Gtk.Label(label=f"{int(fraction * 100)}% used")
        pct_lbl.get_style_context().add_class("pct-label")
        pct_lbl.set_size_request(72, -1)
        pct_lbl.set_halign(Gtk.Align.END)
        row.pack_end(pct_lbl, False, False, 0)

        self._content_box.pack_start(row, False, False, 0)

    def _add_separator(self):
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(16)
        self._content_box.pack_start(sep, False, False, 0)

    def update(self, stats: UsageStats):
        self._clear()

        self._add_section_header("Plan usage limits")
        self._add_usage_row(
            "Current session",
            _format_reset_duration(stats.session_reset),
            stats.session_utilization,
        )

        self._add_separator()

        self._add_section_header("Weekly limits")
        self._add_usage_row(
            "All models",
            _format_reset_day(stats.weekly_reset),
            stats.weekly_utilization,
        )

        self._add_separator()

        self._add_section_header(
            "Active sessions",
            f"{len(stats.active_sessions)} running",
        )

        if stats.active_sessions:
            for sess in stats.active_sessions:
                started = datetime.fromtimestamp(sess["startedAt"] / 1000)
                duration = datetime.now() - started
                cwd = sess.get("cwd", "?").replace(os.path.expanduser("~"), "~")

                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row.set_margin_bottom(6)

                lbl = Gtk.Label(label=cwd)
                lbl.get_style_context().add_class("session-text")
                lbl.set_halign(Gtk.Align.START)
                lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                row.pack_start(lbl, True, True, 0)

                dur = Gtk.Label(label=_format_session_duration(int(duration.total_seconds())))
                dur.get_style_context().add_class("dim-text")
                row.pack_end(dur, False, False, 0)

                self._content_box.pack_start(row, False, False, 0)
        else:
            lbl = Gtk.Label(label="No active sessions")
            lbl.get_style_context().add_class("dim-text")
            lbl.set_halign(Gtk.Align.START)
            self._content_box.pack_start(lbl, False, False, 0)

        self._add_separator()

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        updated = Gtk.Label(label="Last updated: just now")
        updated.get_style_context().add_class("updated-text")
        footer.pack_start(updated, True, True, 0)

        if stats.rate_limit_error:
            err = Gtk.Label(label=f"API: {stats.rate_limit_error}")
            err.get_style_context().add_class("error-text")
            footer.pack_end(err, False, False, 0)

        self._content_box.pack_start(footer, False, False, 0)
        self._content_box.show_all()


class ClaudeUsageTray:
    """System tray icon with menu and periodic refresh."""

    def __init__(self, config: dict):
        self.config = config
        self.stats = UsageStats()
        self._alive = True
        self._refreshing = False

        self.indicator = AppIndicator.Indicator.new(
            "claude-usage",
            os.path.abspath(ICON_PATH),
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

        menu = Gtk.Menu()

        self.mi_session = Gtk.MenuItem(label="Session: ...")
        self.mi_session.set_sensitive(False)
        menu.append(self.mi_session)

        self.mi_week = Gtk.MenuItem(label="Weekly: ...")
        self.mi_week.set_sensitive(False)
        menu.append(self.mi_week)

        menu.append(Gtk.SeparatorMenuItem())

        mi_details = Gtk.MenuItem(label="Details...")
        mi_details.connect("activate", self._on_show_details)
        menu.append(mi_details)

        mi_refresh = Gtk.MenuItem(label="Refresh")
        mi_refresh.connect("activate", lambda _: self._refresh_async())
        menu.append(mi_refresh)

        menu.append(Gtk.SeparatorMenuItem())

        self.mi_osd = Gtk.CheckMenuItem(label="OSD Overlay")
        self.mi_osd.set_active(True)
        self.mi_osd.connect("toggled", self._on_toggle_osd)
        menu.append(self.mi_osd)

        opacity_item = Gtk.MenuItem(label="OSD Opacity")
        opacity_menu = Gtk.Menu()
        for pct in [100, 75, 50, 25]:
            mi = Gtk.MenuItem(label=f"{pct}%")
            mi.connect("activate", self._on_set_opacity, pct / 100.0)
            opacity_menu.append(mi)
        opacity_item.set_submenu(opacity_menu)
        menu.append(opacity_item)

        menu.append(Gtk.SeparatorMenuItem())

        mi_quit = Gtk.MenuItem(label="Quit")
        mi_quit.connect("activate", self._on_quit)
        menu.append(mi_quit)

        menu.show_all()
        self.indicator.set_menu(menu)

        self.popup = UsagePopup(config)
        self.overlay = UsageOverlay(config)
        self.overlay.show_all()

        self._refresh_async()
        GLib.timeout_add_seconds(config["refresh_seconds"], self._on_timer)

    def _refresh_async(self):
        """Run data collection in a background thread to avoid blocking GTK."""
        if self._refreshing or not self._alive:
            return
        self._refreshing = True

        def _worker():
            try:
                stats = collect_all(self.config)
            except Exception:
                stats = UsageStats(rate_limit_error="Collection failed")
            if self._alive:
                GLib.idle_add(self._apply_stats, stats)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_stats(self, stats):
        """Apply collected stats to the UI (must run on GTK main thread)."""
        self._refreshing = False
        if not self._alive:
            return False
        self.stats = stats

        session_pct = int(stats.session_utilization * 100)
        week_pct = int(stats.weekly_utilization * 100)

        self.mi_session.set_label(f"Session: {session_pct}% used")
        self.mi_week.set_label(f"Weekly: {week_pct}% used")
        self.indicator.set_label(f"{session_pct}%", "")

        self.popup.update(stats)
        self.overlay.update(stats)
        return False  # remove from idle queue

    def _on_timer(self):
        if not self._alive:
            return False
        self._refresh_async()
        return True

    def _on_show_details(self, _):
        self.popup.show_all()
        self.popup.present()

    def _on_toggle_osd(self, widget):
        if widget.get_active():
            self.overlay.show_all()
        else:
            self.overlay.hide()

    def _on_set_opacity(self, _, value):
        self.overlay.set_opacity(value)

    def _on_quit(self, _):
        self._alive = False
        Gtk.main_quit()
