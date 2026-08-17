**What & why**

<!-- One fix or feature per PR. What does it change, and why? -->

**Checklist**

- [ ] `QT_QPA_PLATFORM=offscreen python -m pytest -q` passes
- [ ] New behavior has a test (bug fixes: a regression test that fails before the fix)
- [ ] No new runtime dependencies (PySide6-Essentials + certifi + stdlib only)
- [ ] If it draws on the OSD or adds a toggle: verified in all 11 themes (5 classics + 6 skins) — the skins have their own paint path, so a toggle that only works in the built-in themes is a bug (#25)
- [ ] Ran the widget manually
