"""Webhook dispatcher for usage events (threshold, daily, anomaly).

Uses urllib so we don't pull in ``requests`` as a runtime dependency. All
dispatches run in a daemon thread; network errors are swallowed so a
misconfigured webhook can never crash the widget.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable
from urllib.request import Request, urlopen


KNOWN_EVENTS = ("threshold_crossed", "daily_report", "anomaly")


def _default_sender(url: str, payload: dict) -> None:
    """POST *payload* as JSON to *url* with a short timeout."""
    body = json.dumps(payload).encode()
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "claude-usage-widget",
        },
        method="POST",
    )
    urlopen(req, timeout=5).read()


class WebhookDispatcher:
    """Dispatch usage events to user-configured webhook URLs."""

    def __init__(
        self,
        config: dict,
        sender: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._send = sender or _default_sender

    def fire(self, event: str, data: dict | None = None) -> None:
        """Fire *event* with *data*. Always returns; never raises."""
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

        threading.Thread(target=_worker, daemon=True).start()
