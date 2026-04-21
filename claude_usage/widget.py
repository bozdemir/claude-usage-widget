"""System tray icon and detailed popup window."""

from __future__ import annotations

import math
import os
import threading
from datetime import datetime
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import Gtk, GLib, Gdk, Pango  # type: ignore[attr-defined]
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # type: ignore[attr-defined]

from claude_usage.collector import collect_all, UsageStats
from claude_usage.forecast import format_forecast
from claude_usage.notifier import UsageNotifier
from claude_usage.overlay import UsageOverlay
from claude_usage.themes import get_theme

if TYPE_CHECKING:
    import cairo


ICON_PATH = os.path.join(os.path.dirname(__file__), "icons", "claude-tray.svg")


def _build_css(theme: dict[str, str]) -> bytes:
    """Render the application-wide CSS string from a theme color dict.

    All named color roles resolve to the given theme, so swapping themes
    regenerates the stylesheet with a single call.  Font sizes step down
    intentionally: 14 px headers → 13 px metric labels → 12 px supporting
    text → 11 px metadata/dim.
    """
    return f"""
window {{
    background-color: {theme["bg"]};
}}
.section-header {{
    color: {theme["text_primary"]};
    font-size: 14px;
    font-weight: bold;
}}
.section-right {{
    color: {theme["text_secondary"]};
    font-size: 12px;
    font-style: italic;
}}
.metric-label {{
    color: {theme["text_primary"]};
    font-size: 13px;
    font-weight: bold;
}}
.metric-sub {{
    color: {theme["text_secondary"]};
    font-size: 11px;
}}
.pct-label {{
    color: {theme["text_secondary"]};
    font-size: 12px;
}}
.dim-text {{
    color: {theme["text_dim"]};
    font-size: 11px;
}}
.session-text {{
    color: {theme["text_link"]};
    font-size: 11px;
}}
.updated-text {{
    color: {theme["text_dim"]};
    font-size: 11px;
}}
.error-text {{
    color: {theme["error"]};
    font-size: 11px;
}}
separator {{
    background-color: {theme["separator"]};
    min-height: 1px;
}}
""".encode()


def _rounded_rect(
    cr: cairo.Context,
    x: float,
    y: float,
    w: float,
    h: float,
    r: float,
) -> None:
    """Trace a rounded-rectangle path onto Cairo context *cr*."""
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


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """Convert a ``#RRGGBB`` hex string to an ``(r, g, b)`` float triple."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)


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


def _format_session_duration(total_seconds: int) -> str:
    """Format a duration in seconds as ``Xh Ym`` or ``Ym``."""
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class UsagePopup(Gtk.Window):
    """Detailed popup window showing usage bars, sessions, and model breakdown."""

    _css_loaded: bool = False

    def __init__(self, config: dict[str, object]) -> None:
        super().__init__(title="Claude Usage", type=Gtk.WindowType.TOPLEVEL)
        self.config = config
        # Resolve the theme once per popup instance. Drawing callbacks and
        # anything that needs raw color values (Cairo fills, etc.) read from
        # self._theme directly so that a single config value controls both
        # CSS and custom-drawn widgets.
        self._theme: dict[str, str] = get_theme(
            str(config.get("theme", "default"))
        )
        self.set_default_size(520, -1)
        self.set_resizable(False)
        self.set_decorated(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_position(Gtk.WindowPosition.MOUSE)
        self.connect("delete-event", self._on_delete)

        # Install the application-wide CSS exactly once, no matter how many
        # UsagePopup instances are created (normally just one).
        if not UsagePopup._css_loaded:
            css = Gtk.CssProvider()
            css.load_from_data(_build_css(self._theme))
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            UsagePopup._css_loaded = True

        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._main_box.set_margin_top(20)
        self._main_box.set_margin_bottom(20)
        self._main_box.set_margin_start(24)
        self._main_box.set_margin_end(24)
        self.add(self._main_box)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._main_box.pack_start(self._content_box, False, False, 0)

    def _on_delete(self, widget: Gtk.Widget, event: Gdk.Event) -> bool:
        """Hide instead of destroying so the window can be re-shown later."""
        self.hide()
        return True

    def _clear(self) -> None:
        """Destroy all child widgets inside the content box."""
        for child in self._content_box.get_children():
            child.destroy()

    def _add_section_header(self, title: str, right_text: str = "") -> None:
        """Append a bold section heading with an optional right-aligned subtitle."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label=title)
        lbl.get_style_context().add_class("section-header")
        lbl.set_halign(Gtk.Align.START)
        box.pack_start(lbl, True, True, 0)

        if right_text:
            right_lbl = Gtk.Label(label=right_text)
            right_lbl.get_style_context().add_class("section-right")
            box.pack_end(right_lbl, False, False, 0)

        self._content_box.pack_start(box, False, False, 0)

    def _add_usage_row(self, label: str, subtitle: str, fraction: float) -> None:
        """Add a row: Label [====bar====] XX% used."""
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

        theme = self._theme

        def _draw_bar(widget: Gtk.DrawingArea, cr: cairo.Context) -> None:
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            # Draw the empty track first, then paint the filled portion on top.
            tr, tg, tb = _hex_to_rgb(theme["bar_track"])
            cr.set_source_rgb(tr, tg, tb)
            _rounded_rect(cr, 0, 0, w, h, 6)
            cr.fill()
            if fraction > 0:
                # Clamp to 100% and enforce a minimum pill width equal to the
                # bar height so the rounded caps always render correctly.
                fill_w = max(w * min(fraction, 1.0), h)
                fr, fg, fb = _hex_to_rgb(theme["bar_blue"])
                cr.set_source_rgb(fr, fg, fb)
                _rounded_rect(cr, 0, 0, fill_w, h, 6)
                cr.fill()

        bar.connect("draw", _draw_bar)
        row.pack_start(bar, True, True, 0)

        pct_lbl = Gtk.Label(label=f"{min(int(fraction * 100), 100)}% used")
        pct_lbl.get_style_context().add_class("pct-label")
        pct_lbl.set_size_request(72, -1)
        pct_lbl.set_halign(Gtk.Align.END)
        row.pack_end(pct_lbl, False, False, 0)

        self._content_box.pack_start(row, False, False, 0)

    def _add_sparkline(self, buckets: list[float], label: str) -> None:
        """Append a vertical-bar sparkline with a caption underneath.

        Each bucket is drawn as a thin vertical bar whose height is proportional
        to its utilization (0.0-1.0). Empty buckets are skipped.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_bottom(12)

        area = Gtk.DrawingArea()
        area.set_size_request(-1, 32)

        theme = self._theme

        def draw(widget: Gtk.Widget, cr: cairo.Context) -> None:
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            r, g, b = _hex_to_rgb(theme["bar_track"])
            cr.set_source_rgb(r, g, b)
            _rounded_rect(cr, 0, 0, w, h, 4)
            cr.fill()
            if not buckets:
                return
            n = len(buckets)
            gap = 1.0
            bar_w = max(1.0, (w - (n - 1) * gap) / n)
            r, g, b = _hex_to_rgb(theme["bar_blue"])
            cr.set_source_rgb(r, g, b)
            for i, val in enumerate(buckets):
                if val <= 0:
                    continue
                bx = i * (bar_w + gap)
                bh = max(1.0, h * min(float(val), 1.0))
                cr.rectangle(bx, h - bh, bar_w, bh)
            cr.fill()

        area.connect("draw", draw)
        box.pack_start(area, False, False, 0)

        lbl = Gtk.Label(label=label)
        lbl.get_style_context().add_class("dim-text")
        lbl.set_halign(Gtk.Align.START)
        box.pack_start(lbl, False, False, 0)

        self._content_box.pack_start(box, False, False, 0)

    def _add_dim_line(self, text: str, bottom_margin: int = 8) -> None:
        """Append a single left-aligned line styled with ``.dim-text``."""
        lbl = Gtk.Label(label=text)
        lbl.get_style_context().add_class("dim-text")
        lbl.set_halign(Gtk.Align.START)
        lbl.set_margin_bottom(bottom_margin)
        self._content_box.pack_start(lbl, False, False, 0)

    def _add_metric_line(self, text: str, bottom_margin: int = 2) -> None:
        """Append a single left-aligned line styled with ``.metric-label``."""
        lbl = Gtk.Label(label=text)
        lbl.get_style_context().add_class("metric-label")
        lbl.set_halign(Gtk.Align.START)
        lbl.set_margin_bottom(bottom_margin)
        self._content_box.pack_start(lbl, False, False, 0)

    def _add_separator(self) -> None:
        """Append a styled horizontal separator."""
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(16)
        self._content_box.pack_start(sep, False, False, 0)

    def update(self, stats: UsageStats) -> None:
        """Rebuild the popup contents from the latest ``UsageStats``.

        Destroys all existing child widgets and recreates them so that layout
        reflects the current data.  Called from the GTK main thread each time
        a background refresh completes.
        """
        self._clear()

        self._add_section_header("Plan usage limits")
        self._add_usage_row(
            "Current session",
            _format_reset_duration(stats.session_reset),
            stats.session_utilization,
        )
        session_forecast = format_forecast(stats.session_forecast)
        if session_forecast:
            self._add_dim_line(session_forecast)
        self._add_sparkline(stats.session_history, "Last 5 hours")

        self._add_separator()

        self._add_section_header("Weekly limits")
        self._add_usage_row(
            "All models",
            _format_reset_day(stats.weekly_reset),
            stats.weekly_utilization,
        )
        weekly_forecast = format_forecast(stats.weekly_forecast)
        if weekly_forecast:
            self._add_dim_line(weekly_forecast)
        self._add_sparkline(stats.weekly_history, "Last 7 days")

        self._add_separator()

        # Cost + top-projects block — only rendered when there is data for today.
        today_cost = float(getattr(stats, "today_cost", 0.0) or 0.0)
        cache_savings = float(getattr(stats, "cache_savings", 0.0) or 0.0)
        today_projects = getattr(stats, "today_by_project", {}) or {}

        if today_cost > 0:
            self._add_section_header("Cost (today)")
            self._add_metric_line(f"${today_cost:.2f}")
            self._add_dim_line(f"${cache_savings:.2f} saved by cache", bottom_margin=12)
            self._add_separator()

        if today_projects:
            self._add_section_header("Top projects today")
            # today_projects may be a plain dict or an ordered mapping of
            # (project -> tokens). Show the top 5 by tokens descending.
            try:
                items = sorted(
                    today_projects.items(), key=lambda kv: kv[1], reverse=True
                )
            except (TypeError, AttributeError):
                items = list(today_projects.items()) if hasattr(today_projects, "items") else []
            for name, tokens in items[:5]:
                try:
                    tokens_int = int(tokens)
                except (TypeError, ValueError):
                    tokens_int = 0
                # Express in thousands for compactness (matches "XXXk tokens").
                k = tokens_int // 1000
                self._add_dim_line(f"{name}: {k}k tokens", bottom_margin=4)
            self._add_separator()

        self._add_section_header(
            "Active sessions",
            f"{len(stats.active_sessions)} running",
        )

        if stats.active_sessions:
            for sess in stats.active_sessions:
                # startedAt is a JavaScript-style millisecond epoch; divide by
                # 1000 to convert to the seconds expected by fromtimestamp.
                started = datetime.fromtimestamp(sess.get("startedAt", 0) / 1000)
                duration = datetime.now() - started
                # Replace the home directory prefix with ~ for compact display.
                cwd: str = sess.get("cwd", "?").replace(
                    os.path.expanduser("~"), "~"
                )

                sess_row = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=8
                )
                sess_row.set_margin_bottom(6)

                path_lbl = Gtk.Label(label=cwd)
                path_lbl.get_style_context().add_class("session-text")
                path_lbl.set_halign(Gtk.Align.START)
                path_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                sess_row.pack_start(path_lbl, True, True, 0)

                dur_lbl = Gtk.Label(
                    label=_format_session_duration(int(duration.total_seconds()))
                )
                dur_lbl.get_style_context().add_class("dim-text")
                sess_row.pack_end(dur_lbl, False, False, 0)

                self._content_box.pack_start(sess_row, False, False, 0)
        else:
            empty_lbl = Gtk.Label(label="No active sessions")
            empty_lbl.get_style_context().add_class("dim-text")
            empty_lbl.set_halign(Gtk.Align.START)
            self._content_box.pack_start(empty_lbl, False, False, 0)

        self._add_separator()

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        updated_lbl = Gtk.Label(label="Last updated: just now")
        updated_lbl.get_style_context().add_class("updated-text")
        footer.pack_start(updated_lbl, True, True, 0)

        if stats.rate_limit_error:
            err_lbl = Gtk.Label(label=f"API: {stats.rate_limit_error}")
            err_lbl.get_style_context().add_class("error-text")
            footer.pack_end(err_lbl, False, False, 0)

        self._content_box.pack_start(footer, False, False, 0)
        self._content_box.show_all()


class ClaudeUsageTray:
    """System tray indicator that displays Claude API usage.

    Owns the AppIndicator icon, the right-click menu, the :class:`UsagePopup`
    detail window, and the on-screen :class:`UsageOverlay`.  A GLib timer fires
    every ``config["refresh_seconds"]`` seconds and triggers a background data
    collection cycle.

    Threading model
    ---------------
    Two boolean flags coordinate the background refresh cycle:

    ``_alive``
        Set to ``False`` only when the user chooses Quit.  Every callback that
        touches GTK widgets checks this flag first so that nothing runs after
        ``Gtk.main_quit()`` has been called and GTK's internal state is being
        torn down.

    ``_refreshing``
        Acts as a single-flight guard: set to ``True`` the moment a worker
        thread is spawned and cleared back to ``False`` inside
        :meth:`_apply_stats` (which runs on the GTK main thread via
        ``GLib.idle_add``).  This prevents overlapping collection runs if the
        timer fires again before the previous one finishes.
    """

    def __init__(self, config: dict[str, object]) -> None:
        self.config = config
        self.stats: UsageStats = UsageStats()
        # _alive guards all post-quit GTK access (see class docstring).
        self._alive: bool = True
        # _refreshing prevents concurrent collection runs (see class docstring).
        self._refreshing: bool = False

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
        mi_refresh.connect("activate", lambda _w: self._refresh_async())
        menu.append(mi_refresh)

        menu.append(Gtk.SeparatorMenuItem())

        self.mi_osd = Gtk.CheckMenuItem(label="OSD Overlay")
        self.mi_osd.set_active(True)
        self.mi_osd.connect("toggled", self._on_toggle_osd)
        menu.append(self.mi_osd)

        opacity_item = Gtk.MenuItem(label="OSD Opacity")
        opacity_menu = Gtk.Menu()
        for pct in (100, 75, 50, 25):
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

        self.popup: UsagePopup = UsagePopup(config)
        self.overlay: UsageOverlay = UsageOverlay(config)
        self.overlay.show_all()
        self.notifier = UsageNotifier(config)

        # Populate the UI immediately, then register the recurring timer.
        self._refresh_async()
        self._timer_id: int = GLib.timeout_add_seconds(
            config["refresh_seconds"], self._on_timer
        )

    def _refresh_async(self) -> None:
        """Spawn a daemon thread to collect usage data without blocking the UI.

        Returns immediately if a refresh is already in flight (``_refreshing``)
        or the application is shutting down (``_alive`` is ``False``).  On
        completion the worker re-enters the GTK main thread via
        ``GLib.idle_add`` so that widget updates are always made from the
        correct thread.
        """
        if self._refreshing or not self._alive:
            return
        self._refreshing = True

        def _worker() -> None:
            try:
                stats = collect_all(self.config)
            except Exception:
                stats = UsageStats(rate_limit_error="Collection failed")
            # Schedule the UI update on the GTK main thread; skip if we quit
            # while the thread was running.
            if self._alive:
                GLib.idle_add(self._apply_stats, stats)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_stats(self, stats: UsageStats) -> bool:
        """Push freshly collected stats into every UI surface.

        Called exclusively from ``GLib.idle_add``, guaranteeing execution on
        the GTK main thread.  Clears ``_refreshing`` so the next timer tick
        can start a new collection run.

        Returns ``False`` to tell GLib not to reschedule this idle callback.
        """
        # Clear the guard before any early return so a later refresh can proceed.
        self._refreshing = False
        if not self._alive:
            return False
        self.stats = stats

        session_pct = int(stats.session_utilization * 100)
        week_pct = int(stats.weekly_utilization * 100)

        self.mi_session.set_label(f"Session: {session_pct}% used")
        self.mi_week.set_label(f"Weekly: {week_pct}% used")
        # The second argument to set_label is the accessible description shown
        # to screen readers / the panel when the icon itself is not visible.
        self.indicator.set_label(f"{session_pct}%", "")

        self.popup.update(stats)
        self.overlay.update(stats)
        self.notifier.check_stats(stats)
        return False  # remove from idle queue

    def _on_timer(self) -> bool:
        """GLib timeout callback. Returns ``True`` to keep the timer alive."""
        if not self._alive:
            return False
        self._refresh_async()
        return True

    def _on_show_details(self, _widget: Gtk.MenuItem) -> None:
        """Open (or re-show) the detailed usage popup."""
        self.popup.show_all()
        self.popup.present()

    def _on_toggle_osd(self, widget: Gtk.CheckMenuItem) -> None:
        """Show or hide the OSD overlay based on the check-menu state."""
        if widget.get_active():
            self.overlay.show_all()
        else:
            self.overlay.hide()

    def _on_set_opacity(self, _widget: Gtk.MenuItem, value: float) -> None:
        """Set the OSD overlay opacity from the submenu selection."""
        self.overlay.set_opacity(value)

    def _on_quit(self, _widget: Gtk.MenuItem) -> None:
        """Shut down the application cleanly."""
        # Mark dead before removing the timer so any in-flight idle callback
        # that fires during teardown sees _alive=False and exits cleanly.
        self._alive = False
        GLib.source_remove(self._timer_id)
        Gtk.main_quit()
