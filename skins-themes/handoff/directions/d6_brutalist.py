"""Direction 6 — Brutalist Mono.

Swiss grid / newspaper. Off-white bg, pure black ink, one crimson accent.
Heavy 2px section rules, Space Mono for all text, everything ALL CAPS.

Nuances:
- Section break is a pair of horizontal lines: top at 2px black, bottom
  at 1px black, with section number + title between them.
- Section number uses the CRIMSON accent; the title is black.
- Progress bars are RECTANGULAR (no radius), with a hard 1px black
  border. Session bar fills red, weekly bar fills black. This is
  intentional asymmetry — session is the "hot" one.
- Live badge is a red rect with white text, 1px wide letters. No
  inner padding besides 4px.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen

from .._paint import draw_text, hex_to_qcolor, mono_font


THEME = {
    "style":          "brutalist",
    "bg":             "#eeece7",
    "panel":          "#ffffff",
    "bar_blue":       "#d81f26",
    "bar_track":      "#1f1f1f",
    "text_primary":   "#0a0a0a",
    "text_secondary": "#575757",
    "text_dim":       "#8b8b8b",
    "text_link":      "#d81f26",
    "separator":      "#0a0a0a",
    "warn":           "#d81f26",
    "crit":           "#d81f26",
    "error":          "#d81f26",
    "live_indicator": "#d81f26",
    "ink":            "#0a0a0a",
    "accent":         "#d81f26",
    "hair":           "#d4d2cc",
    "very_dim":       "#c8c6c0",
}

METRICS = {
    "osd_width": 360, "osd_height": 200, "osd_radius": 0, "osd_padding": 12,
    "border_width": 2,
}

FONTS = {"family_mono": "Space Mono", "body_pt": 10, "title_pt": 11}


def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    s = scale; t = THEME
    pad = METRICS["osd_padding"] * s

    # panel: white fill + heavy black 2px border
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["panel"]))
    p.drawRect(rect)
    pen = QPen(hex_to_qcolor(t["ink"])); pen.setWidthF(METRICS["border_width"] * s)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawRect(rect.adjusted(1 * s, 1 * s, -1 * s, -1 * s))

    x = rect.x() + pad; y = rect.y() + pad
    w = rect.width() - pad * 2

    title_f = mono_font(FONTS["title_pt"] * s, bold=True, family=FONTS["family_mono"])
    body_f = mono_font(FONTS["body_pt"] * s, family=FONTS["family_mono"])
    big_f = mono_font(14 * s, bold=True, family=FONTS["family_mono"])
    small_f = mono_font(9 * s, family=FONTS["family_mono"])
    fm = QFontMetrics(title_f); fm_b = QFontMetrics(big_f); fm_s = QFontMetrics(small_f)

    # top bar
    draw_text(p, x, y + fm.ascent(),
              "CLAUDE / USAGE",
              hex_to_qcolor(t["ink"]), title_f, letter_spacing_px=3 * s)

    if getattr(data, "is_live", False):
        label = "LIVE"
        lw = fm_s.horizontalAdvance(label)
        # red badge
        p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["accent"]))
        badge = QRectF(rect.right() - pad - lw - 10 * s - 60 * s,
                       y + 2 * s, lw + 8 * s, fm.height() - 2 * s)
        p.drawRect(badge)
        draw_text(p, badge.x() + 4 * s, badge.y() + fm_s.ascent() + 2 * s,
                  label, QColor("#ffffff"), small_f, letter_spacing_px=2 * s)
        tm = f"{data.live_tok_per_min:.1f}K/MIN"
        draw_text(p, badge.right() + 6 * s, badge.y() + fm_s.ascent() + 2 * s,
                  tm, hex_to_qcolor(t["ink"]), small_f, letter_spacing_px=1.5 * s)

    # 2px rule under header
    y_rule = y + fm.height() + 4 * s
    pen = QPen(hex_to_qcolor(t["ink"])); pen.setWidthF(2 * s)
    p.setPen(pen)
    p.drawLine(QPointF(x, y_rule), QPointF(x + w, y_rule))

    def row(yy: float, label: str, pct: float, suffix: str, fill_hex: str):
        # label left
        draw_text(p, x, yy + fm_s.ascent(),
                  label, hex_to_qcolor(t["ink"]), small_f, letter_spacing_px=2 * s)
        # % right
        pct_txt = f"{int(pct * 100)}%"
        pw = QFontMetrics(big_f).horizontalAdvance(pct_txt)
        draw_text(p, x + w - pw, yy + fm_b.ascent(),
                  pct_txt, hex_to_qcolor(t["ink"]), big_f)
        # rect bar below
        ybar = yy + fm_b.height() + 2 * s
        p.setPen(QPen(hex_to_qcolor(t["ink"]), 1 * s))
        p.setBrush(hex_to_qcolor(t["very_dim"]))
        p.drawRect(QRectF(x, ybar, w, 14 * s))
        p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(fill_hex))
        p.drawRect(QRectF(x + 1, ybar + 1, (w - 2) * pct, 14 * s - 2))
        # reset
        draw_text(p, x, ybar + 14 * s + fm_s.ascent() + 2 * s,
                  suffix, hex_to_qcolor(t["text_secondary"]), small_f,
                  letter_spacing_px=1.5 * s)
        return ybar + 14 * s + fm_s.height() + 6 * s

    yy = y_rule + 10 * s
    yy = row(yy, "SESSION", data.session_pct,
             f"RESETS {data.session_reset_min}M", t["accent"])
    yy = row(yy, "WEEKLY", data.weekly_pct,
             f"RESETS {data.weekly_reset_hrs}H {data.weekly_reset_min}M",
             t["ink"])
