# Contributing

Contributions are welcome — bug reports, fixes, and focused features all help.
The project has merged community PRs for Windows encoding fixes, macOS focus
handling, the Codex provider, statusline-fed rate limits, the single-instance
guard, scroll-zoom range, and native-Wayland dragging, among others.

## Ground rules

- **One fix or feature per PR.** Keep changes focused and easy to review.
- **Keep runtime dependencies minimal.** Just `PySide6-Essentials` (Qt) and
  `certifi` (HTTPS CA bundle) — both pure-pip, no system libraries. Everything
  else uses the Python stdlib and platform-native CLIs (`notify-send`,
  `osascript`). The "one `pip install`, no system libraries" promise is a core
  part of the project's identity — PRs that reintroduce heavier deps
  (PyGObject/GTK/rumps) will be asked to make them optional or drop them.
- **English only** in code, comments, and docs.
- **Match the surrounding style.** No formatter is enforced; keep it consistent
  with nearby code. WHY-comments over WHAT-comments.
- **Run the widget manually** before submitting, and run the tests.

## Dev setup

```bash
git clone https://github.com/bozdemir/claude-usage-widget.git
cd claude-usage-widget
python3 -m venv .venv && source .venv/bin/activate
pip install -e . pytest
claude-usage               # or: python3 main.py
```

An editable install means your edits take effect on the next launch.

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

The suite is fast and headless (Qt painting is exercised via the `offscreen`
platform plugin — CI runs it the same way on Python 3.10–3.12). New behavior
should come with a test; bug fixes should come with a regression test that
fails before the fix.

## Bug reports

Open an [issue](https://github.com/bozdemir/claude-usage-widget/issues) with:

- Your **OS** and version
- **Python version** (`python3 --version`)
- **Widget version** (`claude-usage --version`)
- The **full output** of launching from a terminal (`claude-usage`)
- Clear steps to reproduce

Detailed reports with a root-cause analysis are especially appreciated.

## Releases

Maintainer checklist: [docs/RELEASING.md](docs/RELEASING.md).

## License

By contributing you agree your work is licensed under the project's
[MIT License](LICENSE).
