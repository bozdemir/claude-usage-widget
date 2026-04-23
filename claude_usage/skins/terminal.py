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

from ._paint import (
    draw_ascii_bar, draw_block_bar, draw_heatmap_52w, draw_sparkline_bars,
    draw_text, draw_ticker_marquee, hex_to_qcolor, mono_font,
)
from ._popup import (
    ROW_GAP, SECTION_GAP,
    draw_kpi_big, draw_pct_row, draw_project_list, draw_report_card,
    draw_section_header, draw_sparkline_row,
)


WANTS_TICKER = True


THEME = {
    "style":          "terminal",
    '_mono_family'    : 'JetBrains Mono',
    '_ui_family'      : 'JetBrains Mono',
    'paper'           : '#0a0f0a',
    'accent2'         : '#87d7d7',
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

    # Scrolling marquee via the shared helper.
    ticker_colors = (t["text_dim"], t["text_link"], t["warn"], t["crit"])
    y_tick_base = y_tick + 4 * s + QFontMetrics(ticker_f).ascent()
    draw_ticker_marquee(
        p, x, y_tick_base, w,
        data.ticker_items, data.ticker_offset,
        ticker_colors, ticker_f, sep_gap_px=10 * s,
    )


# ---- POPUP ---------------------------------------------------------

def measure_popup(data, scale: float = 1.0) -> int:
    """Return total popup height in px for the given data at this scale.
    Used by the QWidget to set its minimum height BEFORE paintEvent."""
    s = scale
    # rough estimate; measured in dev to match draw_popup exactly
    base = 540 * s
    base += 12 * len(data.top_projects) * s
    base += 18 * len(data.tips) * s
    return int(base)


def paint_popup(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    """Terminal-style popup. Uses [NN] section headers and ASCII bars.
    Mimics a terminal readout — dashed rules, box-drawing trim, mono everywhere."""
    s = scale; t = THEME
    pad = 18 * s

    # paper
    p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["bg"]))
    p.drawRoundedRect(rect, 6 * s, 6 * s)
    p.setPen(hex_to_qcolor(t["border"])); p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6 * s, 6 * s)

    x = rect.x() + pad; y = rect.y() + pad
    w = rect.width() - pad * 2

    # masthead — box-drawing banner
    banner_f = mono_font(12 * s, bold=True, family=FONTS["family"])
    fm = QFontMetrics(banner_f)
    banner = "╔═ CLAUDE USAGE " + "═" * 12 + "╗"
    draw_text(p, x, y + fm.ascent(), banner,
              hex_to_qcolor(t["accent"]), banner_f,
              letter_spacing_px=1.5 * s)
    sub_f = mono_font(10 * s, family=FONTS["family"])
    draw_text(p, x, y + fm.height() + QFontMetrics(sub_f).ascent() + 4 * s,
              "last updated: just now · refresh: 30s",
              hex_to_qcolor(t["text_dim"]), sub_f)
    y += fm.height() + QFontMetrics(sub_f).height() + 14 * s

    # [01] plan limits
    y = draw_section_header(p, x, y, w, 1, "plan limits", t, s, style="terminal")
    y = draw_pct_row(p, x, y, w, "session · resets in " + f"{data.session_reset_min}m",
                     data.session_pct, f"{int(data.session_pct * 100)}%".rjust(4),
                     t, s, bar_style="ascii", fill_hex=t["accent"], ascii_cols=46)
    y = draw_sparkline_row(p, x, y, w, 28 * s, data.spark_5h,
                           "last 5 hours", t, s)
    y += ROW_GAP * s
    y = draw_pct_row(p, x, y, w, "weekly · resets " + data.weekly_reset_label,
                     data.weekly_pct, f"{int(data.weekly_pct * 100)}%".rjust(4),
                     t, s, bar_style="ascii", fill_hex=t["accent"], ascii_cols=46)
    y = draw_sparkline_row(p, x, y, w, 24 * s, data.spark_7d,
                           "last 7 days", t, s)
    y += SECTION_GAP * s

    # [02] calendar (52-week heatmap)
    y = draw_section_header(p, x, y, w, 2, "calendar", t, s, style="terminal")
    draw_heatmap_52w(p, x, y, data.heat_52w,
                     cell=7 * s, gap=2 * s,
                     track=hex_to_qcolor(t["very_dim"]),
                     fill_hex=t["accent"])
    y += (7 + 2) * 7 * s + 6 * s
    draw_text(p, x, y + QFontMetrics(sub_f).ascent(),
              "last 52 weeks", hex_to_qcolor(t["text_dim"]), sub_f)
    y += QFontMetrics(sub_f).height() + SECTION_GAP * s

    # [03] cost
    y = draw_section_header(p, x, y, w, 3, "cost (today)", t, s, style="terminal")
    big_f = mono_font(22 * s, bold=True, family=FONTS["family"])
    fm_b = QFontMetrics(big_f)
    cost_txt = f"${data.cost_today_usd:.2f}"
    draw_text(p, x, y + fm_b.ascent(), cost_txt,
              hex_to_qcolor(t["accent"]), big_f)
    sub_text = f"{data.plan} · ${data.cache_saved_usd:,.0f} saved by cache"
    sw = QFontMetrics(sub_f).horizontalAdvance(sub_text)
    draw_text(p, x + w - sw, y + fm_b.ascent(), sub_text,
              hex_to_qcolor(t["text_dim"]), sub_f)
    y += fm_b.height() + 6 * s
    # model + rows
    mono_f = mono_font(10 * s, family=FONTS["family"])
    fm_m = QFontMetrics(mono_f)
    draw_text(p, x, y + fm_m.ascent(), data.cost_model,
              hex_to_qcolor(t["text_secondary"]), mono_f)
    y += fm_m.height() + 2 * s
    for row in data.cost_rows:
        left = f"  {row.label:<12} {row.tokens} × {row.rate}"
        right = f"${row.value_usd:.2f}"
        rw = fm_m.horizontalAdvance(right)
        draw_text(p, x, y + fm_m.ascent(), left,
                  hex_to_qcolor(t["text_primary"]), mono_f)
        draw_text(p, x + w - rw, y + fm_m.ascent(), right,
                  hex_to_qcolor(t["text_primary"]), mono_f)
        y += fm_m.height() + 2 * s
    y += SECTION_GAP * s

    # [04] top projects
    y = draw_section_header(p, x, y, w, 4, "top projects", t, s, style="terminal")
    y = draw_project_list(p, x, y, w, data.top_projects, t, s)
    y += SECTION_GAP * s

    # [05] tips
    y = draw_section_header(p, x, y, w, 5, "tips", t, s, style="terminal")
    tip_f = mono_font(10 * s, family=FONTS["family"])
    fm_t = QFontMetrics(tip_f)
    for tip in data.tips:
        draw_text(p, x, y + fm_t.ascent(), "▸",
                  hex_to_qcolor(t["warn"]), tip_f)
        p.setPen(hex_to_qcolor(t["text_primary"]))
        p.setFont(tip_f)
        tr = QRectF(x + 14 * s, y, w - 14 * s, 1000)
        br = p.fontMetrics().boundingRect(tr.toRect(), Qt.TextWordWrap, tip)
        p.drawText(QRectF(x + 14 * s, y + fm_t.ascent(), w - 14 * s, br.height()),
                   Qt.TextWordWrap, tip)
        y += max(fm_t.height(), br.height()) + 4 * s
    y += SECTION_GAP * s

    # [06] weekly report
    y = draw_section_header(p, x, y, w, 6, "your week", t, s, style="terminal")
    y = draw_report_card(p, x, y, w, data.weekly_report, t, s, style="quote")

    # bottom trim
    y += 10 * s
    trim = "╚" + "═" * 28 + "╝"
    fm_tr = QFontMetrics(sub_f)
    tw = fm_tr.horizontalAdvance(trim)
    draw_text(p, x + (w - tw) / 2, y + fm_tr.ascent(), trim,
              hex_to_qcolor(t["text_dim"]), sub_f)


# Constant used by the popup helpers above (ROW_GAP from _popup.py).
ROW_GAP = 6
