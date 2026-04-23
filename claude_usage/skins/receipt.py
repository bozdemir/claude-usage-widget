"""Direction 4 — Print Receipt.

Thermal paper metaphor. Cream bg, near-black mono ink, dashed rules,
one receipt-red accent for warnings only. Subtle horizontal grain.

Nuances:
- Grain: 1px horizontal line at alpha=6/255 every 3px across the full
  paper area. Skip this at scale<0.8 — it becomes moire.
- Dashed rules use Qt.DashLine with a custom dash pattern [4, 3] in
  pen-width multiples. Set pen.setDashPattern([4, 3]).
- Dotted rules between list rows use a 1px pen at alpha 0.35.
- Total line uses a thick 2px solid line above + large bold number.
- The "barcode" at the bottom is 60 rects with random widths in
  [1, 3.5] px. Seed the random (use index-based) so it doesn't flicker
  between paints.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen

from ._paint import (
    draw_block_bar, draw_text, draw_ticker_marquee, hex_to_qcolor, mono_font,
)


WANTS_TICKER = True


THEME = {
    "style":          "receipt",
    "bg":             "#f3efe5",
    "paper":          "#faf6ec",
    "bar_blue":       "#16110a",
    "bar_track":      "#d8cfb9",
    "text_primary":   "#16110a",
    "text_secondary": "#43382a",
    "text_dim":       "#8a7d68",
    "text_link":      "#b4331c",
    "separator":      "#cfc6b2",
    "warn":           "#b4331c",
    "crit":           "#b4331c",
    "error":          "#b4331c",
    "live_indicator": "#3a6b3a",
    "ink":            "#16110a",
    "accent":         "#b4331c",
    "rule":           "#a79c85",
    "hair":           "#cfc6b2",
}

METRICS = {
    "osd_width": 340, "osd_height": 234, "osd_radius": 2, "osd_padding": 16,
    "popup_width": 540, "popup_padding": 26,
    "grain_step_px": 3, "ticker_h": 22,
}

FONTS = {"family_mono": "JetBrains Mono", "body_pt": 10, "title_pt": 11}


def _draw_grain(p: QPainter, rect: QRectF, step: float = 3.0) -> None:
    """Horizontal scanline grain. ~2% alpha, every `step` px."""
    p.setPen(QPen(QColor(0, 0, 0, 6), 1))
    y = rect.y()
    while y < rect.bottom():
        p.drawLine(QPointF(rect.x(), y), QPointF(rect.right(), y))
        y += step


def _draw_dashed_rule(p: QPainter, x1: float, y: float, x2: float,
                     color: QColor, dash: tuple[float, float] = (4, 3)) -> None:
    pen = QPen(color)
    pen.setWidthF(1)
    pen.setDashPattern([dash[0], dash[1]])
    p.setPen(pen)
    p.drawLine(QPointF(x1, y), QPointF(x2, y))


def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    s = scale; t = THEME; m = METRICS
    pad = m["osd_padding"] * s

    # paper
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["paper"]))
    p.drawRoundedRect(rect, 2 * s, 2 * s)
    p.setPen(hex_to_qcolor(t["rule"])); p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 2 * s, 2 * s)
    if scale >= 0.8:
        _draw_grain(p, rect, m["grain_step_px"] * s)

    x = rect.x() + pad; y = rect.y() + pad
    w = rect.width() - pad * 2

    title_f = mono_font(FONTS["title_pt"] * s, bold=True, family=FONTS["family_mono"])
    body_f  = mono_font(FONTS["body_pt"] * s, family=FONTS["family_mono"])
    small_f = mono_font(FONTS["body_pt"] * s * 0.85, family=FONTS["family_mono"])
    fm = QFontMetrics(body_f); fm_t = QFontMetrics(title_f)

    # centered masthead
    title = "* CLAUDE USAGE *"
    tw = fm_t.horizontalAdvance(title)
    draw_text(p, rect.x() + (rect.width() - tw) / 2,
              y + fm_t.ascent(), title,
              hex_to_qcolor(t["ink"]), title_f, letter_spacing_px=3 * s)
    sub = "RCPT #00231 · JUST NOW"
    sw = QFontMetrics(small_f).horizontalAdvance(sub)
    draw_text(p, rect.x() + (rect.width() - sw) / 2,
              y + fm_t.height() + QFontMetrics(small_f).ascent(),
              sub, hex_to_qcolor(t["text_dim"]), small_f)

    y_rule = y + fm_t.height() + fm.height() + 2 * s
    _draw_dashed_rule(p, x, y_rule, x + w, hex_to_qcolor(t["rule"]))

    # SESSION row + bar
    yy = y_rule + 6 * s
    draw_text(p, x, yy + fm.ascent(), "SESSION",
              hex_to_qcolor(t["ink"]), body_f)
    right = f"{int(data.session_pct * 100)}% · {data.session_reset_min}m"
    rw = fm.horizontalAdvance(right)
    draw_text(p, x + w - rw, yy + fm.ascent(), right,
              hex_to_qcolor(t["ink"]), body_f)
    yy += fm.height() + 2 * s
    # bar is a rect with 1px ink border
    p.setPen(hex_to_qcolor(t["rule"])); p.setBrush(hex_to_qcolor(t["bar_track"]))
    p.drawRect(QRectF(x, yy, w, 8 * s))
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["ink"]))
    p.drawRect(QRectF(x, yy, w * data.session_pct, 8 * s))

    # WEEKLY
    yy += 8 * s + 6 * s
    draw_text(p, x, yy + fm.ascent(), "WEEKLY",
              hex_to_qcolor(t["ink"]), body_f)
    right = f"{int(data.weekly_pct * 100)}% · {data.weekly_reset_hrs}h{data.weekly_reset_min}m"
    rw = fm.horizontalAdvance(right)
    draw_text(p, x + w - rw, yy + fm.ascent(), right,
              hex_to_qcolor(t["ink"]), body_f)
    yy += fm.height() + 2 * s
    p.setPen(hex_to_qcolor(t["rule"])); p.setBrush(hex_to_qcolor(t["bar_track"]))
    p.drawRect(QRectF(x, yy, w, 8 * s))
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["ink"]))
    p.drawRect(QRectF(x, yy, w * data.weekly_pct, 8 * s))

    # Ticker marquee (between the weekly bar and the thank-you footer).
    yy += 8 * s + 6 * s
    ticker_f = mono_font(FONTS["body_pt"] * s * 0.85, family=FONTS["family_mono"])
    fm_t = QFontMetrics(ticker_f)
    # Dashed top rule — matches the stationery feel.
    pen = QPen(hex_to_qcolor(t["rule"])); pen.setWidthF(1)
    pen.setDashPattern([4, 3]); p.setPen(pen)
    p.drawLine(QPointF(x, yy), QPointF(x + w, yy))
    yy_base = yy + 6 * s + fm_t.ascent()
    # Receipt colors — black for most, red for hot (>= dollar).
    ticker_colors = (t["text_dim"], t["ink"], t["ink"], t["accent"])
    draw_ticker_marquee(
        p, x, yy_base, w,
        data.ticker_items, data.ticker_offset,
        ticker_colors, ticker_f, sep_gap_px=8 * s,
    )
    yy = yy_base + fm_t.descent() + 6 * s

    # thank-you footer
    foot = "— THANK YOU —"
    fw = QFontMetrics(small_f).horizontalAdvance(foot)
    draw_text(p, rect.x() + (rect.width() - fw) / 2,
              yy + QFontMetrics(small_f).ascent(),
              foot, hex_to_qcolor(t["text_dim"]), small_f,
              letter_spacing_px=2 * s)
