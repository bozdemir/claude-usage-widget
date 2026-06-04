"""Cross-platform system-tray / menu-bar indicator.

Two backends, picked in order by :func:`try_create`:

1. **AyatanaAppIndicator3** (Linux / GNOME / Ubuntu) — shows a live text
   label ("C: 42% | W: 71%") right in the top bar. Runs a GTK main loop in
   a background daemon thread; all GTK calls are marshalled through
   ``GLib.idle_add`` so they execute on the GTK thread.
2. **QSystemTrayIcon** (macOS menu bar, Windows notification area, and any
   Linux DE with a tray) — pure Qt, no extra dependency. macOS can't show a
   live text label next to a tray icon, so the stats live in the dropdown
   menu and the hover tooltip instead.

If neither backend is available the widget runs fine without a tray.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_usage.collector import UsageStats

_ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")
_ICON_SVG = os.path.join(_ICON_DIR, "claude-tray.svg")
# AppIndicator resolves names against the active icon theme; to use our own
# SVG we must register its directory as an icon-theme path first.
_ICON_THEME_NAME = "claude-tray" if os.path.exists(_ICON_SVG) else None


def _try_import_gtk():
    """Return (AyatanaAppIndicator3, GLib, Gtk) or raise ImportError."""
    import gi
    gi.require_version("AyatanaAppIndicator3", "0.1")
    gi.require_version("Gtk", "3.0")
    from gi.repository import AyatanaAppIndicator3, GLib, Gtk
    return AyatanaAppIndicator3, GLib, Gtk


def _format_label(stats: UsageStats) -> str:
    """Shared "C: 42% | W: 71%" label used by both backends."""
    s_pct = int(stats.session_utilization * 100)
    w_pct = int(stats.weekly_utilization * 100)
    return f"C: {s_pct}% | W: {w_pct}%"


class AppIndicatorTray:
    """Linux/GNOME top-bar indicator showing session + weekly utilisation."""

    def __init__(self, on_toggle_widget=None, on_quit=None) -> None:
        AyatanaAppIndicator3, GLib, Gtk = _try_import_gtk()
        self._GLib = GLib
        self._Gtk = Gtk
        self._on_quit = on_quit

        icon_name = _ICON_THEME_NAME or "dialog-information"
        self._indicator = AyatanaAppIndicator3.Indicator.new(
            "claude-usage",
            icon_name,
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        if _ICON_THEME_NAME:
            self._indicator.set_icon_theme_path(_ICON_DIR)
        self._indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_label("C: …", "C: 100% | W: 100%")

        # GTK needs a non-empty menu to show the indicator on some DE versions.
        menu = Gtk.Menu()

        if on_toggle_widget is not None:
            item_toggle = Gtk.MenuItem(label="Show/Hide widget")
            item_toggle.connect("activate", lambda _: on_toggle_widget())
            menu.append(item_toggle)
            menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Quit claude-usage")
        item_quit.connect("activate", self._on_quit_clicked)
        menu.append(item_quit)
        menu.show_all()
        self._indicator.set_menu(menu)

        # Start GTK main loop in a daemon thread.
        self._loop = GLib.MainLoop()
        t = threading.Thread(target=self._loop.run, daemon=True)
        t.start()

    def update(self, stats: UsageStats) -> None:
        """Update the label from any thread (marshalled to GTK thread)."""
        label = _format_label(stats)
        # guide string sets the column-width so the panel doesn't jitter
        guide = "C: 100% | W: 100%"
        indicator = self._indicator
        self._GLib.idle_add(indicator.set_label, label, guide)

    def _on_quit_clicked(self, _item) -> None:
        # Stop the GTK loop, then hand off to the app's quit callback (which
        # tears down the Qt side). Without on_quit we only stop GTK and the
        # widget keeps running — historical behaviour, preserved as fallback.
        self._loop.quit()
        if self._on_quit is not None:
            self._on_quit()

    def destroy(self) -> None:
        self._GLib.idle_add(self._loop.quit)


class QtSystemTray:
    """Cross-platform tray via :class:`QSystemTrayIcon`.

    Works on macOS (menu bar), Windows (notification area), and Linux DEs
    with a system tray. Must be constructed on the GUI thread with a live
    ``QApplication``. macOS shows only the icon in the menu bar — the live
    stats surface in the dropdown menu and the tooltip.
    """

    def __init__(self, on_toggle_widget=None, on_quit=None) -> None:
        from PySide6.QtWidgets import (
            QApplication,
            QMenu,
            QStyle,
            QSystemTrayIcon,
        )
        from PySide6.QtGui import QAction, QIcon

        if QApplication.instance() is None:
            raise RuntimeError("QtSystemTray needs a running QApplication")
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("No system tray available on this platform")

        icon = QIcon(_ICON_SVG) if os.path.exists(_ICON_SVG) else QIcon()
        if icon.isNull():
            # Fall back to a stock icon so the menu bar still shows something.
            icon = QApplication.instance().style().standardIcon(
                QStyle.SP_ComputerIcon
            )

        self._tray = QSystemTrayIcon(icon)
        self._tray.setToolTip("Claude Usage")

        menu = QMenu()
        # First row mirrors the AppIndicator label; disabled so it reads as a
        # header rather than a clickable item.
        self._status_action = QAction("C: … | W: …", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)
        menu.addSeparator()

        if on_toggle_widget is not None:
            act_toggle = QAction("Show/Hide widget", menu)
            act_toggle.triggered.connect(lambda: on_toggle_widget())
            menu.addAction(act_toggle)

        act_quit = QAction("Quit claude-usage", menu)
        if on_quit is not None:
            act_quit.triggered.connect(lambda: on_quit())
        else:
            act_quit.triggered.connect(
                lambda: QApplication.instance().quit()
            )
        menu.addAction(act_quit)

        # Keep a reference so the menu isn't garbage-collected.
        self._menu = menu
        self._tray.setContextMenu(menu)
        # On macOS a left-click opens the same menu (no separate activate
        # gesture), so wire activation to toggle the widget when present.
        if on_toggle_widget is not None:
            self._tray.activated.connect(
                lambda reason: self._on_activated(reason, on_toggle_widget)
            )
        self._tray.show()

    @staticmethod
    def _on_activated(reason, on_toggle_widget) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        # Trigger / DoubleClick = left-click on the icon. Right-click already
        # raises the context menu, so don't double-fire on Context.
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
        ):
            on_toggle_widget()

    def update(self, stats: UsageStats) -> None:
        """Refresh the menu header + tooltip (already on the GUI thread)."""
        label = _format_label(stats)
        self._status_action.setText(label)
        self._tray.setToolTip(f"Claude Usage — {label}")

    def destroy(self) -> None:
        self._tray.hide()


def try_create(on_toggle_widget=None, on_quit=None):
    """Return the best available tray backend, or ``None``.

    Tries the GTK AppIndicator first (richest experience on GNOME/Ubuntu —
    it shows a live text label), then falls back to the Qt system tray
    (macOS / Windows / other Linux DEs). Returns ``None`` only when neither
    is available, in which case the widget runs without a tray.
    """
    # GTK AppIndicator — Linux/GNOME only; raises on macOS/Windows where
    # PyGObject or the indicator library isn't present.
    try:
        return AppIndicatorTray(
            on_toggle_widget=on_toggle_widget, on_quit=on_quit
        )
    except (ImportError, ValueError):
        pass

    # Qt system tray — cross-platform fallback (this is the macOS path).
    try:
        return QtSystemTray(
            on_toggle_widget=on_toggle_widget, on_quit=on_quit
        )
    except Exception:
        return None
