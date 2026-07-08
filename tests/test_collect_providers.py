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

def test_provider_error_does_not_abort_siblings(monkeypatch):
    def boom(cfg): raise RuntimeError("kaboom")
    monkeypatch.setattr("claude_usage.providers.claude.collect_all", boom)
    out = collect_providers(dict(DEFAULT_CONFIG, providers=["claude"]))
    assert "kaboom" in out["claude"].rate_limit_error

def test_collect_all_still_returns_claude(monkeypatch):
    monkeypatch.setattr("claude_usage.providers.claude.collect_all",
                        lambda cfg: UsageStats(today_tokens=3))
    # collect_all itself is the underlying Claude path; unchanged signature.
    assert isinstance(collect_all(dict(DEFAULT_CONFIG)), UsageStats)
