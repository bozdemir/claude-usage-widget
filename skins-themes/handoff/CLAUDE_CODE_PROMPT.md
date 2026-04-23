# Claude Code prompt — wiring the design handoff

Paste this prompt into Claude Code, with the `handoff/` folder placed
next to `claude_usage/` in the repo root.

---

I've added a `handoff/` folder with 6 visual directions for the OSD +
popup, each implemented as a PyQt6 paint module. I want to:

1. Register the 6 new themes in `claude_usage/themes.py` so
   `config.json` can set `"theme": "terminal"` (or dashboard/hud/
   receipt/strip/brutalist). Each direction's `THEME` dict has the same
   shape as the existing themes plus a `"style"` key.

2. Extend `overlay.py`'s paint path. At the top of `paintEvent`, branch
   on `self._theme.get("style")`. When it's one of the 6 new styles,
   call the direction's `paint_osd(painter, self.rect(), stats, scale)`
   and return. Otherwise fall through to the existing default path.

3. Do the same for the detail popup in `widget.py` (the direction
   modules also expose `paint_popup` where applicable; for directions
   that don't yet have a popup painter, keep the default popup but
   apply the theme colors).

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
- The `data` argument passed to `paint_osd` is the existing `UsageStats`
  shape. Map fields carefully — e.g. `data.session_pct` is 0..1, not
  percent.

Read `handoff/README.md` and `handoff/_paint.py` first; they explain
the shared helpers. Each direction file has a top docstring listing
the nuances that are easy to miss — follow those precisely.
