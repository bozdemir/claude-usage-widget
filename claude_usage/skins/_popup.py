"""Shared popup-specific painters used by all 6 directions.

A "popup" in PyQt6 is a `QWidget` (frameless, Qt.Popup window flag) that
paints its whole surface inside `paintEvent`. All 6 directions share the
same data flow:

    class PopupWidget(QWidget):
        def paintEvent(self, ev):
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
            direction.paint_popup(p, self.rect(), self._data, self._scale)

Each direction implements its own `paint_popup`, but they all pull from
the same toolbox here: section headers, KPI blocks, sparkline rows,
90-day heatmap, 52-week heatmap, project/tip/report cards.

IMPORTANT SIZING CONVENTION
- All metrics in this module are at `scale=1.0`. Multiply positions and
  sizes by `scale` at call time.
- Y advances top-to-bottom; every helper RETURNS the new y cursor so the
  caller can chain sections without recomputing offsets.
- Widgets that need to be taller than the popup resize themselves via
  `QWidget.setMinimumHeight` — the direction's `measure_popup(data)`
  function returns the total height so the widget can be sized before
  `paintEvent` runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from ._paint import (
    draw_ascii_bar, draw_block_bar, draw_heatmap_52w, draw_ring,
    draw_sparkline_bars, draw_text, hex_to_qcolor, mono_font, ui_font,
)


# ---- layout constants ---------------------------------------------

POPUP_WIDTH = 540        # all directions share this width
POPUP_PADDING = 20
SECTION_GAP = 18
ROW_GAP = 6

# Each direction fills in its own color map; these keys are the contract.
# NOTE: order these to match the default-theme keys so existing color
# choosers in widget.py don't need branching.
REQUIRED_KEYS = (
    "bg", "panel", "border", "bar_blue", "bar_track", "text_primary",
    "text_secondary", "text_dim", "separator", "warn", "crit",
    "live_indicator", "accent",
)


# ---- measurement --------------------------------------------------

def dry_measure(paint_fn: Callable, data, scale: float = 1.0,
                width: int = POPUP_WIDTH) -> int:
    """Paint the popup into a throwaway 1×1 QImage and read back the final
    y cursor the painter returned.

    Skins track their own y cursor through every section; once paint_popup
    returns that cursor, we have the exact content height — no guessing.
    The paint operations go out of bounds on the 1×1 surface, but Qt
    silently clips; what we care about is the returned y value."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    img = QImage(1, 1, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    try:
        y = paint_fn(p, QRectF(0, 0, width, 99999), data, scale)
    finally:
        p.end()
    # Fall back for paint functions that haven't been taught to return y.
    if not isinstance(y, (int, float)):
        return int(1180 * scale)
    return int(y)


# ---- loading state ------------------------------------------------

def paint_loading(
    p: QPainter, rect: QRectF, theme: dict, scale: float = 1.0,
    *, style: str = "default", phase: float = 0.0,
) -> None:
    """Draws a "waiting for data" state in the popup's centre. ``phase`` is
    a 0..1 value driven by a timer outside so the indicator can animate
    (dots cycling, arc sweeping, etc.).

    Styles:
        "terminal"  — ASCII box with cycling ``.``/``..``/``...``
        "receipt"   — dashed rule + centered "PRINTING..."
        "hud"       — 270° arc that rotates
        "brutalist" — thick 2px block + "WAIT" stamp
        "default"   — centered "Loading…" with a 3-dot pulse
    """
    s = scale; t = theme
    # panel bg + border — match the resting popup chrome so the transition
    # to the real content is seamless (no flash).
    bg = hex_to_qcolor(t.get("paper", t["bg"]))
    p.setPen(Qt.NoPen); p.setBrush(bg)
    radius = 0 if style == "brutalist" else 8 * s
    p.drawRoundedRect(rect, radius, radius)
    border_w = 2 * s if style == "brutalist" else 1
    p.setPen(QPen(hex_to_qcolor(t["border"]), border_w))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(border_w / 2, border_w / 2,
                                    -border_w / 2, -border_w / 2),
                      radius, radius)

    cx = rect.x() + rect.width() / 2
    cy = rect.y() + rect.height() / 2

    # dot animation — 0..3 dots based on phase
    dots = ("", ".", "..", "...")[int(phase * 4) % 4]

    if style == "terminal":
        banner_f = mono_font(13 * s, bold=True,
                             family=t.get("_mono_family", "JetBrains Mono"))
        body_f = mono_font(11 * s, family=t.get("_mono_family", "JetBrains Mono"))
        fm_b = QFontMetrics(banner_f); fm = QFontMetrics(body_f)
        line1 = "╔═ LOADING " + "═" * 8 + "╗"
        line2 = f"  collecting{dots}".ljust(len(line1) - 2)
        line3 = "╚" + "═" * (len(line1) - 2) + "╝"
        w1 = fm_b.horizontalAdvance(line1)
        y0 = cy - fm_b.height()
        draw_text(p, cx - w1 / 2, y0 + fm_b.ascent(),
                  line1, hex_to_qcolor(t["accent"]), banner_f,
                  letter_spacing_px=1.0 * s)
        draw_text(p, cx - w1 / 2 + fm_b.horizontalAdvance("║") * 1.0,
                  y0 + fm_b.height() + fm.ascent(),
                  line2, hex_to_qcolor(t["text_primary"]), body_f)
        draw_text(p, cx - w1 / 2,
                  y0 + fm_b.height() + fm.height() + fm_b.ascent(),
                  line3, hex_to_qcolor(t["accent"]), banner_f,
                  letter_spacing_px=1.0 * s)
        return

    if style == "receipt":
        banner_f = mono_font(12 * s, bold=True,
                             family=t.get("_mono_family", "JetBrains Mono"))
        fm_b = QFontMetrics(banner_f)
        txt = f"- - -  PRINTING{dots.ljust(3)}  - - -"
        tw = fm_b.horizontalAdvance(txt)
        # dashed rule above & below
        pen = QPen(hex_to_qcolor(t.get("rule", t["border"])))
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.drawLine(QPointF(cx - tw / 2 - 20 * s, cy - 24 * s),
                   QPointF(cx + tw / 2 + 20 * s, cy - 24 * s))
        draw_text(p, cx - tw / 2, cy + fm_b.ascent() / 2,
                  txt, hex_to_qcolor(t["text_primary"]), banner_f,
                  letter_spacing_px=2 * s)
        p.setPen(pen)
        p.drawLine(QPointF(cx - tw / 2 - 20 * s, cy + 24 * s),
                   QPointF(cx + tw / 2 + 20 * s, cy + 24 * s))
        return

    if style == "hud":
        # rotating 270° arc
        r = 34 * s; stroke = 6 * s
        arc_rect = QRectF(cx - r, cy - r - 12 * s, r * 2, r * 2)
        pen = QPen(hex_to_qcolor(t["bar_track"])); pen.setWidthF(stroke)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawArc(arc_rect, 0, 360 * 16)
        pen = QPen(hex_to_qcolor(t["accent"])); pen.setWidthF(stroke)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        start_deg = int(-phase * 360 * 16)
        p.drawArc(arc_rect, start_deg, -90 * 16)
        # label below
        label_f = mono_font(10 * s, bold=True,
                            family=t.get("_mono_family", "JetBrains Mono"))
        fm = QFontMetrics(label_f)
        txt = "INITIALIZING" + dots
        tw = fm.horizontalAdvance(txt)
        draw_text(p, cx - tw / 2, cy + r + 24 * s,
                  txt, hex_to_qcolor(t["text_dim"]), label_f,
                  letter_spacing_px=3 * s)
        return

    if style == "brutalist":
        # big solid block + stamp
        big_f = mono_font(28 * s, bold=True,
                          family=t.get("_mono_family", "Space Mono"))
        fm_b = QFontMetrics(big_f)
        txt = f"§ WAIT{dots}"
        tw = fm_b.horizontalAdvance(txt)
        block = QRectF(cx - tw / 2 - 18 * s, cy - fm_b.height() / 2 - 6 * s,
                       tw + 36 * s, fm_b.height() + 12 * s)
        p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["text_primary"]))
        p.drawRect(block)
        draw_text(p, cx - tw / 2, cy + fm_b.ascent() / 2 - 4 * s,
                  txt, hex_to_qcolor(t["paper"]), big_f,
                  letter_spacing_px=3 * s)
        return

    # default — centred "Loading..." with a pulsing 3-dot bar
    label_f = ui_font(13 * s, family=t.get("_ui_family", "Inter"))
    fm = QFontMetrics(label_f)
    txt = "Loading"
    tw = fm.horizontalAdvance(txt)
    draw_text(p, cx - tw / 2, cy - 6 * s,
              txt, hex_to_qcolor(t["text_primary"]), label_f,
              letter_spacing_px=1.5 * s)
    # 3 dots, the "active" one (based on phase) is accent
    dot_r = 3 * s
    active = int(phase * 3) % 3
    for i in range(3):
        col = hex_to_qcolor(t["accent"]) if i == active else hex_to_qcolor(t["text_dim"])
        p.setPen(Qt.NoPen); p.setBrush(col)
        p.drawEllipse(QPointF(cx - 12 * s + i * 12 * s, cy + 14 * s),
                      dot_r, dot_r)


# ---- reusable blocks ----------------------------------------------

def draw_section_header(
    p: QPainter,
    x: float, y: float, w: float,
    number: int, title: str,
    theme: dict,
    scale: float = 1.0,
    style: str = "default",
) -> float:
    """Section header. Style switches the visual treatment:
        "default"   — "01 · TITLE" with an accent number and a hairline rule
        "terminal"  — "[01] TITLE ─ ─ ─ ─" dashed trailer
        "brutalist" — big 2px top rule + section number + title, all caps
        "receipt"   — "- - - TITLE - - -" centered dashed
    Returns new y cursor."""
    s = scale
    title_f = ui_font(11 * s, family=theme.get("_ui_family", "Inter"))
    num_f = mono_font(10 * s, bold=True, family=theme.get("_mono_family", "JetBrains Mono"))
    fm = QFontMetrics(title_f)

    if style == "terminal":
        num = f"[{number:02d}]"
        nf = mono_font(10 * s, family=theme["_mono_family"])
        adv = draw_text(p, x, y + fm.ascent(), num,
                        hex_to_qcolor(theme["text_dim"]), nf)
        adv += draw_text(p, x + adv + 8 * s, y + fm.ascent(), title,
                         hex_to_qcolor(theme["accent"]), num_f,
                         letter_spacing_px=1.5 * s)
        # dashed trailing line
        pen = QPen(hex_to_qcolor(theme["border"])); pen.setDashPattern([2, 2])
        p.setPen(pen)
        p.drawLine(QPointF(x + adv + 16 * s, y + fm.ascent() - 2 * s),
                   QPointF(x + w, y + fm.ascent() - 2 * s))
        return y + fm.height() + 6 * s

    if style == "brutalist":
        pen = QPen(hex_to_qcolor(theme["text_primary"])); pen.setWidthF(2 * s)
        p.setPen(pen)
        p.drawLine(QPointF(x, y), QPointF(x + w, y))
        y2 = y + 8 * s
        nf = mono_font(10 * s, bold=True, family=theme["_mono_family"])
        adv = draw_text(p, x, y2 + fm.ascent(), f"§{number:02d}",
                        hex_to_qcolor(theme["accent"]), nf,
                        letter_spacing_px=1.5 * s)
        draw_text(p, x + adv + 10 * s, y2 + fm.ascent(), title.upper(),
                  hex_to_qcolor(theme["text_primary"]), num_f,
                  letter_spacing_px=3 * s)
        return y2 + fm.height() + 6 * s

    if style == "receipt":
        fm_t = QFontMetrics(num_f)
        txt = f"- - -  {title.upper()}  - - -"
        tw = fm_t.horizontalAdvance(txt)
        draw_text(p, x + (w - tw) / 2, y + fm_t.ascent(), txt,
                  hex_to_qcolor(theme["text_dim"]), num_f,
                  letter_spacing_px=2 * s)
        return y + fm_t.height() + 4 * s

    # default — accent number + title + thin rule under
    adv = draw_text(p, x, y + fm.ascent(), f"{number:02d}",
                    hex_to_qcolor(theme["accent"]), num_f,
                    letter_spacing_px=1.5 * s)
    draw_text(p, x + adv + 10 * s, y + fm.ascent(), title.upper(),
              hex_to_qcolor(theme["text_secondary"]), num_f,
              letter_spacing_px=2 * s)
    p.setPen(hex_to_qcolor(theme["border"]))
    p.drawLine(QPointF(x, y + fm.height() + 3 * s),
               QPointF(x + w, y + fm.height() + 3 * s))
    return y + fm.height() + 8 * s


def draw_kpi_big(
    p: QPainter, x: float, y: float,
    label: str, value: str, sub: str,
    theme: dict, scale: float = 1.0,
) -> float:
    s = scale
    label_f = ui_font(9 * s, family=theme["_ui_family"])
    value_f = mono_font(28 * s, bold=True, family=theme["_mono_family"])
    sub_f = ui_font(10 * s, family=theme["_ui_family"])
    fm_l = QFontMetrics(label_f); fm_v = QFontMetrics(value_f); fm_s_ = QFontMetrics(sub_f)
    draw_text(p, x, y + fm_l.ascent(), label.upper(),
              hex_to_qcolor(theme["text_dim"]), label_f,
              letter_spacing_px=2 * s)
    draw_text(p, x, y + fm_l.height() + fm_v.ascent(), value,
              hex_to_qcolor(theme["text_primary"]), value_f)
    if sub:
        draw_text(p, x, y + fm_l.height() + fm_v.height() + fm_s_.ascent(),
                  sub, hex_to_qcolor(theme["text_secondary"]), sub_f)
        return y + fm_l.height() + fm_v.height() + fm_s_.height()
    return y + fm_l.height() + fm_v.height()


def draw_pct_row(
    p: QPainter, x: float, y: float, w: float,
    label: str, pct: float, reset: str,
    theme: dict, scale: float = 1.0,
    bar_style: str = "block",   # "block" | "ascii" | "rect_border"
    fill_hex: str | None = None,
    ascii_cols: int = 46,
) -> float:
    """Full-width row: label + pct + reset on one line, bar below.
    Returns new y cursor."""
    s = scale
    fill_hex = fill_hex or theme["accent"]
    label_f = ui_font(10 * s, family=theme["_ui_family"])
    pct_f = mono_font(12 * s, bold=True, family=theme["_mono_family"])
    sub_f = mono_font(10 * s, family=theme["_mono_family"])
    fm = QFontMetrics(label_f); fm_p = QFontMetrics(pct_f); fm_s_ = QFontMetrics(sub_f)
    bl = y + fm_p.ascent()
    draw_text(p, x, bl, label, hex_to_qcolor(theme["text_primary"]),
              label_f, letter_spacing_px=0.8 * s)

    pct_txt = f"{int(pct * 100)}%"
    reset_w = fm_s_.horizontalAdvance(reset)
    pct_w = fm_p.horizontalAdvance(pct_txt)
    draw_text(p, x + w - reset_w, bl, reset,
              hex_to_qcolor(theme["text_dim"]), sub_f)
    draw_text(p, x + w - reset_w - pct_w - 10 * s, bl, pct_txt,
              hex_to_qcolor(theme["text_primary"]), pct_f)

    bar_y = bl + 6 * s
    bar_h = 6 * s
    if bar_style == "ascii":
        font = mono_font(10 * s, family=theme["_mono_family"])
        draw_ascii_bar(p, x, bar_y + QFontMetrics(font).ascent(),
                       pct, ascii_cols,
                       hex_to_qcolor(fill_hex),
                       hex_to_qcolor(theme["bar_track"]), font)
        return bar_y + QFontMetrics(font).height() + 4 * s
    if bar_style == "rect_border":
        p.setPen(QPen(hex_to_qcolor(theme["text_primary"]), 1))
        p.setBrush(hex_to_qcolor(theme["bar_track"]))
        p.drawRect(QRectF(x, bar_y, w, bar_h))
        p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(fill_hex))
        p.drawRect(QRectF(x + 1, bar_y + 1, (w - 2) * pct, bar_h - 2))
        return bar_y + bar_h + 4 * s
    # default block
    draw_block_bar(p, x, bar_y, w, bar_h, pct,
                   hex_to_qcolor(theme["bar_track"]),
                   hex_to_qcolor(fill_hex), radius=bar_h / 2)
    return bar_y + bar_h + 4 * s


def draw_sparkline_row(
    p: QPainter, x: float, y: float, w: float, h: float,
    values: list[float], label: str,
    theme: dict, scale: float = 1.0,
    color_hex: str | None = None,
) -> float:
    s = scale
    color_hex = color_hex or theme["accent"]
    draw_sparkline_bars(p, x, y, w, h, values, color_hex, gap=1.0 * s)
    label_f = ui_font(9 * s, family=theme["_ui_family"])
    fm = QFontMetrics(label_f)
    draw_text(p, x, y + h + fm.ascent() + 2 * s, label.upper(),
              hex_to_qcolor(theme["text_dim"]), label_f,
              letter_spacing_px=1.5 * s)
    return y + h + fm.height() + 2 * s


def draw_project_list(
    p: QPainter, x: float, y: float, w: float,
    projects: list,    # each has .name and .tokens
    theme: dict, scale: float = 1.0,
    numbered: bool = True,
) -> float:
    s = scale
    f = mono_font(11 * s, family=theme["_mono_family"])
    fm = QFontMetrics(f)
    row_h = fm.height() + 6 * s
    for i, proj in enumerate(projects):
        bl = y + fm.ascent() + 3 * s
        left = f"{i + 1:02d}  {proj.name}" if numbered else proj.name
        right = proj.tokens
        rw = fm.horizontalAdvance(right)
        draw_text(p, x, bl, left,
                  hex_to_qcolor(theme["text_primary"]), f)
        draw_text(p, x + w - rw, bl, right,
                  hex_to_qcolor(theme["text_dim"]), f)
        # hairline between rows
        if i < len(projects) - 1:
            p.setPen(hex_to_qcolor(theme["border"]))
            p.drawLine(QPointF(x, y + row_h - 1),
                       QPointF(x + w, y + row_h - 1))
        y += row_h
    return y


def draw_active_sessions(
    p: QPainter, x: float, y: float, w: float,
    sessions: list,    # each has .cwd and .duration
    theme: dict, scale: float = 1.0,
) -> float:
    """Per-row list of running Claude Code sessions: cwd left, duration right,
    hairline between rows. Falls back to a dim "no active sessions" line when
    the list is empty so the section still has visual weight."""
    s = scale
    f = mono_font(11 * s, family=theme["_mono_family"])
    fm = QFontMetrics(f)
    row_h = fm.height() + 6 * s
    if not sessions:
        draw_text(p, x, y + fm.ascent() + 3 * s, "no active sessions",
                  hex_to_qcolor(theme["text_dim"]), f)
        return y + row_h
    for i, sess in enumerate(sessions):
        bl = y + fm.ascent() + 3 * s
        cwd = getattr(sess, "cwd", "?") or "?"
        dur = getattr(sess, "duration", "") or ""
        # elide long cwds so right-aligned duration never gets pushed off
        dw = fm.horizontalAdvance(dur)
        cwd_max = w - dw - 16 * s
        elided_cwd = fm.elidedText(cwd, Qt.ElideMiddle, int(cwd_max))
        draw_text(p, x, bl, elided_cwd,
                  hex_to_qcolor(theme["text_primary"]), f)
        draw_text(p, x + w - dw, bl, dur,
                  hex_to_qcolor(theme["text_dim"]), f)
        if i < len(sessions) - 1:
            p.setPen(hex_to_qcolor(theme["border"]))
            p.drawLine(QPointF(x, y + row_h - 1),
                       QPointF(x + w, y + row_h - 1))
        y += row_h
    return y


def draw_report_card(
    p: QPainter, x: float, y: float, w: float,
    body: str,
    theme: dict, scale: float = 1.0,
    style: str = "quote",   # "quote" | "plain"
) -> float:
    """Wrap-and-draw a body of text. Uses QTextOption word wrap via
    drawText(rect, flags)."""
    s = scale
    f = ui_font(11 * s, family=theme["_ui_family"])
    fm = QFontMetrics(f)
    pad = 10 * s
    inner_w = w - (pad * 2 if style == "plain" else 16 * s)
    # estimate height from bounding rect
    # Qt's QFontMetrics.boundingRect(rect,...) wants a QRect (not QRectF).
    from PySide6.QtCore import QRect
    br = fm.boundingRect(QRect(0, 0, int(inner_w), 10000), int(Qt.TextWordWrap), body)
    h = br.height() + pad * 2

    if style == "quote":
        # left accent rule + text
        pen = QPen(hex_to_qcolor(theme["accent"])); pen.setWidthF(2 * s)
        p.setPen(pen)
        p.drawLine(QPointF(x, y), QPointF(x, y + h))
        p.setPen(hex_to_qcolor(theme["text_primary"]))
        p.setFont(f)
        p.drawText(QRectF(x + 12 * s, y + pad, inner_w, h - pad * 2),
                   Qt.TextWordWrap, body)
    else:
        # plain card with faint panel bg
        p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(theme["panel"]))
        p.drawRoundedRect(QRectF(x, y, w, h), 4 * s, 4 * s)
        p.setPen(hex_to_qcolor(theme["text_primary"]))
        p.setFont(f)
        p.drawText(QRectF(x + pad, y + pad, inner_w, h - pad * 2),
                   Qt.TextWordWrap, body)
    return y + h
