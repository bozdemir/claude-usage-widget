from claude_usage.config import DEFAULT_CONFIG
from claude_usage.collector import collect_providers, collect_all, UsageStats

def test_default_config_collects_only_claude(monkeypatch):
    monkeypatch.setattr("claude_usage.providers.claude.collect_all",
                        lambda cfg: UsageStats(today_tokens=7))
    out = collect_providers(dict(DEFAULT_CONFIG))
    assert list(out.keys()) == ["claude"]
    assert out["claude"].today_tokens == 7

def test_codex_enabled_collects_both(monkeypatch, tmp_path):
    monkeypatch.setattr("claude_usage.providers.claude.collect_all",
                        lambda cfg: UsageStats(today_tokens=7))
    cfg = dict(DEFAULT_CONFIG, providers=["claude", "codex"], codex_dir=str(tmp_path))
    out = collect_providers(cfg)
    assert list(out.keys()) == ["claude", "codex"]
    assert out["codex"].provider_title == "CODEX"

def test_provider_error_does_not_abort_siblings(monkeypatch, tmp_path):
    def boom(cfg):
        raise RuntimeError("kaboom")
    monkeypatch.setattr("claude_usage.providers.claude.collect_all", boom)
    # claude (first) raises; codex (second, empty dir) still collects — the
    # failing provider must be captured as an error entry WITHOUT blanking its
    # sibling.
    cfg = dict(DEFAULT_CONFIG, providers=["claude", "codex"], codex_dir=str(tmp_path))
    out = collect_providers(cfg)
    assert "kaboom" in out["claude"].rate_limit_error
    assert "codex" in out                       # sibling survived the failure
    assert out["codex"].provider_title == "CODEX"

def test_collect_all_still_returns_claude(tmp_path, monkeypatch):
    # Hermetic: an empty claude_dir means collect_all reads no on-disk logs and
    # prices no real recent-model tokens (which would emit pricing warnings and
    # pollute pricing.py's module-global warn-once set, breaking test_pricing).
    # Patch fetch_rate_limits so there is no network call. Just confirm the
    # alias still returns a UsageStats with its unchanged signature.
    monkeypatch.setattr("claude_usage.collector.fetch_rate_limits",
                        lambda claude_dir: {"error": "test"})
    cfg = dict(DEFAULT_CONFIG, claude_dir=str(tmp_path))
    assert isinstance(collect_all(cfg), UsageStats)

def test_enabled_providers_falls_back_on_empty():
    from claude_usage.providers import enabled_providers
    assert enabled_providers({}) == ["claude"]
    assert enabled_providers({"providers": []}) == ["claude"]
    assert enabled_providers({"providers": None}) == ["claude"]
    assert enabled_providers({"providers": ["claude", "codex"]}) == ["claude", "codex"]

def test_collect_providers_empty_list_falls_back_to_claude(monkeypatch):
    monkeypatch.setattr("claude_usage.providers.claude.collect_all",
                        lambda cfg: UsageStats(today_tokens=1))
    out = collect_providers(dict(DEFAULT_CONFIG, providers=[]))
    assert list(out.keys()) == ["claude"]
