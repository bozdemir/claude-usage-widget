# tests/test_multi_overlay_routing.py
# Pure routing logic — no Qt. Extract the mapping into a testable helper.
from claude_usage.collector import UsageStats
from claude_usage.widget import route_stats


def test_route_stats_matches_by_provider_id():
    overlays = {"claude": object(), "codex": object()}
    by_prov = {"claude": UsageStats(today_tokens=1), "codex": UsageStats(today_tokens=2)}
    pairs = route_stats(overlays, by_prov)
    # returns (overlay, stats) pairs only for providers that have an overlay
    assert {id(o) for o, _ in pairs} == {id(overlays["claude"]), id(overlays["codex"])}


def test_route_stats_skips_unknown_provider():
    overlays = {"claude": object()}
    by_prov = {"claude": UsageStats(), "codex": UsageStats()}
    assert len(route_stats(overlays, by_prov)) == 1
