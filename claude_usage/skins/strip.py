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
    '_mono_family'    : 'JetBrains Mono',
    '_ui_family'      : 'Inter',
    'paper'           : '#0e1012',
    'accent2'         : '#4db79a',
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
    "osd_width": 480, "osd_height": 54, "osd_height_scoped": 108,
    "osd_radius": 8, "osd_padding": 0,
    "seg_title_w": 96, "seg_live_w": 96,
    "bar_h": 3,
    # Two extra stacked rows (Codex 5h + Codex 7d), each the same footprint
    # the scoped row already claims: 2 × (osd_height_scoped - osd_height).
    "codex_rows_height": 108,
}

FONTS = {"family_mono": "JetBrains Mono", "family_ui": "Inter",
         "label_pt": 9, "body_pt": 11}


def paint_osd(p: QPainter, rect: QRectF, data, scale: float = 1.0) -> None:
    """Strip OSD: dense single-row layout — title segment + session segment
    + weekly segment + live segment, separated by vertical rules."""
    s = scale; t = THEME; m = METRICS

    # First-row height stays fixed even when the window grows to make room
    # for the optional scoped third row, so row 1 is pixel-identical whether
    # or not a scoped cap is present. When no scoped cap exists the overlay
    # sizes the rect to osd_height, so base_h == rect.height() here.
    base_h = m["osd_height"] * s
    base_bottom = rect.y() + base_h

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
    p.drawEllipse(QPointF(x0 + 16 * s, rect.y() + base_h / 2), 4 * s, 4 * s)
    draw_text(p, x0 + 28 * s, rect.y() + base_h / 2 + fm.ascent() / 2 - 2,
              "CLAUDE", hex_to_qcolor(t["text_secondary"]), label_f,
              letter_spacing_px=2 * s)
    # rule
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(x0 + title_w, rect.y() + 4 * s),
               QPointF(x0 + title_w, base_bottom - 4 * s))

    # generic segment painter
    def seg(x: float, w: float, label: str, pct: float, suffix: str,
            fill_hex: str, top: float | None = None, bh: float | None = None):
        # A single Session/Weekly-style band. ``top``/``bh`` default to the
        # first strip row; the scoped row passes the band directly below it so
        # its internal rhythm (label at the top, hairline bar at the bottom)
        # matches the weekly row exactly.
        if top is None:
            top = rect.y()
        if bh is None:
            bh = base_h
        # label top
        draw_text(p, x + 12 * s, top + 14 * s + fm.ascent() / 2,
                  label, hex_to_qcolor(t["text_dim"]), label_f,
                  letter_spacing_px=1.5 * s)
        # % + suffix right
        pct_txt = f"{int(pct * 100)}%"
        adv = QFontMetrics(body_f).horizontalAdvance(pct_txt)
        suf_w = fm.horizontalAdvance(suffix)
        draw_text(p, x + w - 12 * s - suf_w - 6 * s - adv,
                  top + 14 * s + fm.ascent() / 2,
                  pct_txt, hex_to_qcolor(t["text_primary"]), body_f)
        draw_text(p, x + w - 12 * s - suf_w,
                  top + 14 * s + fm.ascent() / 2,
                  suffix, hex_to_qcolor(t["text_dim"]), label_f)
        # bar
        bar_y = top + bh - 14 * s
        draw_block_bar(p, x + 12 * s, bar_y, w - 24 * s, m["bar_h"] * s,
                       pct, hex_to_qcolor(t["very_dim"]),
                       hex_to_qcolor(fill_hex), radius=1.5 * s)

    # session seg
    xs = x0 + title_w
    seg(xs, mid_w, "SESSION", data.session_pct,
        f"{data.session_reset_min}m", t["accent"])
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(xs + mid_w, rect.y() + 4 * s),
               QPointF(xs + mid_w, base_bottom - 4 * s))

    # weekly seg
    xw = xs + mid_w
    seg(xw, mid_w, "WEEKLY", data.weekly_pct,
        f"{data.weekly_reset_hrs}h", t["accent2"])
    p.setPen(hex_to_qcolor(t["border"]))
    p.drawLine(QPointF(xw + mid_w, rect.y() + 4 * s),
               QPointF(xw + mid_w, base_bottom - 4 * s))

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

    # scoped weekly seg (e.g. "Fable") — optional third row below weekly.
    # Only drawn when the API reported a model-scoped cap; the label guard
    # is belt-and-suspenders so a stray pct never yields an unlabelled band.
    scoped_pct = getattr(data, "scoped_pct", None)
    if scoped_pct is not None and getattr(data, "scoped_label", ""):
        # horizontal rule separating the first strip row from the scoped row,
        # echoing the 1px vertical segment rules (border colour, 4px inset).
        p.setPen(hex_to_qcolor(t["border"]))
        p.drawLine(QPointF(rect.x() + 4 * s, base_bottom),
                   QPointF(rect.right() - 4 * s, base_bottom))
        # Spans the session+weekly columns so the bar sits directly beneath
        # the weekly bar, rendered with the same seg() painter, fonts and
        # weekly accent (accent2). Reset mirrors weekly's "{hrs}h" format.
        seg(xs, mid_w * 2, data.scoped_label.upper(), scoped_pct,
            f"{data.scoped_reset_hrs}h", t["accent2"],
            top=base_bottom, bh=base_h)

    # optional Codex second-provider rows — two stacked bands mirroring the
    # SESSION (5h) and WEEKLY (7d) rows in this skin's style. Drawn AFTER the
    # scoped row so the running vertical cursor flows Session → Weekly →
    # [scoped] → Codex 5h → Codex 7d. Nothing is painted when the provider
    # is absent, keeping the byte-identical default intact.
    if getattr(data, "codex_available", False):
        # start below the first strip row, plus the scoped row if it drew one
        codex_top = base_bottom
        if scoped_pct is not None and getattr(data, "scoped_label", ""):
            codex_top = base_bottom + base_h
        # Codex 5h — mirrors SESSION (accent, "{min}m" reset)
        p.setPen(hex_to_qcolor(t["border"]))
        p.drawLine(QPointF(rect.x() + 4 * s, codex_top),
                   QPointF(rect.right() - 4 * s, codex_top))
        seg(xs, mid_w * 2, "CODEX 5H", data.codex_session_pct,
            f"{data.codex_session_reset_min}m", t["accent"],
            top=codex_top, bh=base_h)
        # Codex 7d — mirrors WEEKLY (accent2, "{hrs}h" reset)
        codex_top += base_h
        p.setPen(hex_to_qcolor(t["border"]))
        p.drawLine(QPointF(rect.x() + 4 * s, codex_top),
                   QPointF(rect.right() - 4 * s, codex_top))
        seg(xs, mid_w * 2, "CODEX 7D", data.codex_weekly_pct,
            f"{data.codex_weekly_reset_hrs}h", t["accent2"],
            top=codex_top, bh=base_h)


# ---- POPUP ---------------------------------------------------------

def paint_popup(p, rect, data, scale: float = 1.0) -> float:
    """Strip popup: DENSE multi-column layout.

    The strip direction's strength is compactness, so its popup echoes
    that — smaller KPI tiles in a 2-column grid instead of the tall
    stacked layout the generic painter produces.

    For now we delegate to the generic painter; Claude Code can
    implement the dense 2-column version as a v2 once the generic one
    is running cleanly.
    """
    from . import _popup_generic
    return _popup_generic.paint_popup(p, rect, data, scale, THEME,
                                      section_style="default",
                                      bar_style="block",
                                      masthead_style="default")


def measure_popup(data, scale: float = 1.0) -> int:
    from ._popup import dry_measure
    return dry_measure(paint_popup, data, scale, METRICS.get("popup_width", 540)) + int(20 * scale)


def paint_loading(p, rect, phase: float = 0.0, scale: float = 1.0) -> None:
    from ._popup import paint_loading as _pl
    _pl(p, rect, THEME, scale, style="default", phase=phase)
