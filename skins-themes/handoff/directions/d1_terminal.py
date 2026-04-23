"""Direction 1 — Terminal Classic.

htop/btop vibe. Mono everything, box-drawing characters for chrome,
one green accent. ASCII █░ progress bars. High readability, small
chrome, nothing cute.

Nuances that are easy to miss:
- Box-drawing chars (┌─ ╔═ ╚═) must use a mono font that has them in
  its bundled glyphs; JetBrains Mono and Menlo both do. If you see
  boxes render as tofu (□), the font fallback chain failed.
- The green accent only lights up ACTIVE elements (title + LIVE + fills).
  Everything else stays neutral. Resist the urge to green-tint labels.
- Ticker colors are the SAME 4 quartile tiers the existing ticker.py
  emits — we just remap tier 0/1/2/3 to (dim, link, warn, crit).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter

from .._paint import (
    draw_ascii_bar, draw_block_bar, draw_heatmap_52w, draw_sparkline_bars,
    draw_text, hex_to_qcolor, mono_font,
)


THEME = {
    "style":          "terminal",
    "bg":             "#0a0f0a",
    "panel":          "#0e1411",
    "border":         "#1d2a22",
    "bar_blue":       "#5fd787",   # accent — used wherever the default theme uses bar_blue
    "bar_track":      "#2e4238",
    "text_primary":   "#d7e3d7",
    "text_secondary": "#7a9889",
    "text_dim":       "#668c75",
    "text_link":      "#87d7d7",
    "separator":      "#1d2a22",
    "warn":           "#d7c85f",
    "crit":           "#ff6b6b",
    "error":          "#ff6b6b",
    "live_indicator": "#5fd787",
    # direction-specific
    "accent":         "#5fd787",
    "very_dim":       "#2e4238",
}

METRICS = {
    "osd_width":       440,
    "osd_height":      172,
    "osd_radius":      6,
    "osd_padding":     12,
    "osd_row_gap":     8,
    "osd_bar_cols":    30,     # ASCII cells in each progress bar
    "popup_width":     540,
    "popup_padding":   18,
    "section_gap":     18,
    "heatmap_cell":    7,
    "heatmap_gap":     2,
}

FONTS = {
    "title_pt":    11,
    "section_pt":  10,
    "body_pt":     10,
    "metric_pt":   18,
    "ticker_pt":   9,
    "family":      "JetBrains Mono",
}


# ---- OSD -----------------------------------------------------------

def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    """Draws the OSD bars view. `data` is the same UsageStats shape the
    existing overlay.py consumes."""
    s = scale
    m = METRICS
    t = THEME
    pad = m["osd_padding"] * s

    # panel
    p.setPen(Qt.NoPen)
    p.setBrush(hex_to_qcolor(t["bg"], 0.92))
    p.drawRoundedRect(rect, m["osd_radius"] * s, m["osd_radius"] * s)

    x = rect.x() + pad
    y = rect.y() + pad
    w = rect.width() - pad * 2

    body_f   = mono_font(FONTS["body_pt"] * s, family=FONTS["family"])
    title_f  = mono_font(FONTS["title_pt"] * s, bold=True, family=FONTS["family"])
    ticker_f = mono_font(FONTS["ticker_pt"] * s, family=FONTS["family"])

    fm = QFontMetrics(body_f)
    line_h = fm.height()

    # titlebar  ┌─ CLAUDE  ⚙ N        ● LIVE 10.5k t/m
    baseline = y + fm.ascent()
    adv = draw_text(p, x, baseline, "┌─ CLAUDE", hex_to_qcolor(t["accent"]), title_f, letter_spacing_px=1.0 * s)
    if getattr(data, "subagent_count", 0):
        draw_text(p, x + adv + 8 * s, baseline, f"⚙ {data.subagent_count}",
                  hex_to_qcolor(t["text_secondary"]), body_f)

    live_text = f"● LIVE {data.live_tok_per_min:.1f}k t/m" if getattr(data, "is_live", False) else ""
    if live_text:
        lw = QFontMetrics(body_f).horizontalAdvance(live_text)
        draw_text(p, x + w - lw, baseline, live_text, hex_to_qcolor(t["accent"]), body_f)

    # session row
    y_row = y + line_h + m["osd_row_gap"] * s
    draw_text(p, x, y_row + fm.ascent(), "session",
              hex_to_qcolor(t["text_secondary"]), body_f)
    right = f"{data.session_reset_min}m · {int(data.session_pct*100)}%"
    rw = fm.horizontalAdvance(right)
    draw_text(p, x + w - rw, y_row + fm.ascent(), right,
              hex_to_qcolor(t["text_secondary"]), body_f)
    y_bar = y_row + line_h + 2 * s
    draw_ascii_bar(p, x, y_bar + fm.ascent(), data.session_pct,
                   m["osd_bar_cols"],
                   hex_to_qcolor(t["accent"]), hex_to_qcolor(t["very_dim"]),
                   body_f)

    # weekly row
    y_row = y_bar + line_h + m["osd_row_gap"] * s
    draw_text(p, x, y_row + fm.ascent(), "weekly",
              hex_to_qcolor(t["text_secondary"]), body_f)
    right = f"{data.weekly_reset_hrs}h {data.weekly_reset_min}m · {int(data.weekly_pct*100)}%"
    rw = fm.horizontalAdvance(right)
    draw_text(p, x + w - rw, y_row + fm.ascent(), right,
              hex_to_qcolor(t["text_secondary"]), body_f)
    y_bar = y_row + line_h + 2 * s
    draw_ascii_bar(p, x, y_bar + fm.ascent(), data.weekly_pct,
                   m["osd_bar_cols"],
                   hex_to_qcolor(t["accent"]), hex_to_qcolor(t["very_dim"]),
                   body_f)

    # ticker strip — dashed separator + colour-quartile cost tags
    y_tick = y_bar + line_h + 6 * s
    # dashed top rule
    p.setPen(hex_to_qcolor(t["border"]))
    dash_w = 3 * s
    gx = x
    while gx < x + w:
        p.drawLine(QPointF(gx, y_tick), QPointF(gx + dash_w, y_tick))
        gx += dash_w * 2

    ticker_colors = [t["text_dim"], t["text_link"], t["warn"], t["crit"]]
    y_tick_base = y_tick + 4 * s + QFontMetrics(ticker_f).ascent()
    gx = x
    for item in (data.ticker_items or [])[:8]:
        txt = f"${item.cost_usd:.3f} {item.tool_label}"
        adv = draw_text(p, gx, y_tick_base, txt,
                        hex_to_qcolor(ticker_colors[item.tier]), ticker_f)
        gx += adv + 10 * s
        if gx > x + w:
            break
