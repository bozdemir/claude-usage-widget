"""Threshold-crossing notifications for usage utilization.

Pure crossing logic lives in :class:`CrossingDetector` (testable).
:class:`UsageNotifier` binds the detector to a platform-appropriate desktop
notification sender.

The sender uses plain subprocess calls so the widget has no runtime
dependency on PyGObject (libnotify) or rumps:

    Linux : ``notify-send`` (from ``libnotify-bin`` / ``libnotify``)
    macOS : ``osascript`` (AppleScript, ships with macOS)
    Other : silent no-op
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Callable, Optional


class CrossingDetector:
    """Detects upward threshold crossings in a stream of values per scope.

    A threshold fires only on the transition that crosses it (prev < t <= cur),
    so a reset (cur < prev) silently re-arms it for the next cycle.
    """

    def __init__(self, thresholds):
        self.thresholds = sorted(t for t in thresholds if 0.0 < t <= 1.0)
        self._last: dict[str, float] = {}

    def check(self, scope: str, util: float) -> list[float]:
        prev = self._last.get(scope)
        self._last[scope] = util
        if prev is None:
            return []
        return [t for t in self.thresholds if prev < t <= util]


def _send_linux(title: str, body: str) -> None:
    """Fire a desktop notification via ``notify-send`` (libnotify)."""
    if shutil.which("notify-send") is None:
        return
    try:
        subprocess.run(
            ["notify-send", "--icon=dialog-warning", title, body],
            check=False, timeout=5,
        )
    except Exception:
        pass


def _send_macos(title: str, body: str) -> None:
    """Fire a desktop notification via ``osascript`` (AppleScript)."""
    # AppleScript string literals escape quotes by DOUBLING (`""`), not via
    # backslash. Newlines also break the single-line `-e` script so we
    # collapse them to spaces. This guards against arbitrary content
    # (project paths, error messages) breaking the script or worse,
    # injecting AppleScript via crafted strings.
    def _escape(s: str) -> str:
        return s.replace('"', '""').replace("\n", " ").replace("\r", " ")
    t = _escape(title)
    b = _escape(body)
    script = f'display notification "{b}" with title "{t}"'
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=False, timeout=5,
        )
    except Exception:
        pass


def _default_sender() -> Callable[[str, str], None]:
    if sys.platform == "darwin":
        return _send_macos
    if sys.platform.startswith("linux"):
        return _send_linux

    def _noop(title: str, body: str) -> None:
        return

    return _noop


class UsageNotifier:
    """Fires desktop notifications when session/weekly utilization crosses a threshold."""

    SCOPES = (
        ("session", "Session", "session_utilization"),
        ("weekly", "Weekly", "weekly_utilization"),
    )

    def __init__(
        self,
        config: dict,
        sender: Optional[Callable[[str, str], None]] = None,
        on_threshold: Optional[Callable[[str, float], None]] = None,
    ):
        self.enabled = bool(config.get("notifications_enabled", True))
        thresholds = config.get("notify_thresholds", [0.75, 0.90])
        self.detector = CrossingDetector(thresholds)
        self._send = sender or _default_sender()
        self._on_threshold = on_threshold

    def check_stats(self, stats) -> None:
        for scope, label, attr in self.SCOPES:
            util = getattr(stats, attr, 0.0) or 0.0
            for t in self.detector.check(scope, util):
                if self.enabled:
                    pct_t = int(round(t * 100))
                    pct_now = int(round(util * 100))
                    self._send(
                        f"Claude {label} usage at {pct_now}%",
                        f"Crossed the {pct_t}% threshold.",
                    )
                if self._on_threshold is not None:
                    try:
                        self._on_threshold(scope, t)
                    except Exception:
                        pass
