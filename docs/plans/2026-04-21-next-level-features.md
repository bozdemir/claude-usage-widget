# Next-Level Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Claude Usage Widget from "great OSD widget" to "best-in-class Claude telemetry platform" by adding CLI/API integration, intelligence features, historical trends, and distribution tooling.

**Architecture:** All new features are additive — existing widget, OSD, tray, and popup keep working unchanged. New pure modules (`cli.py`, `api_server.py`, `analytics.py`, `webhooks.py`, `updater.py`) sit next to existing ones. Linux/macOS parity is maintained throughout.

**Tech Stack:** Python 3.10+, stdlib only (`http.server`, `urllib`, `argparse`, `csv`, statistics), GTK3/Cairo on Linux, AppKit/rumps on macOS. No new runtime deps. CI uses GitHub Actions for PyPI publish.

**Baseline:** 170 tests passing, widget running at PID varies. Repository: `bozdemir/claude-usage-widget`.

---

## File Structure

```
claude_usage/
├── cli.py              # NEW — argparse CLI, `--json`, `--field`, `--export`, `--once`, `--daemon`
├── api_server.py       # NEW — localhost HTTP server, /usage /metrics endpoints
├── analytics.py        # NEW — anomaly detection, cost optimization tips
├── trends.py           # NEW — heatmap data, monthly summary, time-of-day aggregation
├── webhooks.py         # NEW — webhook dispatch for threshold/daily/anomaly events
├── updater.py          # NEW — GitHub Releases version check
├── exporter.py         # NEW — CSV/JSON history export
├── collector.py        # MODIFY — wire analytics into UsageStats
├── widget.py           # MODIFY — new popup sections (anomaly, tips, trends)
├── widget_macos.py     # MODIFY — parity with widget.py
├── config.py           # MODIFY — new keys (api_server, webhooks, auto_update)
└── __init__.py         # MODIFY — __version__ string

tests/
├── test_cli.py                  # NEW
├── test_api_server.py           # NEW
├── test_analytics.py            # NEW
├── test_trends.py               # NEW
├── test_webhooks.py             # NEW
├── test_updater.py              # NEW
└── test_exporter.py             # NEW

docs/integrations/
├── zsh-prompt.zsh               # NEW — prompt segment snippet
├── tmux.conf.snippet            # NEW — tmux status bar line
├── waybar-module.json           # NEW — waybar custom module
├── polybar-module.ini           # NEW — polybar exec module
├── starship.toml.snippet        # NEW — starship custom command
└── grafana-dashboard.json       # NEW — Prometheus scrape dashboard

pyproject.toml                   # NEW — PyPI packaging
MANIFEST.in                      # NEW — include non-Python assets
.github/workflows/publish.yml    # NEW — auto-publish on tag
Formula/claude-usage-widget.rb   # NEW — Homebrew formula (separate tap)
```

**Design notes:**
- Every new module is a pure library with its own test file.
- Widget files get display code only; business logic stays in pure modules.
- `config.json` stays backwards compatible — all new keys have sensible defaults.
- No new runtime dependencies. `urllib` over `requests`; `http.server` over Flask.

---

## Task Ordering / Dependencies

```
Foundation       : Task 1 (CLI skeleton + __version__)
Power User       : Task 2 (export) → Task 3 (JSON API server) → Task 4 (shell integrations)
Intelligence     : Task 5 (analytics) → Task 6 (cost tips) → Task 7 (trends) → Task 8 (widget integration)
Distribution     : Task 9 (webhooks) → Task 10 (updater) → Task 11 (PyPI) → Task 12 (Homebrew formula)
```

Each task produces a committable, tested unit. Tasks 1–4 are independent of 5–8. Tasks 9–12 can ship even if intelligence tasks slip.

---

### Task 1: CLI Skeleton + `__version__`

**Files:**
- Create: `claude_usage/cli.py`
- Modify: `claude_usage/__init__.py`
- Modify: `main.py`
- Test: `tests/test_cli.py`

This task adds `python3 main.py --json`, `--field NAME`, `--once`, `--version` flags. GUI is the default when no flag given. Also adds `__version__` so later tasks (updater, PyPI) can reference it.

- [ ] **Step 1: Write failing test for version flag**

```python
# tests/test_cli.py
"""Tests for the CLI argument parser and dispatch."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import asdict
from io import StringIO
from unittest.mock import patch

from claude_usage import __version__
from claude_usage.cli import build_parser, run_cli
from claude_usage.collector import UsageStats


def _fake_stats() -> UsageStats:
    return UsageStats(
        session_utilization=0.58,
        weekly_utilization=0.10,
        today_tokens=1_234_567,
        today_cost=12.34,
    )


class TestBuildParser(unittest.TestCase):
    def test_has_version_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--version"])
        self.assertTrue(ns.version)

    def test_json_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--json"])
        self.assertTrue(ns.json)

    def test_field_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--field", "session_utilization"])
        self.assertEqual(ns.field, "session_utilization")

    def test_once_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--once"])
        self.assertTrue(ns.once)

    def test_no_args_is_gui_mode(self):
        parser = build_parser()
        ns = parser.parse_args([])
        self.assertFalse(ns.json)
        self.assertIsNone(ns.field)


class TestRunCli(unittest.TestCase):
    def test_version_prints_version(self):
        out = StringIO()
        with patch("sys.stdout", out):
            rc = run_cli(["--version"])
        self.assertEqual(rc, 0)
        self.assertIn(__version__, out.getvalue())

    def test_json_emits_valid_json(self):
        out = StringIO()
        with patch("claude_usage.cli.collect_all", return_value=_fake_stats()), \
             patch("sys.stdout", out):
            rc = run_cli(["--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["session_utilization"], 0.58)
        self.assertEqual(data["today_cost"], 12.34)

    def test_field_emits_single_value(self):
        out = StringIO()
        with patch("claude_usage.cli.collect_all", return_value=_fake_stats()), \
             patch("sys.stdout", out):
            rc = run_cli(["--field", "session_utilization"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "0.58")

    def test_unknown_field_returns_error(self):
        err = StringIO()
        with patch("claude_usage.cli.collect_all", return_value=_fake_stats()), \
             patch("sys.stderr", err):
            rc = run_cli(["--field", "bogus_field"])
        self.assertEqual(rc, 2)
        self.assertIn("bogus_field", err.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_usage.cli'`

- [ ] **Step 3: Add `__version__` to package**

Replace `/home/burak/claude-usage-plugin/claude_usage/__init__.py` contents with:

```python
"""Claude Usage Widget — desktop usage tracker for Claude Code."""

__version__ = "0.2.0"
```

- [ ] **Step 4: Create `claude_usage/cli.py`**

```python
"""Command-line interface for headless / scripted access to usage stats.

Exposes:
  --json                Emit the full UsageStats as a JSON document and exit.
  --field NAME          Print a single field value (e.g. "session_utilization")
                        so shell scripts can consume it without parsing JSON.
  --once                Collect once and exit (same as --json but returns the
                        same data format as the UI uses internally).
  --version             Print the package version and exit.
  (no flags)            Launch the GUI (default behaviour — main.py delegates
                        to the GTK / AppKit entry point).

The CLI is pure-Python: no GTK or AppKit imports until the GUI branch is
taken, so it can run inside cron, CI, or minimal containers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Sequence

from claude_usage import __version__
from claude_usage.collector import UsageStats, collect_all
from claude_usage.config import load_config


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser used by the CLI dispatcher."""
    p = argparse.ArgumentParser(
        prog="claude-usage",
        description="Claude Code usage tracker — GUI by default, CLI on demand.",
    )
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    p.add_argument("--json", action="store_true", help="Emit full stats as JSON.")
    p.add_argument("--once", action="store_true", help="Collect once and print JSON.")
    p.add_argument("--field", metavar="NAME", default=None,
                   help="Print a single UsageStats field by name.")
    return p


def _usage_stats_to_dict(stats: UsageStats) -> dict:
    """Convert a UsageStats dataclass to a JSON-serialisable dict."""
    return asdict(stats) if is_dataclass(stats) else dict(stats)


def _default_config_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = os.path.join(base_dir, "config.json")
    if not os.path.isfile(cfg):
        cfg = os.path.join(base_dir, "config.json.example")
    return cfg


def run_cli(argv: Sequence[str]) -> int:
    """Dispatch a single CLI invocation. Returns a process exit code."""
    args = build_parser().parse_args(list(argv))

    if args.version:
        print(__version__)
        return 0

    # --once implies --json output shape
    if args.json or args.once or args.field:
        config = load_config(_default_config_path())
        stats = collect_all(config)
        data = _usage_stats_to_dict(stats)

        if args.field is not None:
            if args.field not in data:
                print(f"error: unknown field {args.field!r}", file=sys.stderr)
                return 2
            print(data[args.field])
            return 0

        json.dump(data, sys.stdout, default=str, indent=2, sort_keys=True)
        print()
        return 0

    # No CLI flag — caller should fall through to GUI.
    return -1


def main() -> int:
    """Entry point for the ``claude-usage`` console script."""
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Route `main.py` through the CLI**

Modify `/home/burak/claude-usage-plugin/main.py` — at the top of `main()`, before platform dispatch, intercept CLI flags:

```python
def main() -> None:
    # CLI flags take precedence over the GUI. run_cli returns -1 when the
    # user did not pass any CLI-specific flag, in which case we fall through
    # to the platform GUI entry point below.
    from claude_usage.cli import run_cli
    rc = run_cli(sys.argv[1:])
    if rc >= 0:
        sys.exit(rc)

    # Restore the default SIGINT handler so Ctrl-C kills the GUI cleanly.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == "darwin":
        _main_macos()
    elif sys.platform.startswith("linux"):
        _main_linux()
    else:
        print(f"ERROR: Unsupported platform: {sys.platform}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_cli.py -v`
Expected: 8 passed

- [ ] **Step 7: Smoke-test the CLI end-to-end**

Run: `cd /home/burak/claude-usage-plugin && python3 main.py --version`
Expected: `0.2.0`

Run: `cd /home/burak/claude-usage-plugin && python3 main.py --field session_utilization`
Expected: a float between 0 and 1

- [ ] **Step 8: Commit**

```bash
cd /home/burak/claude-usage-plugin
git add claude_usage/__init__.py claude_usage/cli.py main.py tests/test_cli.py
git commit -m "feat(cli): add --json, --field, --version, --once flags"
```

---

### Task 2: Data Export (CSV / JSON)

**Files:**
- Create: `claude_usage/exporter.py`
- Modify: `claude_usage/cli.py` (add `--export` flag)
- Test: `tests/test_exporter.py`

`--export csv --days 30 > usage.csv` writes the history.jsonl contents filtered by `--days` as CSV (or JSON). Useful for spreadsheet analysis without parsing JSONL.

- [ ] **Step 1: Write failing tests for export**

```python
# tests/test_exporter.py
"""Tests for CSV / JSON history export."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import time
import unittest

from claude_usage.exporter import export_history


def _write_history(path: str, samples: list[dict]) -> None:
    with open(path, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")


class TestExportHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self.path = self.tmp.name

    def tearDown(self) -> None:
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_export_csv_writes_header_and_rows(self):
        now = time.time()
        _write_history(self.path, [
            {"ts": now, "session": 0.5, "weekly": 0.1},
            {"ts": now - 100, "session": 0.3, "weekly": 0.05},
        ])
        out = io.StringIO()
        count = export_history(self.path, fmt="csv", days=7, out=out, now=now)
        self.assertEqual(count, 2)
        reader = csv.reader(io.StringIO(out.getvalue()))
        rows = list(reader)
        self.assertEqual(rows[0], ["ts", "iso", "session", "weekly"])
        self.assertEqual(len(rows), 3)  # header + 2 rows

    def test_export_json_emits_array(self):
        now = time.time()
        _write_history(self.path, [{"ts": now, "session": 0.1, "weekly": 0.02}])
        out = io.StringIO()
        count = export_history(self.path, fmt="json", days=7, out=out, now=now)
        self.assertEqual(count, 1)
        data = json.loads(out.getvalue())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["session"], 0.1)

    def test_export_filters_by_days(self):
        now = time.time()
        _write_history(self.path, [
            {"ts": now, "session": 0.5, "weekly": 0.1},
            {"ts": now - 8 * 86400, "session": 0.9, "weekly": 0.9},  # 8 days ago
        ])
        out = io.StringIO()
        count = export_history(self.path, fmt="csv", days=7, out=out, now=now)
        self.assertEqual(count, 1)  # the 8-day-old sample is excluded

    def test_export_missing_file_writes_empty(self):
        out = io.StringIO()
        count = export_history("/nonexistent/path.jsonl", fmt="csv", days=7, out=out)
        self.assertEqual(count, 0)
        # Header should still be present for CSV
        self.assertIn("ts,iso,session,weekly", out.getvalue())

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            export_history(self.path, fmt="xml", days=7, out=io.StringIO())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_exporter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_usage.exporter'`

- [ ] **Step 3: Create `claude_usage/exporter.py`**

```python
"""CSV / JSON export of the history.jsonl sample stream.

Pure module — takes a path and a file-like destination.  The CLI wires this
to stdout when ``--export`` is passed; tests supply a StringIO so they never
touch the real filesystem.
"""

from __future__ import annotations

import csv
import json
import os
import time as _time
from datetime import datetime
from typing import IO


CSV_HEADER = ["ts", "iso", "session", "weekly"]


def _iter_samples(path: str, cutoff_ts: float):
    """Yield JSON-decoded samples from *path* with ts >= cutoff_ts."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("ts", 0) >= cutoff_ts:
                yield entry


def export_history(
    path: str,
    fmt: str,
    days: int,
    out: IO[str],
    now: float | None = None,
) -> int:
    """Write the last *days* of history samples to *out* in *fmt*.

    Args:
        path: Path to history.jsonl.
        fmt: "csv" or "json".
        days: Look-back window (sample kept if ts >= now - days*86400).
        out: Text-mode writable (e.g. sys.stdout or StringIO).
        now: Unix timestamp used as the upper bound.  Defaults to time.time().

    Returns:
        Number of samples written.

    Raises:
        ValueError: If fmt is not "csv" or "json".
    """
    if fmt not in ("csv", "json"):
        raise ValueError(f"Unknown export format: {fmt!r}")

    if now is None:
        now = _time.time()
    cutoff = now - days * 86400

    if fmt == "csv":
        writer = csv.writer(out)
        writer.writerow(CSV_HEADER)
        count = 0
        for s in _iter_samples(path, cutoff):
            ts = float(s.get("ts", 0))
            writer.writerow([
                ts,
                datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
                float(s.get("session", 0.0)),
                float(s.get("weekly", 0.0)),
            ])
            count += 1
        return count

    # JSON array
    samples = list(_iter_samples(path, cutoff))
    json.dump(samples, out, indent=2)
    out.write("\n")
    return len(samples)
```

- [ ] **Step 4: Wire `--export` into the CLI**

Modify `/home/burak/claude-usage-plugin/claude_usage/cli.py` — add two new arguments and one new branch in `run_cli`:

Inside `build_parser()`, add after `--field`:

```python
    p.add_argument("--export", choices=("csv", "json"), default=None,
                   help="Export history as CSV or JSON to stdout.")
    p.add_argument("--days", type=int, default=30,
                   help="Look-back window for --export (default: 30).")
```

Inside `run_cli()`, add after the `--version` branch and before the `--json/--once/--field` branch:

```python
    if args.export:
        from claude_usage.exporter import export_history
        config = load_config(_default_config_path())
        history_path = os.path.join(config["claude_dir"], "usage-history.jsonl")
        count = export_history(history_path, fmt=args.export, days=args.days, out=sys.stdout)
        print(f"# exported {count} samples", file=sys.stderr)
        return 0
```

- [ ] **Step 5: Run export test suite**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_exporter.py tests/test_cli.py -v`
Expected: all pass (test_exporter: 5 tests, test_cli: 8 tests)

- [ ] **Step 6: Smoke-test end-to-end**

Run: `cd /home/burak/claude-usage-plugin && python3 main.py --export csv --days 7 | head -3`
Expected: a CSV header line plus up to 2 sample rows.

- [ ] **Step 7: Commit**

```bash
git add claude_usage/exporter.py claude_usage/cli.py tests/test_exporter.py
git commit -m "feat(export): CSV/JSON history export via --export flag"
```

---

### Task 3: Localhost JSON API Server

**Files:**
- Create: `claude_usage/api_server.py`
- Modify: `claude_usage/config.py` (new default keys)
- Modify: `claude_usage/widget.py` (start server on init)
- Modify: `claude_usage/widget_macos.py` (start server on init)
- Test: `tests/test_api_server.py`

Starts a background `http.server` on `localhost:8765` (configurable) exposing `/usage` (JSON) and `/healthz`. Only binds to `127.0.0.1`, no external access. Optional — disabled by default.

- [ ] **Step 1: Write failing tests for api_server**

```python
# tests/test_api_server.py
"""Tests for the localhost JSON usage API server."""

from __future__ import annotations

import json
import time
import unittest
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import MagicMock

from claude_usage.api_server import UsageAPIServer
from claude_usage.collector import UsageStats


def _get(url: str, timeout: float = 1.0) -> tuple[int, dict | str]:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class TestUsageAPIServer(unittest.TestCase):
    def setUp(self) -> None:
        self.get_stats = MagicMock(return_value=UsageStats(
            session_utilization=0.58, weekly_utilization=0.10,
            today_cost=42.0,
        ))
        # Port 0 asks the kernel for a free ephemeral port
        self.server = UsageAPIServer(
            host="127.0.0.1", port=0, get_stats=self.get_stats,
        )
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self) -> None:
        self.server.stop()

    def test_healthz_returns_200(self):
        status, body = _get(self.base + "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("ok"), True)

    def test_usage_returns_stats_as_json(self):
        status, body = _get(self.base + "/usage")
        self.assertEqual(status, 200)
        self.assertEqual(body["session_utilization"], 0.58)
        self.assertEqual(body["today_cost"], 42.0)

    def test_unknown_path_404s(self):
        status, _ = _get(self.base + "/does-not-exist")
        self.assertEqual(status, 404)

    def test_only_binds_localhost(self):
        # The `host` attribute should always be a loopback address
        self.assertIn(self.server.host, ("127.0.0.1", "localhost"))

    def test_get_stats_callable_invoked_on_request(self):
        _get(self.base + "/usage")
        self.assertTrue(self.get_stats.called)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_api_server.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `claude_usage/api_server.py`**

```python
"""Localhost-only JSON HTTP server exposing UsageStats.

Runs on a background thread so the GTK / rumps main loop is never blocked.
Binds only to 127.0.0.1 by default; callers must explicitly opt into a
non-loopback address via config (and then understand the auth implications).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from claude_usage.collector import UsageStats


class UsageAPIServer:
    """Background HTTP server exposing /usage and /healthz.

    Parameters
    ----------
    host:
        Bind address.  Must be a loopback address unless the caller is
        deliberately exposing the endpoint.
    port:
        TCP port.  Use 0 to let the OS pick a free ephemeral port (read back
        via ``self.port`` after ``start()``).
    get_stats:
        Callable returning the current ``UsageStats`` snapshot.  Invoked on
        every ``/usage`` request so responses are always live.
    """

    def __init__(
        self,
        host: str,
        port: int,
        get_stats: Callable[[], UsageStats],
    ) -> None:
        self.host = host
        self._requested_port = port
        self._get_stats = get_stats
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self._requested_port
        return self._server.server_address[1]

    def start(self) -> None:
        """Bind the socket and start the background serving thread."""
        handler_cls = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self._requested_port), handler_cls)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="usage-api", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Shut down the server and wait for its thread to exit."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        get_stats = self._get_stats

        class Handler(BaseHTTPRequestHandler):
            # Silence the default request logging.
            def log_message(self, fmt, *args) -> None:  # noqa: N802
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/healthz":
                    self._send_json({"ok": True})
                    return
                if self.path == "/usage":
                    stats = get_stats()
                    data = asdict(stats) if is_dataclass(stats) else dict(stats)
                    self._send_json(data)
                    return
                self.send_error(404, "Not Found")

            def _send_json(self, payload: dict) -> None:
                body = json.dumps(payload, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        return Handler
```

- [ ] **Step 4: Add config defaults**

Modify `/home/burak/claude-usage-plugin/claude_usage/config.py` — inside `DEFAULT_CONFIG` dict, add three entries before the closing brace:

```python
    # --- Localhost JSON API server (opt-in) ---
    # Exposes UsageStats as JSON on http://127.0.0.1:<port>/usage so shell
    # integrations (tmux, polybar, waybar, custom scripts) can poll without
    # spawning a Python process each time.  Disabled by default; set
    # api_server_enabled=true to turn on.
    "api_server_enabled": False,
    "api_server_host": "127.0.0.1",
    "api_server_port": 8765,
```

- [ ] **Step 5: Start the server from the Linux widget**

Modify `/home/burak/claude-usage-plugin/claude_usage/widget.py` — inside `ClaudeUsageTray.__init__`, after `self.overlay = UsageOverlay(config)`, add:

```python
        # Optional: start localhost JSON API server for shell integrations.
        self._api_server = None
        if config.get("api_server_enabled"):
            from claude_usage.api_server import UsageAPIServer
            self._api_server = UsageAPIServer(
                host=config.get("api_server_host", "127.0.0.1"),
                port=int(config.get("api_server_port", 8765)),
                get_stats=lambda: self.stats,
            )
            self._api_server.start()
```

And inside `ClaudeUsageTray._on_quit`, before `Gtk.main_quit()`, add:

```python
        if self._api_server is not None:
            self._api_server.stop()
```

- [ ] **Step 6: Mirror the change in widget_macos.py**

Modify `/home/burak/claude-usage-plugin/claude_usage/widget_macos.py` — find the `ClaudeUsageTray.__init__` method.  After `self.overlay = UsageOverlay(config)`, add the same `self._api_server = ...` block (identical code; the macOS tray uses the same attribute name).

Inside `ClaudeUsageTray._on_quit`, before `rumps.quit_application()`, add:

```python
        if getattr(self, "_api_server", None) is not None:
            self._api_server.stop()
```

- [ ] **Step 7: Run the test suite**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_api_server.py -v`
Expected: 5 passed

- [ ] **Step 8: Smoke-test live (optional)**

Edit `config.json` (or `config.json.example`) to set `"api_server_enabled": true`.  Restart the widget, then:

```bash
curl -s http://127.0.0.1:8765/healthz
curl -s http://127.0.0.1:8765/usage | python3 -m json.tool | head
```

- [ ] **Step 9: Commit**

```bash
git add claude_usage/api_server.py claude_usage/config.py claude_usage/widget.py claude_usage/widget_macos.py tests/test_api_server.py
git commit -m "feat(api): localhost JSON API server on port 8765"
```

---

### Task 4: Shell Integration Templates

**Files:**
- Create: `docs/integrations/zsh-prompt.zsh`
- Create: `docs/integrations/tmux.conf.snippet`
- Create: `docs/integrations/waybar-module.json`
- Create: `docs/integrations/polybar-module.ini`
- Create: `docs/integrations/starship.toml.snippet`
- Create: `docs/integrations/README.md`

These are plain-text templates — no code or tests.  They rely on the CLI (`claude-usage --field …`) or API server (`curl localhost:8765/usage`) from Tasks 1 and 3.

- [ ] **Step 1: Create `docs/integrations/README.md`**

```markdown
# Shell and Status-Bar Integrations

These snippets pull live usage data from either the CLI (Task 1) or the
localhost JSON API (Task 3).  Pick whichever suits your environment:

| Integration | Backend | Refresh cadence |
|-------------|---------|-----------------|
| zsh prompt  | CLI     | on every prompt |
| tmux        | CLI     | 15 s (tmux refresh) |
| waybar      | CLI     | 30 s (waybar interval) |
| polybar     | CLI     | 30 s |
| starship    | CLI     | on every prompt |

The JSON API is used by anything that can do an HTTP GET (Grafana scrape,
Home Assistant, etc.).
```

- [ ] **Step 2: Create `docs/integrations/zsh-prompt.zsh`**

```zsh
# Drop this into ~/.zshrc.  Adds a right-prompt segment showing session usage.
# Requires claude-usage to be on PATH (see README for install options).

_claude_usage_rprompt() {
  # Fast exit if the CLI isn't available.
  command -v claude-usage >/dev/null 2>&1 || return

  local pct
  pct=$(claude-usage --field session_utilization 2>/dev/null) || return
  [[ -z "$pct" ]] && return

  # Multiply by 100 with awk; zsh arithmetic can't handle floats portably.
  local pct_int
  pct_int=$(awk -v p="$pct" 'BEGIN { printf "%d", p * 100 }')

  # Colour-code: green <60, yellow 60-85, red >85.
  if   (( pct_int < 60 )); then echo "%F{green}C:${pct_int}%%%f"
  elif (( pct_int < 85 )); then echo "%F{yellow}C:${pct_int}%%%f"
  else                          echo "%F{red}C:${pct_int}%%%f"
  fi
}

# Wire the function into the right prompt.  Recomputed on every prompt.
setopt PROMPT_SUBST
RPROMPT='$(_claude_usage_rprompt)'
```

- [ ] **Step 3: Create `docs/integrations/tmux.conf.snippet`**

```
# Append to ~/.tmux.conf and reload with `tmux source-file ~/.tmux.conf`.
# Requires claude-usage on PATH.

set -g status-interval 15
set -g status-right-length 80
set -g status-right '#(claude-usage --field session_utilization | awk "{printf \"C:%d%%\", \$1*100}") | %H:%M'
```

- [ ] **Step 4: Create `docs/integrations/waybar-module.json`**

```json
{
    "custom/claude": {
        "format": "C:{}",
        "interval": 30,
        "exec": "claude-usage --field session_utilization | awk '{printf \"%d%%\", $1*100}'",
        "tooltip": true,
        "exec-if": "command -v claude-usage"
    }
}
```

Accompanying CSS snippet (users drop this into `~/.config/waybar/style.css`):

```css
#custom-claude {
    padding: 0 10px;
    color: #5B9BD5;
}
```

(Write the CSS as a second file: `docs/integrations/waybar-style.css` with the three-line rule above.)

- [ ] **Step 5: Create `docs/integrations/polybar-module.ini`**

```ini
; Drop into ~/.config/polybar/config.ini and add `claude-usage` to your modules.
[module/claude-usage]
type = custom/script
exec = claude-usage --field session_utilization | awk '{printf "C:%d%%", $1*100}'
interval = 30
format-foreground = #5B9BD5
```

- [ ] **Step 6: Create `docs/integrations/starship.toml.snippet`**

```toml
# Add to ~/.config/starship.toml.

[custom.claude_usage]
command = 'claude-usage --field session_utilization | awk "{printf \"C:%d%%\", \$1*100}"'
when = 'command -v claude-usage'
format = '[$output]($style) '
style = 'bold blue'
```

- [ ] **Step 7: Create the waybar CSS file**

Create `/home/burak/claude-usage-plugin/docs/integrations/waybar-style.css`:

```css
#custom-claude {
    padding: 0 10px;
    color: #5B9BD5;
}
```

- [ ] **Step 8: Commit**

```bash
git add docs/integrations/
git commit -m "docs(integrations): zsh, tmux, waybar, polybar, starship templates"
```

---

### Task 5: Anomaly Detection

**Files:**
- Create: `claude_usage/analytics.py`
- Modify: `claude_usage/collector.py` (populate `UsageStats.anomaly`)
- Test: `tests/test_analytics.py`

Analyses the last 30 days of history samples; if today's usage exceeds the 30-day mean by more than 2 standard deviations, flags it.  Pure function, no I/O.

- [ ] **Step 1: Write failing tests for anomaly detection**

```python
# tests/test_analytics.py
"""Tests for anomaly detection and cost optimisation analysis."""

from __future__ import annotations

import unittest

from claude_usage.analytics import detect_anomaly, AnomalyReport


def _samples(daily_totals: list[float], now_ts: float = 86400 * 30) -> list[dict]:
    """Build one max-per-day history sample from a list of daily session peaks."""
    return [
        {"ts": now_ts - (len(daily_totals) - i) * 86400, "session": v, "weekly": v}
        for i, v in enumerate(daily_totals)
    ]


class TestDetectAnomaly(unittest.TestCase):
    def test_flat_usage_no_anomaly(self):
        hist = _samples([0.5] * 30)
        rep = detect_anomaly(hist, today_usage=0.5)
        self.assertIsInstance(rep, AnomalyReport)
        self.assertFalse(rep.is_anomaly)

    def test_spike_beyond_two_sigma_is_anomaly(self):
        # Mean 0.5, std ~0.05, today 0.9 (8 sigma above).
        hist = _samples([0.45, 0.5, 0.55, 0.5, 0.48, 0.52, 0.5] * 4)
        rep = detect_anomaly(hist, today_usage=0.9)
        self.assertTrue(rep.is_anomaly)
        self.assertGreater(rep.z_score, 2.0)
        self.assertGreater(rep.ratio, 1.0)  # today > baseline

    def test_below_average_not_anomaly(self):
        hist = _samples([0.5] * 30)
        rep = detect_anomaly(hist, today_usage=0.1)
        self.assertFalse(rep.is_anomaly)  # only upward spikes flagged

    def test_too_few_samples_returns_no_anomaly(self):
        hist = _samples([0.5, 0.6])
        rep = detect_anomaly(hist, today_usage=0.95)
        self.assertFalse(rep.is_anomaly)
        self.assertIn("insufficient", rep.reason.lower())

    def test_message_formats_ratio(self):
        hist = _samples([0.5] * 30)
        rep = detect_anomaly(hist, today_usage=1.0)
        self.assertTrue(rep.is_anomaly)
        self.assertIn("2.0x", rep.message)  # 1.0 / 0.5 = 2x


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_analytics.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `claude_usage/analytics.py` with detection**

```python
"""Anomaly detection and cost-optimisation analysis over usage history.

Pure module — no I/O, no GUI, no network.  Given a list of sample dicts from
history.py, produces structured reports the widget can render in the popup.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


MIN_SAMPLES = 7  # Need at least a week of data before we flag anomalies
Z_THRESHOLD = 2.0  # Standard deviations above the mean


@dataclass
class AnomalyReport:
    """Summary of a single-day anomaly check."""

    is_anomaly: bool = False
    today_usage: float = 0.0
    baseline: float = 0.0       # mean of per-day peaks over the window
    std_dev: float = 0.0
    z_score: float = 0.0
    ratio: float = 0.0          # today / baseline
    reason: str = ""            # free-form diagnostic when not flagged
    message: str = ""           # user-facing text when flagged


def _daily_peaks(samples: list[dict], key: str = "session") -> list[float]:
    """Reduce a sample stream into one max value per calendar day."""
    by_day: dict[int, float] = {}
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts <= 0:
            continue
        day = int(ts // 86400)
        val = float(s.get(key, 0))
        if val > by_day.get(day, 0.0):
            by_day[day] = val
    # Iterate in chronological order
    return [by_day[d] for d in sorted(by_day)]


def detect_anomaly(
    samples: list[dict],
    today_usage: float,
    key: str = "session",
) -> AnomalyReport:
    """Return an :class:`AnomalyReport` for ``today_usage`` against history.

    ``samples`` is the history.py sample list (``{ts, session, weekly}`` dicts).
    ``key`` selects which field to baseline against.
    """
    rep = AnomalyReport(today_usage=today_usage)

    peaks = _daily_peaks(samples, key=key)
    # Exclude today (last entry) from the baseline calculation
    history = peaks[:-1] if peaks else []

    if len(history) < MIN_SAMPLES:
        rep.reason = f"insufficient history ({len(history)} days < {MIN_SAMPLES})"
        return rep

    rep.baseline = statistics.fmean(history)
    rep.std_dev = statistics.pstdev(history) if len(history) > 1 else 0.0
    if rep.baseline > 0:
        rep.ratio = today_usage / rep.baseline
    if rep.std_dev > 0:
        rep.z_score = (today_usage - rep.baseline) / rep.std_dev

    # Only flag upward anomalies — low-usage days are not interesting.
    if today_usage > rep.baseline and rep.z_score >= Z_THRESHOLD:
        rep.is_anomaly = True
        rep.message = (
            f"Today is {rep.ratio:.1f}x your {len(history)}-day average — "
            f"{int(today_usage * 100)}% vs {int(rep.baseline * 100)}% typical."
        )
    return rep
```

- [ ] **Step 4: Wire anomaly report into UsageStats**

Modify `/home/burak/claude-usage-plugin/claude_usage/collector.py`:

At the top, add an import:

```python
from claude_usage.analytics import detect_anomaly, AnomalyReport
```

In the `UsageStats` dataclass, add a field (alongside the other optional analytics output):

```python
    anomaly: AnomalyReport = field(default_factory=AnomalyReport)
```

Inside `collect_all`, after `samples = load_samples(history_path, since_ts=...)`, add:

```python
    # Anomaly detection — compares today's session utilization against the
    # per-day peaks over the prior 30 days.
    stats.anomaly = detect_anomaly(samples, today_usage=stats.session_utilization)
```

- [ ] **Step 5: Run the full suite**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/ -q`
Expected: all tests pass (170 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add claude_usage/analytics.py claude_usage/collector.py tests/test_analytics.py
git commit -m "feat(analytics): z-score anomaly detection over daily usage peaks"
```

---

### Task 6: Cost Optimization Tips

**Files:**
- Modify: `claude_usage/analytics.py` (add `generate_tips`)
- Modify: `claude_usage/collector.py` (populate `UsageStats.tips`)
- Modify: `tests/test_analytics.py`

Produces short, actionable strings like "Cache hit rate is 43%; raising to 80% would save ~$120/week".

- [ ] **Step 1: Add failing tests for tip generation**

Append to `/home/burak/claude-usage-plugin/tests/test_analytics.py`:

```python
from claude_usage.analytics import generate_tips


class TestGenerateTips(unittest.TestCase):
    def test_low_cache_hit_rate_generates_tip(self):
        by_model = {
            "claude-opus-4-7": {
                "input": 1_000_000,
                "output": 100_000,
                "cache_read": 500_000,     # 33% hit rate (read / (read+input))
                "cache_creation": 0,
            }
        }
        tips = generate_tips(by_model, week_cost=200.0, cache_savings=10.0)
        # Should produce a cache-related tip
        self.assertTrue(any("cache" in t.lower() for t in tips))

    def test_high_cache_hit_rate_no_cache_tip(self):
        by_model = {
            "claude-opus-4-7": {
                "input": 100_000,
                "output": 50_000,
                "cache_read": 9_000_000,  # 99% hit rate
                "cache_creation": 0,
            }
        }
        tips = generate_tips(by_model, week_cost=50.0, cache_savings=2000.0)
        self.assertFalse(any("cache hit rate" in t.lower() for t in tips))

    def test_opus_heavy_model_mix_suggests_downgrade(self):
        # 90% of output tokens from opus
        by_model = {
            "claude-opus-4-7":  {"input": 0, "output": 9_000_000, "cache_read": 0, "cache_creation": 0},
            "claude-sonnet-4-6": {"input": 0, "output": 1_000_000, "cache_read": 0, "cache_creation": 0},
        }
        tips = generate_tips(by_model, week_cost=400.0, cache_savings=0.0)
        self.assertTrue(any("sonnet" in t.lower() for t in tips))

    def test_empty_input_returns_empty_tips(self):
        self.assertEqual(generate_tips({}, week_cost=0.0, cache_savings=0.0), [])
```

- [ ] **Step 2: Run the test to verify failure**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_analytics.py::TestGenerateTips -v`
Expected: FAIL — `ImportError: cannot import name 'generate_tips'`

- [ ] **Step 3: Implement `generate_tips`**

Append to `/home/burak/claude-usage-plugin/claude_usage/analytics.py`:

```python
# ---------------------------------------------------------------------------
# Cost optimisation tips
# ---------------------------------------------------------------------------

LOW_CACHE_HIT_RATE = 0.60   # below this, suggest improving caching
OPUS_HEAVY_THRESHOLD = 0.80 # above this share of output tokens from opus, suggest sonnet


def _cache_hit_rate(counts: dict) -> float:
    """Return cache_read / (cache_read + input) for one model's counts."""
    cr = float(counts.get("cache_read", 0) or 0)
    in_t = float(counts.get("input", 0) or 0)
    denom = cr + in_t
    return cr / denom if denom > 0 else 0.0


def generate_tips(
    by_model: dict,
    week_cost: float,
    cache_savings: float,
) -> list[str]:
    """Return 0-3 short actionable tips based on the week's usage profile.

    ``by_model`` has the shape ``{model: {"input": N, "output": N, ...}}``
    and matches ``UsageStats.today_by_model_detailed`` / the weekly variant.
    """
    tips: list[str] = []
    if not by_model:
        return tips

    # Total output tokens across all models — used to judge model mix.
    total_output = sum(
        float(c.get("output", 0) or 0) for c in by_model.values()
    )

    # ---- Tip 1: cache hit rate -------------------------------------------------
    # Only compute on models with a non-trivial (>10k) input volume.
    hit_rates = [
        _cache_hit_rate(c) for c in by_model.values()
        if float(c.get("input", 0) or 0) + float(c.get("cache_read", 0) or 0) > 10_000
    ]
    if hit_rates:
        avg_hit = sum(hit_rates) / len(hit_rates)
        if avg_hit < LOW_CACHE_HIT_RATE and week_cost > 0:
            # If raising hit rate from avg_hit to 0.85 saved proportionally more:
            potential = week_cost * (0.85 - avg_hit) * 0.9  # ~90% of theoretical max
            if potential >= 1.0:
                tips.append(
                    f"Cache hit rate is {int(avg_hit * 100)}%. "
                    f"Raising to ~85% could save ~${potential:.0f}/week."
                )

    # ---- Tip 2: model mix ------------------------------------------------------
    if total_output > 100_000:
        opus_output = sum(
            float(c.get("output", 0) or 0)
            for m, c in by_model.items() if "opus" in m
        )
        opus_share = opus_output / total_output if total_output else 0.0
        if opus_share >= OPUS_HEAVY_THRESHOLD and week_cost > 20.0:
            # Rough: shifting half of opus output to sonnet saves (25-15)/25 ≈ 40%
            # of opus output cost.  Estimate opus output cost as ~70% of week_cost.
            potential = week_cost * 0.70 * (opus_share - 0.5) * 0.4
            if potential >= 1.0:
                tips.append(
                    f"Opus handles {int(opus_share * 100)}% of your output. "
                    f"Shifting easy tasks to Sonnet could save ~${potential:.0f}/week."
                )

    # ---- Tip 3: celebrate savings ---------------------------------------------
    if cache_savings > 0 and week_cost > 0 and cache_savings >= week_cost * 2:
        tips.append(
            f"Cache already saves ${cache_savings:.0f}/week — "
            f"{cache_savings / max(week_cost, 1):.1f}x your bill. Keep it up."
        )

    return tips[:3]  # Cap at 3 tips so the popup stays compact
```

- [ ] **Step 4: Wire tips into UsageStats**

Modify `/home/burak/claude-usage-plugin/claude_usage/collector.py`:

In the `UsageStats` dataclass:

```python
    tips: list[str] = field(default_factory=list)
```

Inside `collect_all`, after the anomaly detection line, add:

```python
    from claude_usage.analytics import generate_tips
    stats.tips = generate_tips(
        by_model=stats.today_by_model_detailed,
        week_cost=stats.week_cost,
        cache_savings=stats.cache_savings,
    )
```

- [ ] **Step 5: Run tests**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_analytics.py -v`
Expected: 9 passed (5 anomaly + 4 tips)

- [ ] **Step 6: Commit**

```bash
git add claude_usage/analytics.py claude_usage/collector.py tests/test_analytics.py
git commit -m "feat(analytics): cost optimization tips (cache hit rate, model mix)"
```

---

### Task 7: Historical Trends (Heatmap, Monthly, Hourly)

**Files:**
- Create: `claude_usage/trends.py`
- Modify: `claude_usage/collector.py` (populate trend fields)
- Test: `tests/test_trends.py`

Pure aggregation of history samples into:
- 90-day daily heatmap (list of 90 floats, newest last)
- monthly summary (total tokens / cost per month, last 6 months)
- time-of-day histogram (24 buckets, avg utilization per hour)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_trends.py
"""Tests for trend aggregation (heatmap, monthly, hourly)."""

from __future__ import annotations

import time
import unittest

from claude_usage.trends import (
    daily_heatmap,
    monthly_summary,
    hourly_histogram,
)


def _s(ts: float, session: float = 0.5, weekly: float = 0.1) -> dict:
    return {"ts": ts, "session": session, "weekly": weekly}


class TestDailyHeatmap(unittest.TestCase):
    def test_heatmap_length_is_n_days(self):
        now = 1_000_000.0
        result = daily_heatmap([], now=now, n_days=30)
        self.assertEqual(len(result), 30)
        self.assertTrue(all(v == 0.0 for v in result))

    def test_heatmap_stores_daily_peak(self):
        now = 100 * 86400.0  # some day boundary
        samples = [
            _s(now - 0.5 * 86400, session=0.3),
            _s(now - 0.3 * 86400, session=0.7),  # peak for "today"
            _s(now - 1.5 * 86400, session=0.2),  # yesterday
        ]
        result = daily_heatmap(samples, now=now, n_days=3)
        # Newest last: [day-2, day-1, today]
        self.assertEqual(result[-1], 0.7)
        self.assertEqual(result[-2], 0.2)

    def test_old_samples_ignored(self):
        now = 100 * 86400.0
        samples = [_s(now - 500 * 86400, session=0.9)]
        result = daily_heatmap(samples, now=now, n_days=30)
        self.assertTrue(all(v == 0.0 for v in result))


class TestMonthlySummary(unittest.TestCase):
    def test_empty_samples_returns_empty(self):
        self.assertEqual(monthly_summary([], now=time.time(), n_months=3), [])

    def test_bucket_by_calendar_month(self):
        # two samples in same month
        jan_15 = time.mktime((2026, 1, 15, 12, 0, 0, 0, 0, -1))
        jan_20 = time.mktime((2026, 1, 20, 12, 0, 0, 0, 0, -1))
        feb_10 = time.mktime((2026, 2, 10, 12, 0, 0, 0, 0, -1))
        samples = [
            _s(jan_15, session=0.3),
            _s(jan_20, session=0.5),
            _s(feb_10, session=0.7),
        ]
        result = monthly_summary(samples, now=feb_10, n_months=3)
        # Each entry: {"month": "YYYY-MM", "peak": float, "count": int}
        months = {m["month"]: m for m in result}
        self.assertIn("2026-01", months)
        self.assertEqual(months["2026-01"]["peak"], 0.5)
        self.assertEqual(months["2026-01"]["count"], 2)
        self.assertEqual(months["2026-02"]["peak"], 0.7)
        self.assertEqual(months["2026-02"]["count"], 1)


class TestHourlyHistogram(unittest.TestCase):
    def test_always_24_buckets(self):
        self.assertEqual(len(hourly_histogram([], now=time.time())), 24)

    def test_average_utilization_per_hour(self):
        # Build 3 samples all at the same hour-of-day
        base_day = 100 * 86400.0
        hour_10 = base_day + 10 * 3600
        samples = [
            _s(hour_10, session=0.2),
            _s(hour_10 + 86400, session=0.4),    # next day, same hour
            _s(hour_10 + 2 * 86400, session=0.6),
        ]
        buckets = hourly_histogram(samples, now=hour_10 + 3 * 86400)
        # Hour 10 bucket should be (0.2 + 0.4 + 0.6) / 3 = 0.4
        self.assertAlmostEqual(buckets[10], 0.4, places=5)
        # All other buckets empty
        for i, v in enumerate(buckets):
            if i != 10:
                self.assertEqual(v, 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_trends.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `claude_usage/trends.py`**

```python
"""Long-range trend aggregations over the history.jsonl sample stream.

All functions are pure: they take a sample list (or empty list) and a
reference timestamp, and return primitive Python types.  The widget and CLI
render these into UI / JSON; the logic lives here so unit tests are easy.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def daily_heatmap(
    samples: list[dict],
    now: float,
    n_days: int = 90,
    key: str = "session",
) -> list[float]:
    """Return a fixed-length list of per-day peak utilization values.

    Index 0 is the oldest day, index -1 is today.  Empty days are 0.0.
    """
    if n_days <= 0:
        return []
    today_start = int(now // 86400)
    oldest = today_start - (n_days - 1)
    buckets = [0.0] * n_days
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts <= 0:
            continue
        day = int(ts // 86400)
        if day < oldest or day > today_start:
            continue
        idx = day - oldest
        val = float(s.get(key, 0))
        if val > buckets[idx]:
            buckets[idx] = val
    return buckets


def monthly_summary(
    samples: list[dict],
    now: float,
    n_months: int = 6,
    key: str = "session",
) -> list[dict]:
    """Aggregate samples into the last *n_months* calendar months.

    Each entry: ``{"month": "YYYY-MM", "peak": float, "count": int}``.
    Returned newest last.  Empty months are omitted (vs. heatmap, which
    keeps slots for zero-activity days).
    """
    if n_months <= 0 or not samples:
        return []

    ref = datetime.fromtimestamp(now)
    earliest_year = ref.year
    earliest_month = ref.month - n_months + 1
    while earliest_month <= 0:
        earliest_year -= 1
        earliest_month += 12

    buckets: dict[str, dict] = {}
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts <= 0:
            continue
        dt = datetime.fromtimestamp(ts)
        # Skip samples outside the requested window
        if (dt.year, dt.month) < (earliest_year, earliest_month):
            continue
        if (dt.year, dt.month) > (ref.year, ref.month):
            continue
        label = f"{dt.year:04d}-{dt.month:02d}"
        b = buckets.setdefault(label, {"month": label, "peak": 0.0, "count": 0})
        b["count"] += 1
        val = float(s.get(key, 0))
        if val > b["peak"]:
            b["peak"] = val

    return [buckets[k] for k in sorted(buckets)]


def hourly_histogram(
    samples: list[dict],
    now: float,
    key: str = "session",
) -> list[float]:
    """Return 24-bucket list: average utilization at each hour of day.

    Buckets with no samples in the last 7 days are 0.0.
    """
    cutoff = now - 7 * 86400
    sums = [0.0] * 24
    counts = [0] * 24
    for s in samples:
        ts = float(s.get("ts", 0))
        if ts < cutoff:
            continue
        hour = datetime.fromtimestamp(ts).hour
        sums[hour] += float(s.get(key, 0))
        counts[hour] += 1
    return [
        sums[h] / counts[h] if counts[h] > 0 else 0.0
        for h in range(24)
    ]
```

- [ ] **Step 4: Wire into UsageStats and `collect_all`**

Modify `/home/burak/claude-usage-plugin/claude_usage/collector.py`:

Add fields to `UsageStats`:

```python
    daily_heatmap: list = field(default_factory=list)       # 90-day peaks
    monthly_summary: list = field(default_factory=list)     # last 6 months
    hourly_histogram: list = field(default_factory=list)    # 24 buckets
```

Inside `collect_all`, after the anomaly and tips block, add:

```python
    from claude_usage.trends import daily_heatmap, monthly_summary, hourly_histogram
    stats.daily_heatmap = daily_heatmap(samples, now=now_ts, n_days=90)
    stats.monthly_summary = monthly_summary(samples, now=now_ts, n_months=6)
    stats.hourly_histogram = hourly_histogram(samples, now=now_ts)
```

(`now_ts` is already computed earlier in `collect_all`; if not, add `now_ts = datetime.now().timestamp()`.)

- [ ] **Step 5: Run tests**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_trends.py tests/test_collector.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add claude_usage/trends.py claude_usage/collector.py tests/test_trends.py
git commit -m "feat(trends): 90d heatmap, monthly summary, hourly histogram"
```

---

### Task 8: Widget Integration for Intelligence Features

**Files:**
- Modify: `claude_usage/widget.py` (new popup sections)
- Modify: `claude_usage/widget_macos.py` (same)

Adds three sections to the popup:
- **Anomaly banner** (when `stats.anomaly.is_anomaly` — a single dim line at the top of the Cost section).
- **Tips section** — up to 3 tip strings as dim lines.
- **90-day heatmap** — a Cairo / NSBezierPath rendering of `daily_heatmap` as a 90-cell strip below the weekly sparkline.

No new tests here (the underlying pure modules already cover behaviour); we smoke-test visually.

- [ ] **Step 1: Add anomaly banner + tips to `widget.py`**

Modify `/home/burak/claude-usage-plugin/claude_usage/widget.py` inside `UsagePopup.update(stats)`:

Right after the "Weekly limits" section and separator, before the existing "Cost (today)" section, add:

```python
        # Anomaly banner — shown only when today is statistically unusual
        anomaly = getattr(stats, "anomaly", None)
        if anomaly is not None and getattr(anomaly, "is_anomaly", False):
            self._add_section_header("⚠ Unusual activity")
            self._add_dim_line(anomaly.message, bottom_margin=8)
            self._add_separator()
```

Immediately after the existing cost / top-projects block (just before the "Active sessions" header), add:

```python
        tips = getattr(stats, "tips", []) or []
        if tips:
            self._add_section_header("💡 Tips")
            for tip in tips:
                self._add_dim_line(tip, bottom_margin=4)
            self._add_separator()
```

- [ ] **Step 2: Add 90-day heatmap rendering**

Inside `UsagePopup`, add a new method (place it next to `_add_sparkline`):

```python
    def _add_heatmap(self, buckets: list[float], label: str) -> None:
        """Draw a single-row 90-cell heatmap with a caption underneath."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_bottom(12)

        area = Gtk.DrawingArea()
        area.set_size_request(-1, 18)

        theme = self._theme

        def draw(widget: Gtk.Widget, cr) -> None:
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            n = len(buckets) or 1
            cell_w = w / n
            r, g, b = _hex_to_rgb(theme["bar_track"])
            cr.set_source_rgb(r, g, b)
            cr.rectangle(0, 0, w, h)
            cr.fill()
            # Paint each cell with intensity proportional to its bucket value
            rb, gb, bb = _hex_to_rgb(theme["bar_blue"])
            for i, v in enumerate(buckets):
                if v <= 0:
                    continue
                alpha = min(float(v), 1.0)
                cr.set_source_rgba(rb, gb, bb, alpha)
                cr.rectangle(i * cell_w, 0, cell_w, h)
                cr.fill()

        area.connect("draw", draw)
        box.pack_start(area, False, False, 0)

        cap = Gtk.Label(label=label)
        cap.get_style_context().add_class("dim-text")
        cap.set_halign(Gtk.Align.START)
        box.pack_start(cap, False, False, 0)

        self._content_box.pack_start(box, False, False, 0)
```

And in `update(stats)`, after the weekly sparkline:

```python
        heatmap = getattr(stats, "daily_heatmap", []) or []
        if any(v > 0 for v in heatmap):
            self._add_heatmap(heatmap, "Last 90 days")
```

- [ ] **Step 3: Mirror changes in widget_macos.py**

Apply the same three additions (anomaly banner, tips section, heatmap row) to `/home/burak/claude-usage-plugin/claude_usage/widget_macos.py` inside `PopupView.drawRect_`.  Use `_section_header` / `_draw_str` for text, and for the heatmap draw a sequence of `NSBezierPath.fillRect_` rectangles:

```python
        # ---- Anomaly banner ----
        anomaly = getattr(stats, "anomaly", None)
        if anomaly is not None and getattr(anomaly, "is_anomaly", False):
            y = self._section_header("⚠ Unusual activity", y, w)
            f_dim = _sys_font(11)
            _draw_str(anomaly.message, PAD_X, y, f_dim, _DIM)
            y += 20
            y = self._draw_separator(y)

        # ---- Heatmap (last 90 days) ----
        heatmap = getattr(stats, "daily_heatmap", []) or []
        if any(v > 0 for v in heatmap):
            n = len(heatmap)
            cell_h = 18
            cell_w = (w - 2 * PAD_X) / n
            _ns_color(*_TRACK).setFill()
            NSBezierPath.fillRect_(NSMakeRect(PAD_X, y, w - 2 * PAD_X, cell_h))
            for i, v in enumerate(heatmap):
                if v <= 0:
                    continue
                alpha = min(float(v), 1.0)
                br, bg, bb, _ = _BAR
                _ns_color(br, bg, bb, alpha).setFill()
                NSBezierPath.fillRect_(NSMakeRect(PAD_X + i * cell_w, y, cell_w, cell_h))
            y += cell_h + 4
            _draw_str("Last 90 days", PAD_X, y, _sys_font(10), _DIM)
            y += 18

        # ---- Tips ----
        tips = getattr(stats, "tips", []) or []
        if tips:
            y = self._section_header("💡 Tips", y, w)
            f_dim = _sys_font(11)
            for tip in tips:
                _draw_str(tip, PAD_X, y, f_dim, _DIM)
                y += 18
            y = self._draw_separator(y)
```

Also update `_calc_popup_height` to account for the new sections (add ~50 px if anomaly present, ~20 px per tip, ~40 px if heatmap present).

- [ ] **Step 4: Smoke-test the popup**

```bash
pkill -f 'python3.*main.py' 2>/dev/null; sleep 1
python3 /home/burak/claude-usage-plugin/main.py &
```

Open the popup via the tray icon — verify the anomaly banner, heatmap, and tips appear (if any).

- [ ] **Step 5: Commit**

```bash
git add claude_usage/widget.py claude_usage/widget_macos.py
git commit -m "feat(popup): anomaly banner, 90d heatmap, cost-optimisation tips"
```

---

### Task 9: Webhook System

**Files:**
- Create: `claude_usage/webhooks.py`
- Modify: `claude_usage/config.py` (new defaults)
- Modify: `claude_usage/widget.py` (dispatch on events)
- Modify: `claude_usage/widget_macos.py`
- Test: `tests/test_webhooks.py`

Three event types: `threshold_crossed`, `daily_report` (first refresh after local midnight), `anomaly`.  Config:

```json
{
  "webhooks": {
    "threshold_crossed": "https://hooks.slack.com/...",
    "daily_report":      "https://discord.com/api/webhooks/..."
  }
}
```

Uses `urllib.request` — no `requests` dependency.

- [ ] **Step 1: Write failing tests for webhook dispatch**

```python
# tests/test_webhooks.py
"""Tests for webhook dispatch logic."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from claude_usage.webhooks import WebhookDispatcher


class TestWebhookDispatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.sender = MagicMock(side_effect=lambda url, payload: self.sent.append((url, payload)))
        self.cfg = {
            "threshold_crossed": "https://example.com/threshold",
            "daily_report":      "https://example.com/daily",
            "anomaly":           "https://example.com/anomaly",
        }

    def test_threshold_event_posts_to_threshold_url(self):
        d = WebhookDispatcher(self.cfg, sender=self.sender)
        d.fire("threshold_crossed", {"scope": "session", "value": 0.85})
        self.assertEqual(len(self.sent), 1)
        url, payload = self.sent[0]
        self.assertEqual(url, "https://example.com/threshold")
        self.assertEqual(payload["event"], "threshold_crossed")
        self.assertEqual(payload["value"], 0.85)

    def test_unknown_event_is_noop(self):
        d = WebhookDispatcher(self.cfg, sender=self.sender)
        d.fire("not_a_real_event", {})
        self.assertFalse(self.sent)

    def test_event_without_url_is_noop(self):
        d = WebhookDispatcher({"daily_report": "https://x/"}, sender=self.sender)
        d.fire("threshold_crossed", {})
        self.assertFalse(self.sent)

    def test_sender_failure_does_not_raise(self):
        bad_sender = MagicMock(side_effect=RuntimeError("network down"))
        d = WebhookDispatcher(self.cfg, sender=bad_sender)
        # Must swallow the exception — UI shouldn't crash on webhook failure
        d.fire("threshold_crossed", {"value": 1})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing test**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_webhooks.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `claude_usage/webhooks.py`**

```python
"""Webhook dispatcher for usage events (threshold crossings, daily reports,
anomalies).

Uses urllib to avoid adding ``requests`` as a dependency.  Network errors are
always swallowed — the widget must never crash because of a failing webhook.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable
from urllib.request import Request, urlopen


KNOWN_EVENTS = ("threshold_crossed", "daily_report", "anomaly")


def _default_sender(url: str, payload: dict) -> None:
    """POST ``payload`` as JSON to ``url`` with a short timeout."""
    body = json.dumps(payload).encode()
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "claude-usage-widget"},
        method="POST",
    )
    # 5-second timeout — webhooks must not block the UI thread even in the
    # worst case.  Dispatch is already off the GTK/rumps thread, but we're
    # still polite.
    urlopen(req, timeout=5).read()


class WebhookDispatcher:
    """Dispatch usage events to user-configured webhook URLs.

    Parameters
    ----------
    config:
        Mapping of event name -> webhook URL.  Missing events are silently
        skipped.
    sender:
        Override for the HTTP POST function, primarily for tests.
    """

    def __init__(
        self,
        config: dict,
        sender: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._send = sender or _default_sender

    def fire(self, event: str, data: dict | None = None) -> None:
        """Fire ``event`` with ``data``.  Always returns; never raises."""
        if event not in KNOWN_EVENTS:
            return
        url = self._config.get(event)
        if not url:
            return
        payload: dict[str, Any] = {
            "event": event,
            "ts": time.time(),
        }
        if data:
            payload.update(data)

        def _worker() -> None:
            try:
                self._send(url, payload)
            except Exception:
                # Never let webhook failures propagate.
                pass

        # Fire in a daemon thread so _default_sender's HTTP call cannot block.
        threading.Thread(target=_worker, daemon=True).start()
```

- [ ] **Step 4: Wire a `webhooks` config block**

Modify `/home/burak/claude-usage-plugin/claude_usage/config.py` — inside `DEFAULT_CONFIG`:

```python
    # --- Webhooks (opt-in) ---
    # Map event names to URLs.  Supported events:
    #   threshold_crossed — a session/weekly utilisation threshold was crossed.
    #   daily_report      — first refresh of a new local day.
    #   anomaly           — analytics.detect_anomaly flagged today.
    # Leave as {} to disable all webhooks.
    "webhooks": {},
```

- [ ] **Step 5: Wire into `widget.py` and `widget_macos.py`**

Modify `/home/burak/claude-usage-plugin/claude_usage/widget.py` — inside `ClaudeUsageTray.__init__`, after `self.notifier = UsageNotifier(config)`:

```python
        # Webhook dispatcher — fires on threshold / daily / anomaly events.
        from claude_usage.webhooks import WebhookDispatcher
        self._webhooks = WebhookDispatcher(config.get("webhooks", {}))
        self._last_daily_report_date: str = ""
```

In `_apply_stats(self, stats)`, after `self.notifier.check_stats(stats)`, add:

```python
        # Webhook: anomaly
        if getattr(stats.anomaly, "is_anomaly", False):
            self._webhooks.fire("anomaly", {
                "ratio": stats.anomaly.ratio,
                "z_score": stats.anomaly.z_score,
                "message": stats.anomaly.message,
            })

        # Webhook: daily report — fired once per local day on the first refresh
        today_iso = datetime.now().strftime("%Y-%m-%d")
        if today_iso != self._last_daily_report_date:
            self._last_daily_report_date = today_iso
            self._webhooks.fire("daily_report", {
                "date": today_iso,
                "session_utilization": stats.session_utilization,
                "weekly_utilization": stats.weekly_utilization,
                "today_cost": stats.today_cost,
                "today_tokens": stats.today_tokens,
            })
```

Apply identical additions to `widget_macos.py` (same attribute names).

- [ ] **Step 6: Fire `threshold_crossed` from the notifier**

The existing `UsageNotifier.check` already detects crossings for desktop notifications.  Modify `/home/burak/claude-usage-plugin/claude_usage/notifier.py`:

- In `UsageNotifier.__init__`, add a parameter `on_threshold: Callable[[str, float], None] | None = None`, defaulting to None, and store it.
- When a crossing is detected and a notification is sent, also call `self.on_threshold(scope, threshold)` if set.

Then in `widget.py` (and `widget_macos.py`) change the notifier instantiation to:

```python
        self.notifier = UsageNotifier(
            config,
            on_threshold=lambda scope, t: self._webhooks.fire(
                "threshold_crossed", {"scope": scope, "threshold": t},
            ),
        )
```

- [ ] **Step 7: Run all tests**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add claude_usage/webhooks.py claude_usage/config.py claude_usage/widget.py claude_usage/widget_macos.py claude_usage/notifier.py tests/test_webhooks.py
git commit -m "feat(webhooks): threshold_crossed, daily_report, anomaly dispatch"
```

---

### Task 10: GitHub Releases Auto-Update Checker

**Files:**
- Create: `claude_usage/updater.py`
- Modify: `claude_usage/widget.py` (menu item)
- Modify: `claude_usage/widget_macos.py` (menu item)
- Test: `tests/test_updater.py`

Queries `https://api.github.com/repos/bozdemir/claude-usage-widget/releases/latest` once on startup (in a daemon thread, no blocking), compares tag against `__version__`, exposes `stats.latest_version` / `stats.update_available` via the collector.  The tray menu shows "Update available: vX.Y.Z" when true.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_updater.py
"""Tests for the GitHub Releases update checker."""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from claude_usage.updater import check_latest_version, _semver_greater


class TestSemverCompare(unittest.TestCase):
    def test_greater_minor(self):
        self.assertTrue(_semver_greater("0.3.0", "0.2.9"))

    def test_greater_patch(self):
        self.assertTrue(_semver_greater("0.2.10", "0.2.9"))

    def test_equal_is_not_greater(self):
        self.assertFalse(_semver_greater("0.2.0", "0.2.0"))

    def test_pre_release_ignored(self):
        # Treat "v0.3.0-rc1" as 0.3.0 for the purposes of this check
        self.assertTrue(_semver_greater("v0.3.0-rc1", "0.2.0"))

    def test_v_prefix_stripped(self):
        self.assertTrue(_semver_greater("v1.0.0", "0.9.9"))

    def test_malformed_returns_false(self):
        self.assertFalse(_semver_greater("garbage", "0.1.0"))


class TestCheckLatestVersion(unittest.TestCase):
    def _fake_response(self, tag: str) -> MagicMock:
        payload = json.dumps({"tag_name": tag}).encode()
        m = MagicMock()
        m.__enter__.return_value = BytesIO(payload)
        m.__exit__.return_value = False
        return m

    def test_returns_tag_when_available(self):
        with patch("claude_usage.updater.urlopen", return_value=self._fake_response("v0.3.0")):
            result = check_latest_version("0.2.0")
        self.assertEqual(result, ("v0.3.0", True))

    def test_returns_no_update_when_equal(self):
        with patch("claude_usage.updater.urlopen", return_value=self._fake_response("v0.2.0")):
            result = check_latest_version("0.2.0")
        self.assertEqual(result, ("v0.2.0", False))

    def test_network_failure_returns_none(self):
        with patch("claude_usage.updater.urlopen", side_effect=OSError("dns fail")):
            result = check_latest_version("0.2.0")
        self.assertEqual(result, (None, False))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing tests**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_updater.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `claude_usage/updater.py`**

```python
"""Check GitHub Releases for a newer version of claude-usage-widget.

Pure networking — runs once on startup from a daemon thread, never blocks
the UI.  Relies only on urllib (no extra deps).
"""

from __future__ import annotations

import json
import re
from typing import Tuple
from urllib.request import Request, urlopen


RELEASE_URL = "https://api.github.com/repos/bozdemir/claude-usage-widget/releases/latest"


_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _parse(version: str) -> tuple[int, int, int] | None:
    m = _SEMVER_RE.match(version.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _semver_greater(latest: str, current: str) -> bool:
    """Return True iff ``latest`` is a strictly greater semver than ``current``."""
    a, b = _parse(latest), _parse(current)
    if a is None or b is None:
        return False
    return a > b


def check_latest_version(current: str) -> Tuple[str | None, bool]:
    """Fetch the latest release tag and compare against ``current``.

    Returns ``(tag, update_available)``.  Returns ``(None, False)`` on any
    network or parse error — callers should treat that as "no update info".
    """
    req = Request(RELEASE_URL, headers={"User-Agent": "claude-usage-widget"})
    try:
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None, False

    tag = data.get("tag_name") if isinstance(data, dict) else None
    if not isinstance(tag, str):
        return None, False
    return tag, _semver_greater(tag, current)
```

- [ ] **Step 4: Fire the check on widget startup (Linux)**

Modify `/home/burak/claude-usage-plugin/claude_usage/widget.py` — inside `ClaudeUsageTray.__init__`, after the existing menu is shown:

```python
        # Non-blocking version check
        self._latest_tag: str | None = None
        self._update_available: bool = False
        self.mi_update = Gtk.MenuItem(label="")
        self.mi_update.set_visible(False)
        self.mi_update.set_sensitive(False)
        menu.insert(self.mi_update, 0)  # top of menu

        def _check_update() -> None:
            from claude_usage import __version__
            from claude_usage.updater import check_latest_version
            tag, available = check_latest_version(__version__)
            self._latest_tag, self._update_available = tag, available
            if available and tag:
                GLib.idle_add(self._apply_update_label, tag)

        threading.Thread(target=_check_update, daemon=True).start()

    def _apply_update_label(self, tag: str) -> bool:
        self.mi_update.set_label(f"Update available: {tag}")
        self.mi_update.set_visible(True)
        return False
```

- [ ] **Step 5: Same for macOS (widget_macos.py)**

Use a `rumps.MenuItem("Update available: …")` inserted at index 0 of the menu; hide it by default (`item.set_callback(None)` and leaving the title empty), then set the title on update:

```python
        self.mi_update = rumps.MenuItem("")
        self.menu.insert_before("Session: …", self.mi_update)

        def _check_update() -> None:
            from claude_usage import __version__
            from claude_usage.updater import check_latest_version
            tag, available = check_latest_version(__version__)
            if available and tag:
                rumps.Timer(
                    lambda _t: (setattr(self.mi_update, "title", f"Update available: {tag}"),),
                    1,
                ).start()

        threading.Thread(target=_check_update, daemon=True).start()
```

- [ ] **Step 6: Run tests**

Run: `cd /home/burak/claude-usage-plugin && .venv/bin/python -m pytest tests/test_updater.py -v`
Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
git add claude_usage/updater.py claude_usage/widget.py claude_usage/widget_macos.py tests/test_updater.py
git commit -m "feat(updater): non-blocking GitHub release version check"
```

---

### Task 11: PyPI Packaging

**Files:**
- Create: `pyproject.toml`
- Create: `MANIFEST.in`
- Create: `.github/workflows/publish.yml`

Enables `pip install claude-usage-widget`; auto-publishes on git tag push.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "claude-usage-widget"
dynamic = ["version"]
description = "Desktop widget and CLI that shows real-time Claude Code usage limits and cost."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "Burak" }]
keywords = ["claude", "anthropic", "usage", "rate-limit", "widget"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: X11 Applications :: GTK",
    "Environment :: MacOS X",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Operating System :: MacOS :: MacOS X",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: System :: Monitoring",
]

# Stdlib-only runtime.  GTK and rumps are platform system deps, not PyPI deps.
dependencies = []

[project.optional-dependencies]
macos = ["rumps>=0.4.0", "pyobjc-framework-Cocoa>=9.0"]

[project.urls]
Homepage = "https://github.com/bozdemir/claude-usage-widget"
Issues = "https://github.com/bozdemir/claude-usage-widget/issues"

[project.scripts]
claude-usage = "claude_usage.cli:main"

[tool.setuptools]
include-package-data = true

[tool.setuptools.packages.find]
include = ["claude_usage*"]

[tool.setuptools.dynamic]
version = { attr = "claude_usage.__version__" }

[tool.setuptools.package-data]
claude_usage = ["py.typed", "icons/*.svg"]
```

- [ ] **Step 2: Create `MANIFEST.in`**

```
include README.md
include LICENSE
include config.json.example
recursive-include claude_usage/icons *.svg
recursive-include docs/integrations *
include requirements-macos.txt
```

- [ ] **Step 3: Verify a local build succeeds**

```bash
cd /home/burak/claude-usage-plugin
python3 -m pip install --user build
python3 -m build
ls dist/
```

Expected: `claude_usage_widget-0.2.0-py3-none-any.whl` and `.tar.gz` under `dist/`.

- [ ] **Step 4: Add GitHub Actions workflow**

Create `/home/burak/claude-usage-plugin/.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install build
        run: python -m pip install --upgrade build
      - name: Build sdist and wheel
        run: python -m build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml MANIFEST.in .github/workflows/publish.yml
git commit -m "build(pypi): pyproject.toml + GitHub Actions publish on tag"
```

- [ ] **Step 6: (Manual) Configure PyPI trusted publisher**

Document this in the PR description rather than automating:
- Create a PyPI project called `claude-usage-widget`.
- In the project settings, add a trusted publisher: GitHub repo `bozdemir/claude-usage-widget`, workflow `publish.yml`, environment `pypi`.

---

### Task 12: Homebrew Formula (Tap)

**Files:**
- Create: `Formula/claude-usage-widget.rb`
- Create: `docs/homebrew.md`

Publishes a Homebrew formula in a tap repo (`bozdemir/homebrew-tap`) so macOS users can run `brew install bozdemir/tap/claude-usage-widget`.

- [ ] **Step 1: Create `Formula/claude-usage-widget.rb`**

```ruby
class ClaudeUsageWidget < Formula
  include Language::Python::Virtualenv

  desc "Desktop widget that shows real-time Claude Code usage limits and cost"
  homepage "https://github.com/bozdemir/claude-usage-widget"
  url "https://files.pythonhosted.org/packages/source/c/claude-usage-widget/claude-usage-widget-0.2.0.tar.gz"
  # Replace the placeholder SHA after the first PyPI release is published.
  sha256 "REPLACE_WITH_TARBALL_SHA256"
  license "MIT"

  depends_on "python@3.12"

  resource "rumps" do
    url "https://files.pythonhosted.org/packages/source/r/rumps/rumps-0.4.0.tar.gz"
    sha256 "REPLACE_WITH_RUMPS_SHA256"
  end

  resource "pyobjc-core" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc-core/pyobjc-core-10.0.tar.gz"
    sha256 "REPLACE_WITH_PYOBJC_CORE_SHA256"
  end

  resource "pyobjc-framework-Cocoa" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc-framework-Cocoa/pyobjc-framework-Cocoa-10.0.tar.gz"
    sha256 "REPLACE_WITH_PYOBJC_COCOA_SHA256"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "0.2.0", shell_output("#{bin}/claude-usage --version")
  end
end
```

- [ ] **Step 2: Create `docs/homebrew.md`**

```markdown
# Homebrew tap (macOS)

```bash
brew tap bozdemir/tap
brew install claude-usage-widget
claude-usage --version
```

The formula pulls the source tarball from PyPI, so the Homebrew release
follows the PyPI release automatically.  To publish a new version:

1. Tag and push (`git tag v0.x.y && git push --tags`).  The
   `.github/workflows/publish.yml` action uploads to PyPI.
2. Compute the new tarball SHA:
   ```bash
   curl -L https://files.pythonhosted.org/packages/source/c/claude-usage-widget/claude-usage-widget-0.x.y.tar.gz | shasum -a 256
   ```
3. Update `Formula/claude-usage-widget.rb` (url + sha256 + version) in the
   tap repository and push.
```

- [ ] **Step 3: Commit**

```bash
git add Formula/claude-usage-widget.rb docs/homebrew.md
git commit -m "build(homebrew): tap formula + publishing docs"
```

- [ ] **Step 4: (Manual) Move formula to tap repo**

Once the first PyPI release is up and SHAs are filled in:

```bash
# In a separate checkout of bozdemir/homebrew-tap
cp /path/to/claude-usage-plugin/Formula/claude-usage-widget.rb Formula/
git commit -am "claude-usage-widget 0.2.0"
git push
```

---

## Acceptance / Smoke Tests

After all 12 tasks are complete, run:

```bash
cd /home/burak/claude-usage-plugin
.venv/bin/python -m pytest tests/ -v
# Expected: ~250 tests passing.

python3 main.py --version
# Expected: 0.2.0

python3 main.py --json | python3 -m json.tool | head -20
# Expected: UsageStats as JSON with anomaly, tips, daily_heatmap fields.

python3 main.py --export csv --days 7 | head -5
# Expected: CSV header + sample rows.

# With api_server_enabled=true in config.json:
curl -s http://127.0.0.1:8765/healthz
# Expected: {"ok": true}

# Visual: tray icon shows menu with "Update available: vX.Y.Z" when a newer
# GitHub release exists.  Popup shows anomaly banner + heatmap + tips.
```

---

## Out-of-Scope (deliberately deferred)

- **Prometheus exporter** — was in the brainstorm; dropped from this plan
  because the localhost JSON API (Task 3) covers 95 % of the same use case
  and Prometheus users can scrape it directly with a `json_exporter`.
- **VS Code extension** — separate repo, separate language (TypeScript);
  belongs in a follow-up project.
- **Obsidian plugin / Raycast extension** — same reasoning.
