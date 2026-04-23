"""Direction 5 — Stacked Strip.

Ultra-compact horizontal strip that mimics a menubar extra. Segmented
layout: [title][session bar][weekly bar][live]. 480×54 at base scale.

Nuances:
- Each segment is divided by a 1px vertical rule at border color, full
  height minus 0 inset.
- Bars in this view are hairline (3px) rounded rects.
- Label above each bar is a tiny 9pt ALL-CAPS, the % is to the right
  at body size, the reset window is a secondary text-dim suffix.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFontMetrics, QPainter

from ._paint import draw_block_bar, draw_text, hex_to_qcolor, mono_font, ui_font


THEME = {
    "style":          "strip",
    "bg":             "#0e1012",
    "panel":          "#181b21",
    "border":         "#23272f",
    "bar_blue":       "#6be3b6",
    "bar_track":      "#22262e",
    "text_primary":   "#e6e8ec",
    "text_secondary": "#7e8490",
    "text_dim":       "#5a606c",
    "text_link":      "#6be3b6",
    "separator":      "#23272f",
    "warn":           "#e8b15b",
    "crit":           "#e66466",
    "error":          "#e66466",
    "live_indicator": "#6be3b6",
    "accent":         "#6be3b6",
    "accent2":        "#4db79a",
    "very_dim":       "#22262e",
}

METRICS = {
    "osd_width": 480, "osd_height": 54, "osd_radius": 8, "osd_padding": 0,
    "seg_title_w": 96, "seg_live_w": 96,
    "bar_h": 3,
}

FONTS = {"family_mono": "JetBrains Mono", "family_ui": "Inter",
         "label_pt": 9, "body_pt": 11}


def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    s = scale; t = THEME; m = METRICS

    # panel
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["bg"], 0.94))
    p.drawRoundedRect(rect, m["osd_radius"] * s, m["osd_radius"] * s)
    p.setPen(hex_to_qcolor(t["border"])); p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                      m["osd_radius"] * s, m["osd_radius"] * s)

    # segment 1: title
    title_w = m["seg_title_w"] * s
    live_w = m["seg_live_w"] * s
    mid_w = (rect.width() - title_w - live_w) / 2

    label_f = mono_font(9 * s, family=FONTS["family_mono"])
    body_f = mono_font(11 * s, bold=True, family=FONTS["family_mono"])
    fm = QFontMetrics(label_f); fm_b = QFontMetrics(body_f)

    # title segment
    x0 = rect.x()
    # accent dot
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["accent"]))
    p.drawEllipse(QPointF(x0 + 16 * s, rect.y() + rect.height() / 2), 4 * s, 4 * s)
    draw_text(p, x0 + 28 * s, rect.y() + rect.height() / 2 + fm.ascent() / 2 - 2,
              "CLAUDE", hex_to_qcolor(t["text_secondary"]), label_f,
              letter_spacing_px=2 * s)
    # rule
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(x0 + title_w, rect.y() + 4 * s),
               QPointF(x0 + title_w, rect.bottom() - 4 * s))

    # generic segment painter
    def seg(x: float, w: float, label: str, pct: float, suffix: str, fill_hex: str):
        # label top
        draw_text(p, x + 12 * s, rect.y() + 14 * s + fm.ascent() / 2,
                  label, hex_to_qcolor(t["text_dim"]), label_f,
                  letter_spacing_px=1.5 * s)
        # % + suffix right
        pct_txt = f"{int(pct * 100)}%"
        adv = QFontMetrics(body_f).horizontalAdvance(pct_txt)
        suf_w = fm.horizontalAdvance(suffix)
        draw_text(p, x + w - 12 * s - suf_w - 6 * s - adv,
                  rect.y() + 14 * s + fm.ascent() / 2,
                  pct_txt, hex_to_qcolor(t["text_primary"]), body_f)
        draw_text(p, x + w - 12 * s - suf_w,
                  rect.y() + 14 * s + fm.ascent() / 2,
                  suffix, hex_to_qcolor(t["text_dim"]), label_f)
        # bar
        bar_y = rect.y() + rect.height() - 14 * s
        draw_block_bar(p, x + 12 * s, bar_y, w - 24 * s, m["bar_h"] * s,
                       pct, hex_to_qcolor(t["very_dim"]),
                       hex_to_qcolor(fill_hex), radius=1.5 * s)

    # session seg
    xs = x0 + title_w
    seg(xs, mid_w, "SESSION", data.session_pct,
        f"{data.session_reset_min}m", t["accent"])
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(xs + mid_w, rect.y() + 4 * s),
               QPointF(xs + mid_w, rect.bottom() - 4 * s))

    # weekly seg
    xw = xs + mid_w
    seg(xw, mid_w, "WEEKLY", data.weekly_pct,
        f"{data.weekly_reset_hrs}h", t["accent2"])
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(xw + mid_w, rect.y() + 4 * s),
               QPointF(xw + mid_w, rect.bottom() - 4 * s))

    # live seg
    xl = xw + mid_w
    if getattr(data, "is_live", False):
        draw_text(p, xl + 12 * s,
                  rect.y() + 18 * s,
                  f"● LIVE", hex_to_qcolor(t["accent"]), label_f,
                  letter_spacing_px=1 * s)
        draw_text(p, xl + 12 * s,
                  rect.y() + 36 * s,
                  f"{data.live_tok_per_min:.1f}k/min",
                  hex_to_qcolor(t["text_primary"]), label_f)
