"""Generic popup painter — drives all 6 directions.

Each direction calls:

    generic.paint_popup(p, rect, data, scale, theme, style="default")

...and overrides only the section-header style and bar style. The actual
layout (masthead / plan limits / calendar / cost / projects / tips /
report) is identical across directions — only the chrome differs.

If a direction wants completely different layout (e.g. the "strip"
direction's multi-column dense layout) it ships its own paint_popup and
ignores this module.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen

from ._paint import (
    draw_block_bar, draw_heatmap_52w, draw_sparkline_bars,
    draw_text, hex_to_qcolor, mono_font, ui_font,
)
from ._popup import (
    POPUP_PADDING, ROW_GAP, SECTION_GAP,
    draw_active_sessions, draw_pct_row, draw_project_list, draw_report_card,
    draw_section_header, draw_sparkline_row,
)


def paint_popup(
    p: QPainter, rect: QRectF, data, scale: float, theme: dict,
    *,
    section_style: str = "default",
    bar_style: str = "block",
    masthead_style: str = "default",   # "default" | "receipt" | "brutalist"
) -> float:
    """Render the shared masthead → sections → footer layout into *rect*.

    Direction modules call this with the variant flags that pick their
    chrome (masthead style, section header style, bar style); the body
    layout is identical across directions. Returns the final y cursor.
    """
    s = scale; t = theme
    pad = POPUP_PADDING * s

    # --- panel background + border --------------------------------
    bg = hex_to_qcolor(t.get("paper", t["bg"]))
    p.setPen(Qt.NoPen); p.setBrush(bg)
    radius = 0 if masthead_style == "brutalist" else 8 * s
    p.drawRoundedRect(rect, radius, radius)
    border_w = 2 * s if masthead_style == "brutalist" else 1
    p.setPen(QPen(hex_to_qcolor(t["border"]), border_w))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(border_w / 2, border_w / 2,
                                    -border_w / 2, -border_w / 2),
                      radius, radius)

    x = rect.x() + pad
    y = rect.y() + pad
    w = rect.width() - pad * 2

    # --- masthead -------------------------------------------------
    if masthead_style == "receipt":
        title_f = mono_font(13 * s, bold=True, family=t["_mono_family"])
        fm = QFontMetrics(title_f)
        title = "* CLAUDE USAGE *"
        tw = fm.horizontalAdvance(title)
        draw_text(p, x + (w - tw) / 2, y + fm.ascent(),
                  title, hex_to_qcolor(t["text_primary"]), title_f,
                  letter_spacing_px=4 * s)
        sub_f = mono_font(9 * s, family=t["_mono_family"])
        fm_s_ = QFontMetrics(sub_f)
        sub = "RCPT #00231 · JUST NOW"
        sw = fm_s_.horizontalAdvance(sub)
        draw_text(p, x + (w - sw) / 2,
                  y + fm.height() + fm_s_.ascent() + 2 * s,
                  sub, hex_to_qcolor(t["text_dim"]), sub_f,
                  letter_spacing_px=2 * s)
        y += fm.height() + fm_s_.height() + 12 * s
        # dashed rule
        pen = QPen(hex_to_qcolor(t.get("rule", t["border"])))
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.drawLine(QPointF(x, y), QPointF(x + w, y))
        y += 10 * s
    elif masthead_style == "brutalist":
        title_f = mono_font(13 * s, bold=True, family=t["_mono_family"])
        fm = QFontMetrics(title_f)
        draw_text(p, x, y + fm.ascent(),
                  "CLAUDE / USAGE",
                  hex_to_qcolor(t["text_primary"]), title_f,
                  letter_spacing_px=3 * s)
        # live badge if live
        if getattr(data, "is_live", False):
            live = "LIVE"
            sub_f = mono_font(9 * s, family=t["_mono_family"])
            fm_s_ = QFontMetrics(sub_f)
            lw = fm_s_.horizontalAdvance(live) + 8 * s
            badge = QRectF(x + w - lw, y + 2 * s, lw, fm.height() - 2 * s)
            p.setPen(Qt.NoPen); p.setBrush(hex_to_qcolor(t["accent"]))
            p.drawRect(badge)
            draw_text(p, badge.x() + 4 * s,
                      badge.y() + fm_s_.ascent() + 2 * s,
                      live, QColor("#ffffff"), sub_f,
                      letter_spacing_px=2 * s)
        y += fm.height() + 6 * s
        pen = QPen(hex_to_qcolor(t["text_primary"])); pen.setWidthF(2 * s)
        p.setPen(pen)
        p.drawLine(QPointF(x, y), QPointF(x + w, y))
        y += 14 * s
    else:
        # default: label strip + live badge
        title_f = ui_font(11 * s, family=t["_ui_family"])
        fm = QFontMetrics(title_f)
        draw_text(p, x, y + fm.ascent(), "CLAUDE / USAGE",
                  hex_to_qcolor(t["text_dim"]), title_f,
                  letter_spacing_px=3 * s)
        if getattr(data, "is_live", False):
            sub_f = mono_font(9 * s, family=t["_mono_family"])
            fm_s_ = QFontMetrics(sub_f)
            live = f"● LIVE {data.live_tok_per_min:.1f}k t/m"
            lw = fm_s_.horizontalAdvance(live)
            draw_text(p, x + w - lw, y + fm.ascent(), live,
                      hex_to_qcolor(t["live_indicator"]), sub_f)
        y += fm.height() + 8 * s
        p.setPen(hex_to_qcolor(t["border"]))
        p.drawLine(QPointF(x, y), QPointF(x + w, y))
        y += 12 * s

    # --- section 01: plan limits ----------------------------------
    y = draw_section_header(p, x, y, w, 1, "plan limits", t, s,
                            style=section_style)
    y = draw_pct_row(p, x, y, w,
                     f"session · resets in {data.session_reset_min}m",
                     data.session_pct, f"{int(data.session_pct*100)}%",
                     t, s, bar_style=bar_style,
                     fill_hex=t["accent"], ascii_cols=46)
    y = draw_sparkline_row(p, x, y, w, 30 * s, data.spark_5h,
                           "last 5 hours", t, s)
    y += ROW_GAP * s
    y = draw_pct_row(p, x, y, w,
                     f"weekly · resets {data.weekly_reset_label}",
                     data.weekly_pct, f"{int(data.weekly_pct*100)}%",
                     t, s, bar_style=bar_style,
                     fill_hex=t.get("accent2", t["accent"]), ascii_cols=46)
    y = draw_sparkline_row(p, x, y, w, 26 * s, data.spark_7d,
                           "last 7 days", t, s,
                           color_hex=t.get("accent2", t["accent"]))
    y += SECTION_GAP * s

    # --- section 02: calendar -------------------------------------
    y = draw_section_header(p, x, y, w, 2, "calendar", t, s,
                            style=section_style)
    draw_heatmap_52w(p, x, y, data.heat_52w,
                     cell=7 * s, gap=2 * s,
                     track=hex_to_qcolor(t["bar_track"]),
                     fill_hex=t["accent"])
    y += (7 + 2) * 7 * s + 6 * s
    sub_f = ui_font(9 * s, family=t["_ui_family"])
    fm_s_ = QFontMetrics(sub_f)
    draw_text(p, x, y + fm_s_.ascent(), "LAST 52 WEEKS",
              hex_to_qcolor(t["text_dim"]), sub_f, letter_spacing_px=2 * s)
    y += fm_s_.height() + SECTION_GAP * s

    # --- section 03: cost -----------------------------------------
    y = draw_section_header(p, x, y, w, 3, "cost (today)", t, s,
                            style=section_style)
    big_f = mono_font(24 * s, bold=True, family=t["_mono_family"])
    fm_b = QFontMetrics(big_f)
    draw_text(p, x, y + fm_b.ascent(), f"${data.cost_today_usd:.2f}",
              hex_to_qcolor(t["accent"]), big_f)
    right_text = f"{data.plan} · ${data.cache_saved_usd:,.0f} saved by cache"
    rw = fm_s_.horizontalAdvance(right_text)
    draw_text(p, x + w - rw, y + fm_b.ascent() - 2 * s, right_text,
              hex_to_qcolor(t["text_dim"]), sub_f)
    y += fm_b.height() + 10 * s
    mono_f = mono_font(10 * s, family=t["_mono_family"])
    fm_m = QFontMetrics(mono_f)
    draw_text(p, x, y + fm_m.ascent(), data.cost_model,
              hex_to_qcolor(t["text_secondary"]), mono_f)
    y += fm_m.height() + 4 * s
    for row in data.cost_rows:
        left = f"  {row.label:<14} {row.tokens:>12} × {row.rate}"
        right = f"${row.value_usd:.2f}"
        rw = fm_m.horizontalAdvance(right)
        draw_text(p, x, y + fm_m.ascent(), left,
                  hex_to_qcolor(t["text_primary"]), mono_f)
        draw_text(p, x + w - rw, y + fm_m.ascent(), right,
                  hex_to_qcolor(t["text_primary"]), mono_f)
        y += fm_m.height() + 2 * s
    y += SECTION_GAP * s

    # --- section 04: projects -------------------------------------
    y = draw_section_header(p, x, y, w, 4, "top projects", t, s,
                            style=section_style)
    y = draw_project_list(p, x, y, w, data.top_projects, t, s)
    y += SECTION_GAP * s

    # --- section 05: tips -----------------------------------------
    y = draw_section_header(p, x, y, w, 5, "tips", t, s, style=section_style)
    tip_f = ui_font(11 * s, family=t["_ui_family"])
    fm_t = QFontMetrics(tip_f)
    for tip in data.tips:
        draw_text(p, x, y + fm_t.ascent(), "◆",
                  hex_to_qcolor(t["warn"]), tip_f)
        p.setPen(hex_to_qcolor(t["text_primary"])); p.setFont(tip_f)
        tr = QRectF(x + 16 * s, y, w - 16 * s, 1000)
        br = p.fontMetrics().boundingRect(tr.toRect(), Qt.TextWordWrap, tip)
        p.drawText(QRectF(x + 16 * s, y, w - 16 * s, br.height() + 8 * s),
                   Qt.TextWordWrap, tip)
        y += max(fm_t.height(), br.height()) + 6 * s
    y += SECTION_GAP * s

    # --- section 06: weekly report --------------------------------
    y = draw_section_header(p, x, y, w, 6, "your week with claude", t, s,
                            style=section_style)
    y = draw_report_card(p, x, y, w, data.weekly_report, t, s, style="quote")
    y += SECTION_GAP * s

    # --- section 07: active sessions ------------------------------
    y = draw_section_header(p, x, y, w, 7, "active sessions", t, s,
                            style=section_style)
    y = draw_active_sessions(p, x, y, w, data.active_sessions, t, s)
    return y + POPUP_PADDING * s
