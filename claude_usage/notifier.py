"""Threshold-crossing notifications for usage utilization.

Pure crossing logic lives in `CrossingDetector` (testable). `UsageNotifier`
binds the detector to a platform-appropriate desktop notification sender.
"""

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
    try:
        import gi
        gi.require_version("Notify", "0.7")
        from gi.repository import Notify
        if not Notify.is_initted():
            Notify.init("Claude Usage")
        Notify.Notification.new(title, body, "dialog-warning").show()
    except Exception:
        pass


def _send_macos(title: str, body: str) -> None:
    try:
        import rumps
        rumps.notification(title=title, subtitle="", message=body)
    except Exception:
        pass


def _default_sender():
    return _send_macos if sys.platform == "darwin" else _send_linux


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
        # Observer callback fired for every threshold crossing, used e.g.
        # by the widget to dispatch a webhook. Fires independent of the
        # ``enabled`` flag — webhooks are a separate opt-in pathway.
        self._on_threshold = on_threshold

    def check_stats(self, stats) -> None:
        for scope, label, attr in self.SCOPES:
            util = getattr(stats, attr, 0.0) or 0.0
            crossings = self.detector.check(scope, util)
            for t in crossings:
                # Desktop notification (respects notifications_enabled)
                if self.enabled:
                    pct_t = int(round(t * 100))
                    pct_now = int(round(util * 100))
                    self._send(
                        f"Claude {label} usage at {pct_now}%",
                        f"Crossed the {pct_t}% threshold.",
                    )
                # Observer callback (independent of notifications_enabled)
                if self._on_threshold is not None:
                    try:
                        self._on_threshold(scope, t)
                    except Exception:
                        pass
