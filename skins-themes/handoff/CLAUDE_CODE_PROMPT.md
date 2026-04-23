# Claude Code prompt — wiring the design handoff

Paste this prompt into Claude Code, with the `handoff/` folder placed
next to `claude_usage/` in the repo root.

---

I've added a `handoff/` folder with 6 visual directions for the OSD +
detail popup, each implemented as a PyQt6 paint module. I want to:

1. Register the 6 new themes in `claude_usage/themes.py` so
   `config.json` can set `"theme": "terminal"` (or dashboard/hud/
   receipt/strip/brutalist). Each direction's `THEME` dict has the same
   shape as the existing themes plus a `"style"` key and font-family
   meta keys `_mono_family` / `_ui_family`.

2. Extend `overlay.py`'s paint path. At the top of `paintEvent`, branch
   on `self._theme.get("style")`. When it's one of the 6 new styles,
   call the direction's `paint_osd(painter, self.rect(), stats, scale)`
   and return. Otherwise fall through to the existing default path.

3. **Popup (`widget.py`)** — the detail popup uses a different,
   richer data shape. See `handoff/popup_data.py` for the `PopupData`
   dataclass. Extend the collector so it produces:
     - `spark_5h`: list[float], 60 values (5-minute buckets)
     - `spark_7d`: list[float], 7 values
     - `heat_52w`: list[float], 364 values (0..1)
     - `heat_90d`: list[float], 90 values (0..1)
     - `cost_today_usd`, `cache_saved_usd`, `cost_rows` (list of CostRow)
     - `top_projects` (list of ProjectRow), `tips` (list[str]),
       `weekly_report` (str), `plan`, `weekly_reset_label`,
       `session_forecast`.
   In the popup widget's `paintEvent`:

       style = self._theme.get("style")
       data = popup_data.adapt_from_usage_stats(stats, extras)
       if style == "terminal":
           d1_terminal.paint_popup(p, self.rect(), data, scale)
       elif style == "dashboard":
           d2_dashboard.paint_popup(p, self.rect(), data, scale)
       ...

   Every direction ships a working `paint_popup` — d1_terminal has a
   fully custom implementation, the other 5 delegate to
   `_popup_generic.paint_popup` with different `section_style`,
   `bar_style`, and `masthead_style` parameters. Read each direction's
   docstring to see which nuances matter for that style.

4. Add the 6 new choices to the "Theme" submenu in `overlay.py` context
   menu so users can cycle through them live.

5. Add tests in `tests/test_themes.py` asserting the new theme names
   resolve correctly and all required keys are present.

Important constraints:
- No new runtime dependencies.
- Only `QPainter` primitives (`drawRect`, `drawRoundedRect`, `drawText`,
  `drawLine`, `drawArc`, `drawEllipse`). No QGraphicsEffect, no
  pixmaps, no stylesheets.
- All dimensions in the direction modules are at `scale=1.0`; multiply
  by the OSD's current scale before drawing.
- Letter-spacing is applied via
  `QFont.setLetterSpacing(QFont.AbsoluteSpacing, px * scale)`.
- `pct` values are 0..1, not percent. Multiply by 100 when formatting
  for display.

Read `handoff/README.md` first, then `handoff/_paint.py` and
`handoff/_popup.py` for the shared helpers, then open each direction
file — every one has a top docstring listing the nuances that are
easy to miss. Follow those precisely; they encode the intent the
screenshots alone can't convey.
