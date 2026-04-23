"""Detailed popup window + application orchestrator (PySide6).

No system-tray icon: the :class:`ClaudeUsageApp` wires the OSD overlay to a
context menu (right-click) and a detail popup (left-click).  All background
data collection runs in a daemon thread and posts results back to the GUI
via a thread-safe signal.
"""

from __future__ import annotations

import os
import sys
import threading
import warnings
from datetime import datetime
from typing import Any

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from claude_usage.collector import UsageStats, collect_all
from claude_usage.forecast import format_forecast
from claude_usage.notifier import UsageNotifier
from claude_usage.overlay import UsageOverlay, _hex_to_qcolor
from claude_usage.pricing import MODEL_PRICING, calculate_cost
from claude_usage.themes import get_theme


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
POPUP_WIDTH = 520
POPUP_PAD = 24
HEATMAP_HEIGHT = 18
SPARKLINE_HEIGHT = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_tokens(n: int) -> str:
    """Format a token count compactly: ``1234567 -> '1.2M'``, ``5400 -> '5.4K'``."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _short_model_name(model: str) -> str:
    """Strip ``claude-`` prefix and trailing date for compact display."""
    m = model.removeprefix("claude-")
    if len(m) >= 9 and m[-9:-8] == "-" and m[-8:].isdigit():
        m = m[:-9]
    return m


def _prettify_project_name(name: str) -> str:
    """Convert Claude Code's dashed path (``-home-user-proj``) to ``~/proj``."""
    if not name:
        return "?"
    home_dashed = os.path.expanduser("~").replace("/", "-")
    if name == home_dashed:
        return "~"
    if name.startswith(home_dashed + "-"):
        return "~/" + name[len(home_dashed) + 1:]
    return name


def _format_reset_duration(reset_ts: int) -> str:
    """``'Resets in 3 hr 28 min'`` / ``'Resets in 45 min'`` / ``''``."""
    if reset_ts <= 0:
        return ""
    remaining = int(reset_ts - datetime.now().timestamp())
    if remaining <= 0:
        return "Resets soon"
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    if hours > 0:
        return f"Resets in {hours} hr {minutes} min"
    return f"Resets in {minutes} min"


def _format_reset_day(reset_ts: int) -> str:
    """``'Resets Mon 04:00 PM'`` / ``''``."""
    if reset_ts <= 0:
        return ""
    return datetime.fromtimestamp(reset_ts).strftime("Resets %a %I:%M %p")


def _format_session_duration(total_seconds: int) -> str:
    hours, rem = divmod(total_seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"


# ---------------------------------------------------------------------------
# Custom-painted atomic widgets
# ---------------------------------------------------------------------------

class _ProgressBar(QWidget):
    """Thin rounded bar, fill colour depends on utilisation."""

    def __init__(self, theme: dict[str, str], height: int = 12) -> None:
        super().__init__()
        self._theme = theme
        self._fraction = 0.0
        self.setFixedHeight(height)

    def set_fraction(self, value: float) -> None:
        self._fraction = max(0.0, min(1.0, float(value)))
        self.update()

    def set_theme(self, theme: dict[str, str]) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        p.setPen(Qt.NoPen)
        p.setBrush(_hex_to_qcolor(self._theme["bar_track"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        if self._fraction > 0:
            fill_w = max(w * self._fraction, h)
            p.setBrush(_hex_to_qcolor(self._theme["bar_blue"]))
            p.drawRoundedRect(QRectF(0, 0, fill_w, h), r, r)


class _Sparkline(QWidget):
    """Vertical-bar sparkline of per-bucket utilisation values."""

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme
        self._buckets: list[float] = []
        self.setFixedHeight(SPARKLINE_HEIGHT)

    def set_buckets(self, buckets: list[float]) -> None:
        self._buckets = list(buckets or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(Qt.NoPen)
        p.setBrush(_hex_to_qcolor(self._theme["bar_track"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), 4, 4)

        if not self._buckets:
            return
        n = len(self._buckets)
        gap = 1.0
        bar_w = max(1.0, (w - (n - 1) * gap) / n)
        fill = _hex_to_qcolor(self._theme["bar_blue"])
        p.setBrush(fill)
        for i, v in enumerate(self._buckets):
            if v <= 0:
                continue
            bx = i * (bar_w + gap)
            bh = max(1.0, h * min(float(v), 1.0))
            p.drawRect(QRectF(bx, h - bh, bar_w, bh))


class _Heatmap(QWidget):
    """Single-row heatmap strip (e.g. 90 daily cells)."""

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme
        self._buckets: list[float] = []
        self.setFixedHeight(HEATMAP_HEIGHT)

    def set_buckets(self, buckets: list[float]) -> None:
        self._buckets = list(buckets or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(_hex_to_qcolor(self._theme["bar_track"]))
        p.drawRect(QRectF(0, 0, w, h))

        n = len(self._buckets)
        if n == 0:
            return
        cell_w = w / n
        base = self._theme["bar_blue"]
        for i, v in enumerate(self._buckets):
            if v <= 0:
                continue
            alpha = max(0.0, min(1.0, float(v)))
            p.setBrush(_hex_to_qcolor(base, alpha))
            p.drawRect(QRectF(i * cell_w, 0, cell_w, h))


def _align_calendar_buckets(
    buckets: list[float],
    today_weekday: int | None = None,
) -> list[float]:
    """Align an oldest-first daily series to a 52×7 GitHub-style grid.

    The column-major grid has row 0 = Sunday and today pinned to the
    bottom-right column at its real weekday. Buckets older than the grid
    can hold are dropped; trailing empties are appended so future days of
    the current week render as blank cells.

    ``today_weekday`` is Python's ``datetime.weekday()`` (Mon=0..Sun=6);
    pass ``None`` to use ``datetime.now()``.
    """
    if today_weekday is None:
        today_weekday = datetime.now().weekday()
    # Convert to Sunday-indexed 0..6 to match GitHub's top-row convention.
    today_row = (today_weekday + 1) % 7
    total = 52 * 7
    trailing = 6 - today_row  # empty cells after today within current week
    usable = total - trailing  # number of real daily cells that fit
    if len(buckets) > usable:
        buckets = buckets[-usable:]
    padded = buckets + [0.0] * trailing
    # Pad the head if we had fewer buckets than usable slots.
    missing_head = total - len(padded)
    if missing_head > 0:
        padded = [0.0] * missing_head + padded
    return padded


class _CalendarHeatmap(QWidget):
    """GitHub-style calendar heatmap: 52 weeks × 7 days of peak utilization."""

    CELL_SIZE = 10
    CELL_GAP = 2
    WEEKS = 52
    DAYS = 7

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self._theme = theme
        self._buckets: list[float] = []
        total_w = self.WEEKS * (self.CELL_SIZE + self.CELL_GAP)
        total_h = self.DAYS * (self.CELL_SIZE + self.CELL_GAP)
        self.setFixedSize(total_w, total_h)

    def set_buckets(self, buckets: list[float]) -> None:
        self._buckets = list(buckets or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        track = _hex_to_qcolor(self._theme["bar_track"])
        base = self._theme["bar_blue"]
        # Draw from oldest (top-left) to newest (bottom-right).  The list is
        # already oldest-first, length WEEKS*DAYS = 364.
        n = len(self._buckets)
        for i in range(self.WEEKS * self.DAYS):
            col = i // self.DAYS
            row = i % self.DAYS
            x = col * (self.CELL_SIZE + self.CELL_GAP)
            y = row * (self.CELL_SIZE + self.CELL_GAP)
            v = self._buckets[i] if i < n else 0.0
            if v > 0:
                alpha = max(0.15, min(1.0, float(v)))
                p.setBrush(_hex_to_qcolor(base, alpha))
            else:
                p.setBrush(track)
            p.drawRect(QRectF(x, y, self.CELL_SIZE, self.CELL_SIZE))


# ---------------------------------------------------------------------------
# Detail popup
# ---------------------------------------------------------------------------

class UsagePopup(QWidget):
    """Scrollable detail window showing all :class:`UsageStats` fields."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = config
        self._theme = get_theme(str(config.get("theme", "default")))

        self.setWindowTitle("Claude Usage")
        # Resizable: set a sensible initial size and a minimum, but let the
        # user drag the window edges to widen it. A fixed width makes the
        # scrollbar overlap content and denies power users more horizontal
        # room for the per-model cost breakdown.
        self.resize(POPUP_WIDTH, 640)
        self.setMinimumWidth(420)
        self.setMinimumHeight(360)
        # Qt.Tool keeps the popup hidden from the dock / taskbar — exit is
        # via the OSD right-click menu. WindowCloseButtonHint still gives us
        # a native close button on the title bar for discoverability.
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        # Reinforce "don't show me in the dock" via the NET_WM window-type
        # hint. Utility windows are excluded from KDE/GNOME taskbars by spec.
        self.setAttribute(Qt.WA_X11NetWmWindowTypeUtility, True)

        # Style sheet — applied once per instance.
        self.setStyleSheet(self._build_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        root.addWidget(self._scroll)

        # Content container.  We rebuild its layout on every update().
        self._content = QWidget()
        self._content.setObjectName("popupRoot")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(POPUP_PAD, POPUP_PAD, POPUP_PAD, POPUP_PAD)
        self._layout.setSpacing(0)
        self._scroll.setWidget(self._content)

    # ------------------------------------------------------------------ QSS

    def _build_qss(self) -> str:
        t = self._theme
        return f"""
            QWidget#popupRoot, QScrollArea {{ background-color: {t['bg']}; }}
            QLabel {{ color: {t['text_primary']}; }}
            QLabel[role="header"] {{ font-size: 14px; font-weight: bold; color: {t['text_primary']}; }}
            QLabel[role="sub"]    {{ font-size: 11px; color: {t['text_secondary']}; }}
            QLabel[role="dim"]    {{ font-size: 11px; color: {t['text_dim']}; }}
            QLabel[role="metric"] {{ font-size: 13px; font-weight: bold; color: {t['text_primary']}; }}
            QLabel[role="pct"]    {{ font-size: 12px; color: {t['text_secondary']}; }}
            QLabel[role="link"]   {{ font-size: 11px; color: {t['text_link']}; }}
            QLabel[role="error"]  {{ font-size: 11px; color: {t['error']}; }}
        """

    # -------------------------------------------------------------- helpers

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _label(self, text: str, role: str = "") -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        # Default to plain text — never interpret user-sourced content
        # (prompt previews, AI report output, project paths) as rich HTML.
        lbl.setTextFormat(Qt.PlainText)
        if role:
            lbl.setProperty("role", role)
        return lbl

    def _add_section_header(self, title: str, right: str = "") -> None:
        from PySide6.QtWidgets import QHBoxLayout, QFrame

        row = QFrame()
        row.setStyleSheet("QFrame { background: transparent; }")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 10)

        title_lbl = self._label(title, "header")
        hl.addWidget(title_lbl, 1, Qt.AlignLeft)

        if right:
            right_lbl = self._label(right, "sub")
            hl.addWidget(right_lbl, 0, Qt.AlignRight)

        self._layout.addWidget(row)

    def _add_usage_row(self, label: str, subtitle: str, fraction: float) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QFrame

        row = QFrame()
        row.setStyleSheet("QFrame { background: transparent; }")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 14)
        hl.setSpacing(12)

        # Left: label + subtitle
        left = QWidget()
        left.setFixedWidth(140)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        name = self._label(label, "metric")
        left_layout.addWidget(name)
        if subtitle:
            left_layout.addWidget(self._label(subtitle, "sub"))
        hl.addWidget(left)

        # Middle: bar
        bar = _ProgressBar(self._theme, height=12)
        bar.set_fraction(fraction)
        hl.addWidget(bar, 1)

        # Right: percentage
        pct = self._label(f"{min(int(fraction * 100), 100)}% used", "pct")
        pct.setFixedWidth(72)
        pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(pct)

        self._layout.addWidget(row)

    def _add_dim_line(self, text: str, role: str = "dim", margin_bottom: int = 6) -> None:
        lbl = self._label(text, role)
        lbl.setContentsMargins(0, 0, 0, margin_bottom)
        self._layout.addWidget(lbl)

    def _add_sparkline(self, buckets: list[float], caption: str) -> None:
        sp = _Sparkline(self._theme)
        sp.set_buckets(buckets)
        self._layout.addWidget(sp)
        self._add_dim_line(caption, margin_bottom=12)

    def _add_heatmap(self, buckets: list[float], caption: str) -> None:
        hm = _Heatmap(self._theme)
        hm.set_buckets(buckets)
        self._layout.addWidget(hm)
        self._add_dim_line(caption, margin_bottom=12)

    def _add_calendar_heatmap(self, buckets: list[float], caption: str) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QFrame
        row = QFrame()
        row.setStyleSheet("QFrame { background: transparent; }")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        cal = _CalendarHeatmap(self._theme)
        cal.set_buckets(_align_calendar_buckets(list(buckets)))
        hl.addWidget(cal)
        hl.addStretch(1)
        self._layout.addWidget(row)
        self._add_dim_line(caption, margin_bottom=12)

    def _add_separator(self) -> None:
        from PySide6.QtWidgets import QFrame
        # Spacer above the hairline
        self._layout.addSpacing(6)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(
            f"background-color: {self._theme['separator']}; border: none;"
        )
        self._layout.addWidget(sep)
        # Spacer below the hairline
        self._layout.addSpacing(14)

    # --------------------------------------------------------------- update

    def apply_config(self, config: dict[str, Any]) -> None:
        """Re-read theme/opacity in case the user changed it at runtime."""
        self._config = config
        self._theme = get_theme(str(config.get("theme", "default")))
        self.setStyleSheet(self._build_qss())

    @Slot(object)
    def update_stats(self, stats: UsageStats) -> None:
        """Rebuild the popup contents from *stats*."""
        self._clear_layout()

        # --- Plan usage limits ---
        self._add_section_header("Plan usage limits")
        self._add_usage_row(
            "Current session",
            _format_reset_duration(stats.session_reset),
            stats.session_utilization,
        )
        s_fc = format_forecast(stats.session_forecast)
        if s_fc:
            self._add_dim_line(s_fc)
        self._add_sparkline(stats.session_history, "Last 5 hours")
        self._add_separator()

        # --- Weekly limits ---
        self._add_section_header("Weekly limits")
        self._add_usage_row(
            "All models",
            _format_reset_day(stats.weekly_reset),
            stats.weekly_utilization,
        )
        w_fc = format_forecast(stats.weekly_forecast)
        if w_fc:
            self._add_dim_line(w_fc)
        self._add_sparkline(stats.weekly_history, "Last 7 days")

        # 90-day heatmap
        heatmap = getattr(stats, "daily_heatmap", []) or []
        if any(v > 0 for v in heatmap):
            self._add_heatmap(heatmap, "Last 90 days")

        # 52-week × 7-day calendar heatmap (GitHub-style)
        yearly = getattr(stats, "yearly_heatmap", []) or []
        if any(v > 0 for v in yearly):
            self._add_calendar_heatmap(yearly, "Last 52 weeks")
        self._add_separator()

        # --- Anomaly banner ---
        anomaly = getattr(stats, "anomaly", None)
        if anomaly is not None and getattr(anomaly, "is_anomaly", False):
            self._add_section_header("⚠ Unusual activity")
            self._add_dim_line(anomaly.message, margin_bottom=12)
            self._add_separator()

        # --- Cost / API-equivalent value ---
        self._render_cost_section(stats)

        # --- Top projects ---
        self._render_top_projects(stats)

        # --- Tips ---
        tips = getattr(stats, "tips", []) or []
        if tips:
            self._add_section_header("💡 Tips")
            for tip in tips:
                self._add_dim_line(tip, margin_bottom=6)
            self._add_separator()

        # --- Cache savings opportunities ---
        self._render_cache_opportunities(stats)

        # --- Weekly Claude-authored report ---
        self._render_weekly_report(stats)

        # --- Active sessions ---
        self._render_active_sessions(stats)

        # --- Footer ---
        self._render_footer(stats)

    # ------------------------------------------------------------ sections

    def _render_cost_section(self, stats: UsageStats) -> None:
        today_cost = float(getattr(stats, "today_cost", 0.0) or 0.0)
        if today_cost <= 0:
            return

        cache_savings = float(getattr(stats, "cache_savings", 0.0) or 0.0)
        sub = (getattr(stats, "subscription_type", "") or "").lower()
        is_subscriber = sub in ("pro", "max", "team", "enterprise")

        # Short header; detailed framing lives in the dim sub-line below so the
        # popup width doesn't force the title onto two lines.
        if is_subscriber:
            self._add_section_header("Cost (today)", right=f"{sub.capitalize()} plan")
            self._add_dim_line(f"${today_cost:.2f}", role="metric", margin_bottom=4)
            self._add_dim_line(
                "API pay-as-you-go equivalent — included in your plan",
                margin_bottom=4,
            )
        else:
            self._add_section_header("Cost (today)")
            self._add_dim_line(f"${today_cost:.2f}", role="metric", margin_bottom=4)

        if cache_savings > 0:
            self._add_dim_line(f"${cache_savings:.2f} saved by cache", margin_bottom=8)

        by_model = getattr(stats, "today_by_model_detailed", {}) or {}
        if by_model:
            self._render_per_model_breakdown(by_model)

        self._add_separator()

    def _render_per_model_breakdown(self, by_model: dict) -> None:
        total_in = total_out = total_cr = total_cc = 0
        rows = []
        for model, counts in by_model.items():
            in_t = int(counts.get("input", 0) or 0)
            out_t = int(counts.get("output", 0) or 0)
            cr_t = int(counts.get("cache_read", 0) or 0)
            cc_t = int(counts.get("cache_creation", 0) or 0)
            total_in += in_t
            total_out += out_t
            total_cr += cr_t
            total_cc += cc_t
            bk = calculate_cost(model, in_t, out_t, cr_t, cc_t)
            rows.append((_short_model_name(model), model, in_t, out_t, cr_t, cc_t, bk))
        rows.sort(key=lambda r: r[6]["total"], reverse=True)

        self._add_dim_line(
            f"Tokens: {_format_tokens(total_in)} in • "
            f"{_format_tokens(total_out)} out • "
            f"{_format_tokens(total_cr)} cache read • "
            f"{_format_tokens(total_cc)} cache write",
            margin_bottom=6,
        )

        for short, model, in_t, out_t, cr_t, cc_t, bk in rows:
            if bk["total"] < 0.01:
                continue
            rates = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
            self._add_dim_line(f"  {short}: ${bk['total']:.2f} total", margin_bottom=2)
            if in_t > 0:
                self._add_dim_line(
                    f"     input:  {_format_tokens(in_t):>7} × ${rates['input']:.2f}/M = ${bk['input']:.2f}",
                    margin_bottom=2,
                )
            if out_t > 0:
                self._add_dim_line(
                    f"     output: {_format_tokens(out_t):>7} × ${rates['output']:.2f}/M = ${bk['output']:.2f}",
                    margin_bottom=2,
                )
            if cr_t > 0:
                self._add_dim_line(
                    f"     cache read:  {_format_tokens(cr_t):>7} × ${rates['cache_read']:.2f}/M = ${bk['cache_read']:.2f}",
                    margin_bottom=2,
                )
            if cc_t > 0:
                self._add_dim_line(
                    f"     cache write: {_format_tokens(cc_t):>7} × ${rates['cache_creation']:.2f}/M = ${bk['cache_creation']:.2f}",
                    margin_bottom=4,
                )

    def _render_top_projects(self, stats: UsageStats) -> None:
        projects = getattr(stats, "today_by_project", {}) or {}
        if not projects:
            return
        self._add_section_header("Top projects today")
        items = sorted(projects.items(), key=lambda kv: kv[1], reverse=True)
        for name, tokens in items[:5]:
            try:
                tok = int(tokens)
            except (TypeError, ValueError):
                tok = 0
            self._add_dim_line(
                f"{_prettify_project_name(name)}: {_format_tokens(tok)} tokens",
                margin_bottom=4,
            )
        self._add_separator()

    def _render_cache_opportunities(self, stats: UsageStats) -> None:
        opps = getattr(stats, "cache_opportunities", []) or []
        if not opps:
            return
        total = sum(float(o.potential_savings_usd) for o in opps)
        self._add_section_header(
            "💰 Cache opportunities",
            right=f"~${total:.2f}/wk savings" if total > 0 else "",
        )
        for o in opps[:5]:
            name = _prettify_project_name(getattr(o, "project", "") or "?")
            preview = (getattr(o, "prefix_preview", "") or "").strip()
            if len(preview) > 70:
                preview = preview[:67] + "…"
            self._add_dim_line(
                f"{name}: {getattr(o, 'occurrences', 0)}× × "
                f"{_format_tokens(getattr(o, 'token_count', 0))} tokens → "
                f"${float(getattr(o, 'potential_savings_usd', 0.0)):.2f}",
                margin_bottom=2,
            )
            if preview:
                self._add_dim_line(f"    “{preview}”", margin_bottom=6)
        self._add_separator()

    def _render_weekly_report(self, stats: UsageStats) -> None:
        text = (getattr(stats, "weekly_report_text", "") or "").strip()
        if not text:
            return
        self._add_section_header("🪄 Your week with Claude")
        self._add_dim_line(text, margin_bottom=12)
        self._add_separator()

    def _render_active_sessions(self, stats: UsageStats) -> None:
        self._add_section_header(
            "Active sessions",
            f"{len(stats.active_sessions)} running",
        )
        if stats.active_sessions:
            for sess in stats.active_sessions:
                started = datetime.fromtimestamp(sess.get("startedAt", 0) / 1000)
                duration = datetime.now() - started
                cwd = sess.get("cwd", "?").replace(os.path.expanduser("~"), "~")
                dur = _format_session_duration(int(duration.total_seconds()))
                self._add_dim_line(f"{cwd}    {dur}", role="link", margin_bottom=4)
        else:
            self._add_dim_line("No active sessions", margin_bottom=4)

    def _render_footer(self, stats: UsageStats) -> None:
        self._add_separator()
        self._add_dim_line("Last updated: just now", margin_bottom=0)
        if stats.rate_limit_error:
            self._add_dim_line(f"API: {stats.rate_limit_error}", role="error", margin_bottom=0)


# ---------------------------------------------------------------------------
# Application orchestrator
# ---------------------------------------------------------------------------

class ClaudeUsageApp(QObject):
    """Wires OSD, popup, timer, refresh thread, webhooks, and notifier."""

    # Emitted on the GUI thread once background collection completes.
    stats_ready = Signal(object)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self.config = config
        self.stats = UsageStats()
        self._alive = True
        self._refreshing = False
        self._last_daily_report_date: str = ""

        # UI components
        self.overlay = UsageOverlay(config)
        self.popup = UsagePopup(config)

        # Context menu shown on right-click of the OSD.
        self._context_menu = QMenu()
        self._build_context_menu()

        # Webhook dispatcher + notifier
        from claude_usage.webhooks import WebhookDispatcher
        self._webhooks = WebhookDispatcher(config.get("webhooks", {}))
        self.notifier = UsageNotifier(
            config,
            on_threshold=lambda scope, t: self._webhooks.fire(
                "threshold_crossed", {"scope": scope, "threshold": t},
            ),
        )

        # Optional: localhost JSON API server
        self._api_server = None
        if config.get("api_server_enabled"):
            from claude_usage.api_server import UsageAPIServer
            self._api_server = UsageAPIServer(
                host=config.get("api_server_host", "127.0.0.1"),
                port=int(config.get("api_server_port", 8765)),
                get_stats=lambda: self.stats,
            )
            self._api_server.start()

        # --- Wire signals ---
        self.overlay.clicked.connect(self._on_overlay_click)
        self.overlay.rightClicked.connect(self._on_overlay_right_click)
        self.stats_ready.connect(self._apply_stats)

        # Show the overlay and kick off the first refresh.
        self.overlay.show()
        self._refresh_async()

        # Periodic refresh timer (runs on the GUI thread).
        refresh_secs = int(config.get("refresh_seconds", 30))
        self._timer = QTimer()
        self._timer.setInterval(refresh_secs * 1000)
        self._timer.timeout.connect(self._refresh_async)
        self._timer.start()

        # One-shot GitHub release check.
        self._latest_tag: str | None = None
        threading.Thread(target=self._check_update, daemon=True).start()

        # Tracks whether a weekly-report generation is already in flight, so
        # the hourly check doesn't spawn multiple Haiku calls in parallel.
        self._weekly_report_in_flight = False

    # ----------------------------------------------------------- menu build

    def _build_context_menu(self) -> None:
        m = self._context_menu

        act_details = QAction("Details…", m)
        act_details.triggered.connect(self._show_popup)
        m.addAction(act_details)

        act_refresh = QAction("Refresh", m)
        act_refresh.triggered.connect(self._refresh_async)
        m.addAction(act_refresh)

        m.addSeparator()

        opacity_menu = m.addMenu("OSD Opacity")
        for pct in (100, 75, 50, 25):
            a = QAction(f"{pct}%", opacity_menu)
            a.triggered.connect(lambda _checked=False, v=pct / 100.0: self.overlay.set_opacity(v))
            opacity_menu.addAction(a)

        # View mode submenu — bars vs gauges, radio-grouped.
        from PySide6.QtGui import QActionGroup as _QActionGroup
        from claude_usage.overlay import VIEW_MODES
        view_menu = m.addMenu("OSD View")
        self._view_group = _QActionGroup(view_menu)
        self._view_group.setExclusive(True)
        self._view_actions: dict[str, QAction] = {}
        for mode in VIEW_MODES:
            a = QAction(mode.capitalize(), view_menu)
            a.setCheckable(True)
            a.setActionGroup(self._view_group)
            a.triggered.connect(lambda _checked=False, md=mode: self._on_pick_view_mode(md))
            view_menu.addAction(a)
            self._view_actions[mode] = a

        # Theme submenu — radio group so only one is ticked at a time. The
        # selection auto-persists to the user config so a restart keeps it.
        from PySide6.QtGui import QActionGroup
        from claude_usage.themes import THEMES
        theme_menu = m.addMenu("Theme")
        self._theme_group = QActionGroup(theme_menu)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for name in sorted(THEMES.keys()):
            a = QAction(name, theme_menu)
            a.setCheckable(True)
            a.setActionGroup(self._theme_group)
            a.triggered.connect(lambda _checked=False, n=name: self._on_pick_theme(n))
            theme_menu.addAction(a)
            self._theme_actions[name] = a

        act_minimize = QAction("Minimize / Restore", m)
        act_minimize.triggered.connect(self.overlay.toggle_minimized)
        m.addAction(act_minimize)

        self._act_ticker = QAction("Show cost ticker", m)
        self._act_ticker.setCheckable(True)
        self._act_ticker.setChecked(self.overlay.is_ticker_enabled())
        self._act_ticker.toggled.connect(self._on_toggle_ticker)
        m.addAction(self._act_ticker)
        m.aboutToShow.connect(self._sync_menu_state)

        m.addSeparator()

        act_quit = QAction("Quit", m)
        act_quit.triggered.connect(self._on_quit)
        m.addAction(act_quit)

    def _on_toggle_ticker(self, checked: bool) -> None:
        self.overlay.set_ticker_enabled(checked)
        self.config["show_ticker"] = bool(checked)
        self._persist_config()

    def _on_pick_theme(self, name: str) -> None:
        self.overlay.set_theme(name)
        self.popup.apply_config({**self.config, "theme": name})
        self.config["theme"] = name
        self._persist_config()

    def _on_pick_view_mode(self, mode: str) -> None:
        self.overlay.set_view_mode(mode)
        self.config["osd_view_mode"] = mode
        self._persist_config()

    def _sync_menu_state(self) -> None:
        """Refresh the tick marks on checkable items when the menu opens."""
        self._act_ticker.setChecked(self.overlay.is_ticker_enabled())
        current_theme = str(self.config.get("theme", "default"))
        theme_act = self._theme_actions.get(current_theme)
        if theme_act is not None:
            theme_act.setChecked(True)
        current_view = self.overlay.view_mode()
        view_act = self._view_actions.get(current_view)
        if view_act is not None:
            view_act.setChecked(True)

    def _persist_config(self) -> None:
        """Write the in-memory config to the user's XDG config file.

        Best-effort: if the filesystem is read-only (sandboxed installs,
        full disk) we swallow the error rather than crashing the GUI.
        The change still applies for the remainder of the session.
        """
        from claude_usage.config import save_config, user_config_path
        try:
            save_config(user_config_path(), self.config)
        except OSError:
            pass

    # ------------------------------------------------------------- refresh

    def _refresh_async(self) -> None:
        if self._refreshing or not self._alive:
            return
        self._refreshing = True

        def _worker() -> None:
            try:
                stats = collect_all(self.config)
            except Exception:
                stats = UsageStats(rate_limit_error="Collection failed")
            # Emit cross-thread signal; the slot runs on the GUI thread.
            if self._alive:
                self.stats_ready.emit(stats)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(object)
    def _apply_stats(self, stats: UsageStats) -> None:
        self._refreshing = False
        if not self._alive:
            return
        self.stats = stats

        self.overlay.update_stats(stats)
        self.popup.update_stats(stats)
        self.notifier.check_stats(stats)

        # Webhook: anomaly
        if getattr(stats.anomaly, "is_anomaly", False):
            self._webhooks.fire("anomaly", {
                "ratio": stats.anomaly.ratio,
                "z_score": stats.anomaly.z_score,
                "message": stats.anomaly.message,
            })

        # Weekly report: kick off a background regeneration if the on-disk
        # cache is stale and we're not already generating. Pass a snapshot
        # of the stats so the worker never observes a torn mid-refresh mix
        # of fields.
        if not stats.weekly_report_text and not self._weekly_report_in_flight:
            self._weekly_report_in_flight = True
            threading.Thread(
                target=self._generate_weekly_report,
                args=(stats,),
                daemon=True,
            ).start()

        # Webhook: daily report (first refresh of each local day)
        today_iso = datetime.now().strftime("%Y-%m-%d")
        if today_iso != self._last_daily_report_date:
            self._last_daily_report_date = today_iso
            self._webhooks.fire("daily_report", {
                "date": today_iso,
                "session_utilization": stats.session_utilization,
                "weekly_utilization": stats.weekly_utilization,
                "today_cost": stats.today_cost,
                "today_tokens": stats.today_tokens,
            })

    # -------------------------------------------------------------- slots

    def _on_overlay_click(self) -> None:
        self._show_popup()

    def _on_overlay_right_click(self, global_pos: QPoint) -> None:
        self._context_menu.popup(global_pos)

    def _show_popup(self) -> None:
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()

    def _generate_weekly_report(self, snapshot: UsageStats) -> None:
        try:
            from claude_usage.ai_report import generate_report
            from claude_usage.collector import _load_credentials
            claude_dir = self.config["claude_dir"]
            summary = {
                "week_cost": snapshot.week_cost,
                "week_tokens": snapshot.week_tokens,
                "week_messages": snapshot.week_messages,
                "subscription_type": snapshot.subscription_type,
                "top_projects": sorted(
                    snapshot.today_by_project.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:3],
                "by_model": snapshot.today_by_model_detailed,
            }
            generate_report(
                claude_dir=claude_dir,
                summary=summary,
                token_loader=lambda: _load_credentials(claude_dir),
            )
        except Exception:
            pass
        finally:
            self._weekly_report_in_flight = False

    def _check_update(self) -> None:
        try:
            from claude_usage import __version__ as v
            from claude_usage.updater import check_latest_version
            tag, available = check_latest_version(v)
            if available and tag:
                self._latest_tag = tag
                # Show a one-time system notification.
                self.notifier._send(
                    f"Claude Usage {tag} available",
                    "Update with: pip install --upgrade claude-usage-widget",
                )
        except Exception:
            pass

    def _on_quit(self) -> None:
        self._alive = False
        self._timer.stop()
        if self._api_server is not None:
            try:
                self._api_server.stop()
            except Exception:
                pass
        QApplication.instance().quit()
