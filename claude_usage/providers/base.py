"""Provider protocol and shared helpers for multi-provider usage collection."""

from __future__ import annotations

from typing import Any, Protocol

from claude_usage.collector import UsageStats


class Provider(Protocol):
    """A usage source. ``id`` keys config/history; ``title`` labels the OSD block."""

    id: str
    title: str

    def collect(self, config: dict[str, Any]) -> UsageStats:
        """Return a fully-populated UsageStats for this provider."""
        ...


def window_label(minutes: int) -> str:
    """Human label for a rate-limit window of *minutes* (43200→'30d', 300→'5h')."""
    if minutes <= 0:
        return ""
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"
