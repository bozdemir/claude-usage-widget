# Claude Usage Widget — Design Handoff for PyQt6

6 visual directions, each ready to drop into the existing `claude_usage/`
codebase (`overlay.py` + `widget.py` paint paths).

Every direction module exposes:

- a **`THEME` dict** — the same shape as `claude_usage/themes.py` entries
  (`bg`, `bar_blue`, `bar_track`, `text_primary`, `text_secondary`,
  `text_dim`, `separator`, `warn`, `crit`, `live_indicator`) plus a few
  direction-specific keys (accent, rule, paper, etc.).
- **`METRICS` dict** — pixel-level sizing: padding, gaps, bar heights,
  radii, section spacing. All values are at `scale=1.0`; multiply by the
  current OSD scale factor (or popup DPR) at paint time.
- **`FONTS` dict** — font family + weight + point size for each role:
  `title`, `section`, `metric`, `label`, `mono_num`, `ticker`.
- **`paint_osd(p, rect, data, scale, theme, fonts)`** — draws the OSD
  into the given QPainter.
- **`paint_popup_header(p, rect, ...)`** + **`paint_popup_section(...)`**
  — helpers used by the popup QWidget’s `paintEvent`.

Every paint function uses ONLY primitives that already exist in the
widget: `fillRect`, `drawRoundedRect`, `drawRect`, `drawText`, `drawArc`,
`drawLine`. No gradients, no blur, no pixmaps. Alpha is set on the
`QColor(r, g, b, a)` you pass to `setBrush`/`setPen` — not as a
separate layer.

## File map

    handoff/
      directions/
        d1_terminal.py
        d2_dashboard.py
        d3_hud.py
        d4_receipt.py
        d5_strip.py
        d6_brutalist.py
      _paint.py             # shared QPainter helpers (bars, rings, heatmaps)
      _popup.py             # shared popup blocks (sections, kpis, lists)
      _popup_generic.py     # generic popup layout — most directions delegate here
      popup_data.py         # PopupData dataclass + adapter reference
      README.md
      CLAUDE_CODE_PROMPT.md

## OSD vs Popup

Every direction exposes TWO entrypoints:

  - `paint_osd(p, rect, data, scale)` — compact surface (≤ 200px tall).
    Consumes the existing `UsageStats` shape. Drop-in replacement for
    the current overlay paint path.

  - `paint_popup(p, rect, data, scale)` — the detail popup. Consumes a
    richer `PopupData` (see `popup_data.py`). Directions delegate most
    of the layout to `_popup_generic.paint_popup` and only override the
    section-header style / bar style / masthead style.

  Exception: `d1_terminal` has a fully custom popup (box-drawing banner,
  [NN] section markers, mono everywhere) that does NOT use the generic
  painter. Read that file for the full reference implementation.

## Wiring into the existing codebase

Minimum changes to `claude_usage/themes.py`:

```python
from handoff.directions import d1_terminal, d2_dashboard, d3_hud
from handoff.directions import d4_receipt, d5_strip, d6_brutalist

THEMES.update({
    "terminal":  d1_terminal.THEME,
    "dashboard": d2_dashboard.THEME,
    "hud":       d3_hud.THEME,
    "receipt":   d4_receipt.THEME,
    "strip":     d5_strip.THEME,
    "brutalist": d6_brutalist.THEME,
})
```

In `overlay.py`, branch the paint path on the active theme's `style`
key (add `"style": "terminal"` etc. to each THEME dict):

```python
style = self._theme.get("style", "default")
if style == "terminal":
    d1_terminal.paint_osd(p, self.rect(), stats, scale, self._theme, FONTS)
elif style == "dashboard":
    d2_dashboard.paint_osd(...)
...
else:
    self._paint_osd_default(p)   # existing code path
```

Do the same in `widget.py`'s popup `paintEvent` — each direction exposes
a `paint_popup(p, rect, data, scale, theme, fonts)` function that
renders the full popup.

## Key implementation notes (the nuances the screenshots miss)

- **All letter-spacing is real kerning**. Use
  `font.setLetterSpacing(QFont.AbsoluteSpacing, px * scale)`.
- **ASCII bars** (direction 1) are drawn as characters, not rects. This
  matters because the `█` glyph width depends on the font — use
  `QFontMetrics.horizontalAdvance("█")` to measure, don't assume.
- **Ring gauges** (direction 3) use 270° sweep, starting at `-225°`
  (Qt angles are 1/16 degree → pass `-225 * 16`). The needle is just
  the arc's end — no separate stroke.
- **Receipt grain** (direction 4) — paint a 1-px semi-transparent
  horizontal line every 3 px across the full paper area, `alpha=6`.
  Looks like thermal paper texture without any image asset.
- **Brutalist rules** (direction 6) are `drawLine` at full `text_primary`
  color, 2 px wide for major section breaks, 1 px for minor.
- **Heatmap alpha ramp** uses a single base color with `alpha = 40 + v*215`
  where `v` is 0..1. No gradient.
- **Ticker colors** already come quartile-bucketed from `ticker.py` —
  direction modules just remap the 4 tiers to their own palette.

Each direction file is self-contained and ~200-300 lines; open them
one by one and read the docstring at the top for per-direction quirks.
