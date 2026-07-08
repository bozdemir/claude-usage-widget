import json, os
from claude_usage.collector import UsageStats
from claude_usage.providers import codex


def _write_rollout(codex_dir, name, records):
    d = os.path.join(codex_dir, "sessions", "2026", "07", "09")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def _token_count(ts, primary=None, secondary=None, last_total=0):
    return {"timestamp": ts, "type": "event_msg", "payload": {
        "type": "token_count",
        "info": {"last_token_usage": {"input_tokens": 0, "cached_input_tokens": 0,
                 "output_tokens": last_total, "reasoning_output_tokens": 0,
                 "total_tokens": last_total}},
        "rate_limits": {"limit_id": "codex", "plan_type": "pro",
                        "primary": primary, "secondary": secondary}}}


def test_rate_limits_map_short_to_session_long_to_weekly(tmp_path):
    codex_dir = str(tmp_path)
    _write_rollout(codex_dir, "rollout-a.jsonl", [
        _token_count("2026-07-09T01:00:00.000Z",
                     primary={"used_percent": 5.0, "window_minutes": 43200, "resets_at": 1786122437},
                     secondary={"used_percent": 40.0, "window_minutes": 300, "resets_at": 1786000000}),
    ])
    rl = codex._latest_rate_limits(codex_dir)
    stats = UsageStats()
    codex._apply_rate_limits(stats, rl)
    # secondary (300 min) is the short window → session bar
    assert round(stats.session_utilization, 2) == 0.40
    assert stats.session_reset == 1786000000
    assert stats.session_label == "5h"
    # primary (43200 min) is the long window → weekly bar
    assert round(stats.weekly_utilization, 2) == 0.05
    assert stats.weekly_label == "30d"


def test_null_secondary_leaves_session_bar_empty(tmp_path):
    codex_dir = str(tmp_path)
    _write_rollout(codex_dir, "rollout-b.jsonl", [
        _token_count("2026-07-09T02:00:00.000Z",
                     primary={"used_percent": 12.0, "window_minutes": 43200, "resets_at": 1786122437},
                     secondary=None),
    ])
    rl = codex._latest_rate_limits(codex_dir)
    stats = UsageStats()
    codex._apply_rate_limits(stats, rl)
    assert round(stats.weekly_utilization, 2) == 0.12
    assert stats.session_utilization == 0.0
    assert stats.session_label == ""


def test_latest_rate_limits_uses_newest_event_across_files(tmp_path):
    codex_dir = str(tmp_path)
    _write_rollout(codex_dir, "rollout-old.jsonl", [
        _token_count("2026-07-09T01:00:00.000Z",
                     primary={"used_percent": 5.0, "window_minutes": 43200, "resets_at": 1}),
    ])
    _write_rollout(codex_dir, "rollout-new.jsonl", [
        _token_count("2026-07-09T09:00:00.000Z",
                     primary={"used_percent": 33.0, "window_minutes": 43200, "resets_at": 2}),
    ])
    rl = codex._latest_rate_limits(codex_dir)
    assert rl["primary"]["used_percent"] == 33.0  # newest timestamp wins


def test_no_rollouts_returns_none(tmp_path):
    assert codex._latest_rate_limits(str(tmp_path)) is None


def test_token_deltas_bucket_by_day(tmp_path):
    codex_dir = str(tmp_path)
    d = os.path.join(codex_dir, "sessions", "2026", "07", "09")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rollout-c.jsonl"), "w") as f:
        f.write(json.dumps({"timestamp": "2026-07-09T00:00:00.000Z", "type": "turn_context",
                            "payload": {"model": "gpt-5.5"}}) + "\n")
        f.write(json.dumps(_token_count("2026-07-09T10:00:00.000Z", last_total=100)) + "\n")
        f.write(json.dumps(_token_count("2026-07-08T10:00:00.000Z", last_total=40)) + "\n")
    out = codex._collect_tokens(codex_dir, "2026-07-09",
                                ["2026-07-08", "2026-07-09"])
    assert out["today_tokens"] == 100          # only the 07-09 event
    assert out["week_tokens"] == 140           # both in-week events
    assert out["today_by_model"] == {"gpt-5.5": 100}


def test_token_default_model_when_no_model_event(tmp_path):
    codex_dir = str(tmp_path)
    d = os.path.join(codex_dir, "sessions", "2026", "07", "09")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rollout-e.jsonl"), "w") as f:
        f.write(json.dumps(_token_count("2026-07-09T10:00:00.000Z", last_total=50)) + "\n")
    out = codex._collect_tokens(codex_dir, "2026-07-09", ["2026-07-09"], default_model="gpt-x")
    assert out["today_by_model"] == {"gpt-x": 50}


def test_token_model_change_splits_by_model(tmp_path):
    codex_dir = str(tmp_path)
    d = os.path.join(codex_dir, "sessions", "2026", "07", "09")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rollout-f.jsonl"), "w") as f:
        f.write(json.dumps({"timestamp": "2026-07-09T09:00:00.000Z", "type": "turn_context",
                            "payload": {"model": "gpt-5.5"}}) + "\n")
        f.write(json.dumps(_token_count("2026-07-09T09:30:00.000Z", last_total=30)) + "\n")
        f.write(json.dumps({"timestamp": "2026-07-09T10:00:00.000Z", "type": "turn_context",
                            "payload": {"model": "gpt-5-codex"}}) + "\n")
        f.write(json.dumps(_token_count("2026-07-09T10:30:00.000Z", last_total=70)) + "\n")
    out = codex._collect_tokens(codex_dir, "2026-07-09", ["2026-07-09"])
    assert out["today_by_model"] == {"gpt-5.5": 30, "gpt-5-codex": 70}
    assert out["today_tokens"] == 100


def test_token_out_of_window_excluded(tmp_path):
    codex_dir = str(tmp_path)
    d = os.path.join(codex_dir, "sessions", "2026", "06", "20")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rollout-old.jsonl"), "w") as f:
        f.write(json.dumps(_token_count("2026-06-20T10:00:00.000Z", last_total=999)) + "\n")
    out = codex._collect_tokens(codex_dir, "2026-07-09", ["2026-07-08", "2026-07-09"])
    assert out["today_tokens"] == 0 and out["week_tokens"] == 0
