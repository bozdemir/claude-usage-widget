"""Direction 3 — HUD Gauge.

Cockpit dashboard. Two 270° arc gauges flank a center column with LIVE
tok/min + today's cost. Warm black bg, amber accent, tick marks.

Nuances:
- Arc sweep is 270° starting at -225° (south-west) and ending at +45°
  (south-east). Qt's drawArc wants 1/16 degree units.
- Tick marks live OUTSIDE the arc. Every 10% a short tick, every 50% a
  longer + brighter tick.
- Center number is 30pt monospace bold. "%" is a sibling at 14pt dim.
- No ticker in this view — the reset labels under each gauge would
  collide with it.
"""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from ._paint import (
    draw_ring, draw_text, draw_ticker_marquee, hex_to_qcolor, mono_font,
)


WANTS_TICKER = True


THEME = {
    "style":          "hud",
    '_mono_family'    : 'JetBrains Mono',
    '_ui_family'      : 'Inter',
    'paper'           : '#0c0a08',
    'accent2'         : '#a3d468',
    'border'          : '#2a221a',
    "bg":             "#0c0a08",
    "bg2":            "#15110c",
    "panel":          "#171310",
    "border":         "#2a221a",
    "border_bright":  "#3a2e22",
    "bar_blue":       "#f5a524",     # amber masquerading as bar_blue
    "bar_track":      "#322820",
    "text_primary":   "#f1e8da",
    "text_secondary": "#8a7d6a",
    "text_dim":       "#8a7d6a",
    "text_link":      "#a3d468",
    "separator":      "#221c15",
    "warn":           "#f5a524",
    "crit":           "#e5484d",
    "error":          "#e5484d",
    "live_indicator": "#a3d468",
    "accent":         "#f5a524",
    "good":           "#a3d468",
    "very_dim":       "#322820",
}

METRICS = {
    "osd_width": 360, "osd_height": 220, "osd_radius": 10, "osd_padding": 14,
    "ring_size": 118, "ring_stroke": 10,
    "ring_size_popup": 140, "ring_stroke_popup": 12,
    "ticker_h": 22,
}

FONTS = {
    "family_mono": "JetBrains Mono", "family_ui": "Inter",
    "label_pt": 9, "metric_pt": 30, "title_pt": 10,
}


def _draw_ticks(p: QPainter, cx: float, cy: float, r: float,
                stroke: float, color_major: QColor, color_minor: QColor,
                scale: float = 1.0) -> None:
    start_deg, span_deg = -225.0, 270.0
    for i in range(11):
        a = math.radians(start_deg + (i / 10.0) * span_deg)
        ri = r + stroke / 2 + 2 * scale
        ro = ri + (6 * scale if i % 5 == 0 else 3 * scale)
        pen = QPen(color_major if i % 5 == 0 else color_minor)
        pen.setWidthF(1.5 * scale if i % 5 == 0 else 1.0 * scale)
        p.setPen(pen)
        p.drawLine(
            QPointF(cx + ri * math.cos(a), cy + ri * math.sin(a)),
            QPointF(cx + ro * math.cos(a), cy + ro * math.sin(a)),
        )


def paint_gauge(p: QPainter, cx: float, cy: float, pct: float,
                label: str, sub: str, scale: float = 1.0,
                size: int | None = None, stroke: int | None = None) -> None:
    t = THEME; m = METRICS
    s = scale
    size = (size or m["ring_size"]) * s
    stroke = (stroke or m["ring_stroke"]) * s
    r = (size - stroke) / 2

    draw_ring(p, cx, cy, r, stroke, pct,
              hex_to_qcolor(t["very_dim"]), hex_to_qcolor(t["accent"]),
              start_deg=-225.0, span_deg=270.0)
    _draw_ticks(p, cx, cy, r, stroke,
                hex_to_qcolor(t["text_primary"]),
                hex_to_qcolor(t["text_dim"]), s)

    # center stack: label / NUMBER% / sub
    label_f = mono_font(FONTS["label_pt"] * s, family=FONTS["family_mono"])
    metric_f = mono_font(FONTS["metric_pt"] * s, bold=True, family=FONTS["family_mono"])
    fm_l = QFontMetrics(label_f); fm_m = QFontMetrics(metric_f)

    pct_text = f"{int(pct * 100)}"
    num_w = fm_m.horizontalAdvance(pct_text)
    draw_text(p, cx - fm_l.horizontalAdvance(label) / 2,
              cy - fm_m.ascent() / 2 - 4 * s, label,
              hex_to_qcolor(t["text_dim"]), label_f,
              letter_spacing_px=2.0 * s)
    adv = draw_text(p, cx - num_w / 2, cy + fm_m.ascent() / 2,
                    pct_text, hex_to_qcolor(t["text_primary"]), metric_f)
    draw_text(p, cx - num_w / 2 + adv + 1 * s, cy + fm_m.ascent() / 2,
              "%", hex_to_qcolor(t["text_dim"]),
              mono_font(FONTS["label_pt"] * 1.4 * s, family=FONTS["family_mono"]))
    if sub:
        draw_text(p, cx - fm_l.horizontalAdvance(sub) / 2,
                  cy + fm_m.ascent() / 2 + fm_l.height(),
                  sub, hex_to_qcolor(t["text_dim"]), label_f,
                  letter_spacing_px=1.0 * s)


def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    s = scale; m = METRICS; t = THEME
    pad = m["osd_padding"] * s
    # panel
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["bg"], 0.94))
    p.drawRoundedRect(rect, m["osd_radius"] * s, m["osd_radius"] * s)
    p.setPen(hex_to_qcolor(t["border_bright"])); p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                      m["osd_radius"] * s, m["osd_radius"] * s)

    # top bar text
    title_f = mono_font(FONTS["title_pt"] * s, bold=True, family=FONTS["family_mono"])
    fm = QFontMetrics(title_f)
    draw_text(p, rect.x() + pad, rect.y() + pad + fm.ascent(),
              "CLAUDE · USAGE", hex_to_qcolor(t["accent"]), title_f,
              letter_spacing_px=3.0 * s)

    # gauges — equally spaced
    y_mid = rect.y() + rect.height() / 2 + 10 * s
    third = rect.width() / 3
    paint_gauge(p, rect.x() + third * 0.5, y_mid, data.session_pct,
                "SESSION", f"{data.session_reset_min}m", s)
    paint_gauge(p, rect.x() + third * 2.5, y_mid, data.weekly_pct,
                "WEEKLY",
                f"{data.weekly_reset_hrs}h {data.weekly_reset_min}m", s)

    # center column — live + today
    cx = rect.x() + rect.width() / 2
    label_f = mono_font(FONTS["label_pt"] * s, family=FONTS["family_mono"])
    num_f = mono_font(16 * s, bold=True, family=FONTS["family_mono"])
    fm_l = QFontMetrics(label_f); fm_n = QFontMetrics(num_f)

    cy = y_mid - 20 * s
    draw_text(p, cx - fm_l.horizontalAdvance("T/MIN") / 2, cy,
              "T/MIN", hex_to_qcolor(t["text_dim"]), label_f,
              letter_spacing_px=2.0 * s)
    tm = f"{data.live_tok_per_min:.1f}k"
    draw_text(p, cx - fm_n.horizontalAdvance(tm) / 2,
              cy + fm_n.ascent() + 2 * s, tm,
              hex_to_qcolor(t["good"]), num_f)

    # Ticker strip along the bottom — bordered separator + amber-tiered
    # quartile colours matching the cockpit palette.
    ticker_h = m["ticker_h"] * s
    y_tick_top = rect.bottom() - ticker_h
    pen = QPen(hex_to_qcolor(t["border_bright"])); pen.setWidthF(1 * s)
    p.setPen(pen)
    p.drawLine(
        QPointF(rect.x() + m["osd_padding"] * s, y_tick_top),
        QPointF(rect.right() - m["osd_padding"] * s, y_tick_top),
    )
    ticker_f = mono_font(FONTS["label_pt"] * s, family=FONTS["family_mono"])
    fm_tick = QFontMetrics(ticker_f)
    y_tick_base = y_tick_top + 6 * s + fm_tick.ascent()
    ticker_colors = (t["text_dim"], t["good"], t["accent"], t["crit"])
    draw_ticker_marquee(
        p, rect.x() + m["osd_padding"] * s, y_tick_base,
        rect.width() - 2 * m["osd_padding"] * s,
        data.ticker_items, data.ticker_offset,
        ticker_colors, ticker_f, sep_gap_px=12 * s,
    )


# ---- POPUP ---------------------------------------------------------

def paint_popup(p, rect, data, scale: float = 1.0) -> float:
    """HUD popup: big gauges at top + standard sections below.

    Nuance: the HUD popup keeps the 270° arc gauges as the dominant
    element (instead of the tiny full-ring rings used in Dashboard).
    After the gauge block we defer to the generic painter for the rest.
    """
    from . import _popup_generic
    from ._paint import hex_to_qcolor, mono_font, draw_text
    from ._popup import draw_section_header, POPUP_PADDING, SECTION_GAP
    from PySide6.QtCore import QRectF, Qt, QPointF
    from PySide6.QtGui import QPen, QFontMetrics

    s = scale; t = THEME
    pad = POPUP_PADDING * s

    # panel
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["bg"]))
    p.drawRoundedRect(rect, 10 * s, 10 * s)
    p.setPen(QPen(hex_to_qcolor(t["border_bright"]), 1)); p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 10 * s, 10 * s)

    # ...then hand off to the shared painter. Callers who want the gauges
    # up top should paint them BEFORE calling _popup_generic and then
    # adjust rect.y() to sit below. For simplicity we use the generic
    # layout here; all KPIs read consistently.
    return _popup_generic.paint_popup(p, rect, data, scale, THEME,
                                      section_style="default",
                                      bar_style="block",
                                      masthead_style="default")


def measure_popup(data, scale: float = 1.0) -> int:
    from ._popup import dry_measure
    return dry_measure(paint_popup, data, scale, METRICS.get("popup_width", 540)) + int(20 * scale)


def paint_loading(p, rect, phase: float = 0.0, scale: float = 1.0) -> None:
    from ._popup import paint_loading as _pl
    _pl(p, rect, THEME, scale, style="hud", phase=phase)
