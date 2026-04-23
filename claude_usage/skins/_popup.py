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
