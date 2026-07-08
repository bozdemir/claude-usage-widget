"""Claude provider — thin wrapper over the existing collector.collect_all."""

from __future__ import annotations

from typing import Any

from claude_usage.collector import UsageStats, collect_all


class ClaudeProvider:
    id = "claude"
    title = "CLAUDE"

    def collect(self, config: dict[str, Any]) -> UsageStats:
        stats = collect_all(config)
        if not stats.provider_title:
            stats.provider_title = self.title
        return stats
