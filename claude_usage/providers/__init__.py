"""Usage providers: pluggable sources that each produce a collector.UsageStats."""

from claude_usage.providers.claude import ClaudeProvider
from claude_usage.providers.codex import CodexProvider

PROVIDERS = {p.id: p for p in (ClaudeProvider(), CodexProvider())}


def get_provider(provider_id: str):
    return PROVIDERS[provider_id]
