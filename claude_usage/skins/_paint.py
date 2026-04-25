"""Shared painting helpers used by all 6 directions.

Every helper assumes the QPainter has already been set up with antialias:
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen


def hex_to_qcolor(hex_str: str, alpha: float = 1.0) -> QColor:
    """'#rrggbb' or '#rgb' -> QColor with alpha in [0, 1]."""
    c = QColor(hex_str)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def mono_font(size_pt: float, bold: bool = False, family: str = "JetBrains Mono") -> QFont:
    """Build a monospace QFont, falling back to the platform default if the
    requested family isn't installed."""
    f = QFont(family)
    # Fall back to platform mono if family missing.
    f.setStyleHint(QFont.Monospace)
    f.setPointSizeF(size_pt)
    if bold:
        f.setWeight(QFont.Bold)
    return f


def ui_font(size_pt: float, weight: int = QFont.Normal, family: str = "Inter") -> QFont:
    """Build a sans-serif UI QFont with a sensible system fallback."""
    f = QFont(family)
    f.setStyleHint(QFont.SansSerif)
    f.setPointSizeF(size_pt)
    f.setWeight(weight)
    return f


def draw_text(
    p: QPainter,
    x: float,
    y: float,
    text: str,
    color: QColor,
    font: QFont,
    letter_spacing_px: float = 0.0,
) -> float:
    """Draw text at (x, y baseline). Returns advance width so callers can
    chain text runs. ``letter_spacing_px`` is applied via QFont.AbsoluteSpacing."""
    if letter_spacing_px:
        font = QFont(font)  # copy; don't mutate caller's font
        font.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing_px)
    p.setFont(font)
    p.setPen(color)
    p.drawText(QPointF(x, y), text)
    return QFontMetrics(font).horizontalAdvance(text)


def draw_block_bar(
    p: QPainter,
    x: float,
    y: float,
    w: float,
    h: float,
    pct: float,  # 0..1
    track: QColor,
    fill: QColor,
    radius: float = 0.0,
) -> None:
    """Solid-fill horizontal progress bar. Pass ``radius=0`` for a hard
    rectangle (brutalist/receipt) or ``h/2`` for a fully rounded capsule."""
    p.setPen(Qt.NoPen)
    p.setBrush(track)
    if radius:
        p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
    else:
        p.drawRect(QRectF(x, y, w, h))
    if pct > 0:
        fw = max(h if radius else 1.0, w * min(1.0, max(0.0, pct)))
        p.setBrush(fill)
        if radius:
            p.drawRoundedRect(QRectF(x, y, fw, h), radius, radius)
        else:
            p.drawRect(QRectF(x, y, fw, h))


def draw_ascii_bar(
    p: QPainter,
    x: float,
    y_baseline: float,
    pct: float,
    cols: int,
    fill_color: QColor,
    track_color: QColor,
    font: QFont,
) -> float:
    """Draws cols characters of █/░ at the given baseline. Returns advance.
    Each cell is measured via QFontMetrics so the bar visually aligns with
    other monospace text in the same row."""
    p.setFont(font)
    fm = QFontMetrics(font)
    cell_w = fm.horizontalAdvance("█")
    filled = int(round(cols * min(1.0, max(0.0, pct))))
    for i in range(cols):
        ch = "█" if i < filled else "░"
        p.setPen(fill_color if i < filled else track_color)
        p.drawText(QPointF(x + i * cell_w, y_baseline), ch)
    return cell_w * cols


def draw_ring(
    p: QPainter,
    cx: float,
    cy: float,
    radius: float,
    stroke: float,
    pct: float,
    track: QColor,
    fill: QColor,
    start_deg: float = -225.0,
    span_deg: float = 270.0,
) -> None:
    """270° gauge arc. Qt angles are 1/16 degree; passed raw here and
    scaled internally. pct is 0..1."""
    rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

    pen_track = QPen(track)
    pen_track.setWidthF(stroke)
    pen_track.setCapStyle(Qt.RoundCap)
    p.setPen(pen_track)
    p.setBrush(Qt.NoBrush)
    # Qt drawArc: startAngle and spanAngle in 1/16 deg; positive = CCW.
    p.drawArc(rect, int(start_deg * 16), int(span_deg * 16))

    if pct > 0:
        pen_fill = QPen(fill)
        pen_fill.setWidthF(stroke)
        pen_fill.setCapStyle(Qt.RoundCap)
        p.setPen(pen_fill)
        p.drawArc(rect, int(start_deg * 16), int(span_deg * pct * 16))


def draw_heatmap_52w(
    p: QPainter,
    x: float,
    y: float,
    values: list[float],      # length 52*7, each 0..1
    cell: float,
    gap: float,
    track: QColor,
    fill_hex: str,
) -> None:
    """GitHub-style 52×7 grid. Rows = weekdays, cols = weeks."""
    p.setPen(Qt.NoPen)
    for i, v in enumerate(values):
        wi, di = divmod(i, 7)
        cx = x + wi * (cell + gap)
        cy = y + di * (cell + gap)
        if v < 0.05:
            p.setBrush(track)
        else:
            a = 0.2 + 0.8 * v
            c = QColor(fill_hex)
            c.setAlphaF(a)
            p.setBrush(c)
        p.drawRect(QRectF(cx, cy, cell, cell))


def draw_ticker_marquee(
    p: QPainter,
    x: float,
    y_baseline: float,
    clip_w: float,
    items: list,
    offset: float,
    color_hex_by_tier: tuple[str, str, str, str],
    font: QFont,
    sep_gap_px: float = 10.0,
    format_fn=lambda it: f"${it.cost_usd:.3f} {it.tool_label}",
) -> float:
    """Scrolling ticker tape — two end-to-end copies wrapped by ``offset``.

    ``offset`` is pixels scrolled so far (modulo is taken internally), so
    callers can feed a monotonically-increasing value from a QTimer and
    get seamless wrap without ever resetting.

    Returns the total strip width so callers can reason about cadence.
    """
    ordered = list(reversed(items or []))
    if not ordered:
        return 0.0
    fm = QFontMetrics(font)
    strings = [format_fn(it) for it in ordered]
    widths = [fm.horizontalAdvance(s) + sep_gap_px for s in strings]
    strip_w = sum(widths) or 1
    height = fm.height()
    p.save()
    p.setClipRect(QRectF(x, y_baseline - fm.ascent(), clip_w, height + 2))
    cur_off = float(offset) % strip_w
    # Anchor copy 0 at the left edge so the strip is always covered. As
    # `cur_off` grows, the strip slides leftward; copy 1 (positioned at
    # x_start + strip_w) seamlessly takes over once copy 0 has wrapped.
    x_start = x - cur_off
    copies = max(2, int(clip_w // max(strip_w, 1)) + 2)
    for repeat in range(copies):
        gx = x_start + repeat * strip_w
        for (txt, width, it) in zip(strings, widths, ordered):
            if gx + width < x:
                gx += width
                continue
            if gx > x + clip_w:
                break
            draw_text(
                p, gx, y_baseline, txt,
                hex_to_qcolor(color_hex_by_tier[it.tier]), font,
            )
            gx += width
    p.restore()
    return strip_w


def draw_sparkline_bars(
    p: QPainter,
    x: float,
    y: float,
    w: float,
    h: float,
    values: list[float],
    color_hex: str,
    gap: float = 1.0,
    min_bar_h: float = 1.0,
) -> None:
    """Vertical bar sparkline. Each bar's alpha scales with its value."""
    if not values:
        return
    p.setPen(Qt.NoPen)
    mx = max(values) or 1.0
    bw = (w - gap * (len(values) - 1)) / len(values)
    for i, v in enumerate(values):
        bh = max(min_bar_h, (v / mx) * h)
        c = QColor(color_hex)
        c.setAlphaF(0.45 + 0.55 * (v / mx))
        p.setBrush(c)
        p.drawRect(QRectF(x + i * (bw + gap), y + h - bh, bw, bh))
