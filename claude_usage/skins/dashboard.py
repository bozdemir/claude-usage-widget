"""Direction 2 — Data Dashboard.

Bloomberg's clean cousin. Tight KPI rows with a small ring chart per
metric, cool blue accent, Inter for chrome + JetBrains Mono for numbers.

Nuances:
- The ring chart uses FULL 360° (not 270° like the HUD direction).
  Stroke caps are ROUND for a slight visual softness.
- Labels are tiny (9pt) ALL-CAPS with 1.8px letter-spacing. Kerning
  matters — use QFont.setLetterSpacing(AbsoluteSpacing, 1.8 * scale).
- Metric number + % is a SINGLE text run with different sizes:
  "49" at 20pt + "%" at 12pt, same baseline. Advance the x cursor
  between the two calls.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from ._paint import (
    draw_block_bar, draw_text, draw_ticker_marquee, hex_to_qcolor, mono_font, ui_font,
)


WANTS_TICKER = True


THEME = {
    "style":          "dashboard",
    '_mono_family'    : 'JetBrains Mono',
    '_ui_family'      : 'Inter',
    'paper'           : '#0f1114',
    "bg":             "#0f1114",
    "panel":          "#151820",
    "panel2":         "#1b1f28",
    "border":         "#262a35",
    "bar_blue":       "#6ea8fe",
    "bar_track":      "#2b2f3a",
    "text_primary":   "#e4e6ec",
    "text_secondary": "#7c808c",
    "text_dim":       "#565968",
    "text_link":      "#6ea8fe",
    "separator":      "#232631",
    "warn":           "#f0b46a",
    "crit":           "#e76a6a",
    "error":          "#e76a6a",
    "live_indicator": "#5fd7a5",
    "accent":         "#6ea8fe",
    "accent2":        "#4e8be8",
    "very_dim":       "#2b2f3a",
}

METRICS = {
    "osd_width": 380, "osd_height": 196, "osd_radius": 8, "osd_padding": 14,
    "popup_width": 540, "popup_padding": 18,
    "ring_size": 58, "ring_stroke": 6, "row_bar_height": 4,
    "ticker_h": 24,
}

FONTS = {
    "family_mono": "JetBrains Mono", "family_ui": "Inter",
    "label_pt": 9, "body_pt": 11, "metric_pt": 20, "title_pt": 10,
}


def _draw_ring_full(p: QPainter, cx: float, cy: float, r: float,
                    stroke: float, pct: float, track: QColor, fill: QColor) -> None:
    rect = QRectF(cx - r, cy - r, r * 2, r * 2)
    pen = QPen(track); pen.setWidthF(stroke); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawArc(rect, 0, 360 * 16)
    if pct > 0:
        pen2 = QPen(fill); pen2.setWidthF(stroke); pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        # start at 12 o'clock (-90°), CCW sweep
        p.drawArc(rect, 90 * 16, -int(360 * pct * 16))


def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    s = scale; t = THEME; m = METRICS
    pad = m["osd_padding"] * s

    # panel
    p.setPen(Qt.NoPen)
    p.setBrush(hex_to_qcolor(t["bg"], 0.92))
    p.drawRoundedRect(rect, m["osd_radius"] * s, m["osd_radius"] * s)
    p.setPen(hex_to_qcolor(t["border"]))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                      m["osd_radius"] * s, m["osd_radius"] * s)

    label_f = ui_font(FONTS["label_pt"] * s, family=FONTS["family_ui"])
    body_f  = mono_font(FONTS["body_pt"] * s, family=FONTS["family_mono"])
    metric_f = mono_font(FONTS["metric_pt"] * s, bold=True, family=FONTS["family_mono"])
    small_f  = mono_font(FONTS["label_pt"] * s, family=FONTS["family_mono"])

    x = rect.x() + pad; y = rect.y() + pad
    w = rect.width() - pad * 2

    # header: CLAUDE | ⚙ N SUBAGENTS       ● LIVE 10.5K T/M
    fm = QFontMetrics(label_f)
    bl = y + fm.ascent()
    draw_text(p, x, bl, "CLAUDE", hex_to_qcolor(t["text_secondary"]),
              label_f, letter_spacing_px=2.0 * s)
    # vertical separator
    sep_x = x + fm.horizontalAdvance("CLAUDE") + 10 * s
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(sep_x, y + 2 * s), QPointF(sep_x, y + fm.height()))
    if getattr(data, "subagent_count", 0):
        draw_text(p, sep_x + 10 * s, bl,
                  f"⚙ {data.subagent_count} SUBAGENTS",
                  hex_to_qcolor(t["text_secondary"]), small_f,
                  letter_spacing_px=1.5 * s)

    if getattr(data, "is_live", False):
        live = f"● LIVE {data.live_tok_per_min:.1f}K T/M"
        lw = QFontMetrics(small_f).horizontalAdvance(live) + 2 * s
        draw_text(p, x + w - lw, bl, live,
                  hex_to_qcolor(t["live_indicator"]), small_f,
                  letter_spacing_px=1.0 * s)

    # rows: SESSION + WEEKLY
    rows = [
        ("SESSION", data.session_pct, f"{data.session_reset_min}m", t["accent"]),
        ("WEEKLY",  data.weekly_pct,  f"{data.weekly_reset_hrs}h {data.weekly_reset_min}m", t["accent2"]),
    ]
    y_cursor = y + fm.height() + 8 * s
    fm_metric = QFontMetrics(metric_f)
    for label, pct, reset, color_hex in rows:
        # left: label + big number
        draw_text(p, x, y_cursor + fm.ascent(), label,
                  hex_to_qcolor(t["text_dim"]), small_f,
                  letter_spacing_px=1.5 * s)
        num_baseline = y_cursor + fm.ascent() + fm_metric.ascent()
        pct_txt = f"{int(pct * 100)}"
        adv = draw_text(p, x, num_baseline + 4 * s, pct_txt,
                        hex_to_qcolor(t["text_primary"]), metric_f)
        draw_text(p, x + adv + 2 * s, num_baseline + 4 * s, "%",
                  hex_to_qcolor(t["text_dim"]), body_f)

        # right-align reset
        reset_w = QFontMetrics(small_f).horizontalAdvance(reset)
        draw_text(p, x + w - reset_w,
                  num_baseline + 4 * s,
                  reset, hex_to_qcolor(t["text_dim"]), small_f)

        # thin bar — 60px in from left (skip metric column), to (w-reset)
        bar_x = x + 70 * s
        bar_y = num_baseline + 8 * s
        bar_w = w - 70 * s - reset_w - 8 * s
        draw_block_bar(p, bar_x, bar_y, bar_w, m["row_bar_height"] * s,
                       pct, hex_to_qcolor(t["very_dim"]),
                       hex_to_qcolor(color_hex), radius=0)
        y_cursor += fm.height() + fm_metric.height() + 12 * s

    # Ticker strip along the bottom — separator line above, 5-bucket
    # quartile colouring, scrolling right-to-left.
    ticker_h = m["ticker_h"] * s
    y_sep = rect.bottom() - ticker_h - 2 * s
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(x, y_sep), QPointF(x + w, y_sep))
    ticker_f = mono_font(FONTS["label_pt"] * s, family=FONTS["family_mono"])
    fm_t = QFontMetrics(ticker_f)
    ticker_colors = (t["text_dim"], t["accent"], t["warn"], t["crit"])
    y_base = y_sep + 6 * s + fm_t.ascent()
    draw_ticker_marquee(
        p, x, y_base, w,
        data.ticker_items, data.ticker_offset,
        ticker_colors, ticker_f, sep_gap_px=12 * s,
    )


# ---- POPUP ----------------------------------------------------

def paint_popup(p, rect, data, scale: float = 1.0):
    """Dashboard popup: accent-number section headers + block bars."""
    from . import _popup_generic
    _popup_generic.paint_popup(p, rect, data, scale, THEME,
                               section_style="default",
                               bar_style="block",
                               masthead_style="default")


def _draw_ring_full(p: QPainter, cx: float, cy: float, r: float,
                    stroke: float, pct: float, track: QColor, fill: QColor) -> None:
    rect = QRectF(cx - r, cy - r, r * 2, r * 2)
    pen = QPen(track); pen.setWidthF(stroke); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawArc(rect, 0, 360 * 16)
    if pct > 0:
        pen2 = QPen(fill); pen2.setWidthF(stroke); pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        # start at 12 o'clock (-90°), CCW sweep
        p.drawArc(rect, 90 * 16, -int(360 * pct * 16))


def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    s = scale; t = THEME; m = METRICS
    pad = m["osd_padding"] * s

    # panel
    p.setPen(Qt.NoPen)
    p.setBrush(hex_to_qcolor(t["bg"], 0.92))
    p.drawRoundedRect(rect, m["osd_radius"] * s, m["osd_radius"] * s)
    p.setPen(hex_to_qcolor(t["border"]))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                      m["osd_radius"] * s, m["osd_radius"] * s)

    label_f = ui_font(FONTS["label_pt"] * s, family=FONTS["family_ui"])
    body_f  = mono_font(FONTS["body_pt"] * s, family=FONTS["family_mono"])
    metric_f = mono_font(FONTS["metric_pt"] * s, bold=True, family=FONTS["family_mono"])
    small_f  = mono_font(FONTS["label_pt"] * s, family=FONTS["family_mono"])

    x = rect.x() + pad; y = rect.y() + pad
    w = rect.width() - pad * 2

    # header: CLAUDE | ⚙ N SUBAGENTS       ● LIVE 10.5K T/M
    fm = QFontMetrics(label_f)
    bl = y + fm.ascent()
    draw_text(p, x, bl, "CLAUDE", hex_to_qcolor(t["text_secondary"]),
              label_f, letter_spacing_px=2.0 * s)
    # vertical separator
    sep_x = x + fm.horizontalAdvance("CLAUDE") + 10 * s
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(sep_x, y + 2 * s), QPointF(sep_x, y + fm.height()))
    if getattr(data, "subagent_count", 0):
        draw_text(p, sep_x + 10 * s, bl,
                  f"⚙ {data.subagent_count} SUBAGENTS",
                  hex_to_qcolor(t["text_secondary"]), small_f,
                  letter_spacing_px=1.5 * s)

    if getattr(data, "is_live", False):
        live = f"● LIVE {data.live_tok_per_min:.1f}K T/M"
        lw = QFontMetrics(small_f).horizontalAdvance(live) + 2 * s
        draw_text(p, x + w - lw, bl, live,
                  hex_to_qcolor(t["live_indicator"]), small_f,
                  letter_spacing_px=1.0 * s)

    # rows: SESSION + WEEKLY
    rows = [
        ("SESSION", data.session_pct, f"{data.session_reset_min}m", t["accent"]),
        ("WEEKLY",  data.weekly_pct,  f"{data.weekly_reset_hrs}h {data.weekly_reset_min}m", t["accent2"]),
    ]
    y_cursor = y + fm.height() + 8 * s
    fm_metric = QFontMetrics(metric_f)
    for label, pct, reset, color_hex in rows:
        # left: label + big number
        draw_text(p, x, y_cursor + fm.ascent(), label,
                  hex_to_qcolor(t["text_dim"]), small_f,
                  letter_spacing_px=1.5 * s)
        num_baseline = y_cursor + fm.ascent() + fm_metric.ascent()
        pct_txt = f"{int(pct * 100)}"
        adv = draw_text(p, x, num_baseline + 4 * s, pct_txt,
                        hex_to_qcolor(t["text_primary"]), metric_f)
        draw_text(p, x + adv + 2 * s, num_baseline + 4 * s, "%",
                  hex_to_qcolor(t["text_dim"]), body_f)

        # right-align reset
        reset_w = QFontMetrics(small_f).horizontalAdvance(reset)
        draw_text(p, x + w - reset_w,
                  num_baseline + 4 * s,
                  reset, hex_to_qcolor(t["text_dim"]), small_f)

        # thin bar — 60px in from left (skip metric column), to (w-reset)
        bar_x = x + 70 * s
        bar_y = num_baseline + 8 * s
        bar_w = w - 70 * s - reset_w - 8 * s
        draw_block_bar(p, bar_x, bar_y, bar_w, m["row_bar_height"] * s,
                       pct, hex_to_qcolor(t["very_dim"]),
                       hex_to_qcolor(color_hex), radius=0)
        y_cursor += fm.height() + fm_metric.height() + 12 * s
