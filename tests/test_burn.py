"""Tests for claude_usage.burn — burn/spike/retry-storm detection."""

from __future__ import annotations

import types

import pytest

from claude_usage.burn import (
    BurnAlert,
    BurnMonitor,
    detect_fast_burn,
    detect_retry_storm,
    detect_token_spike,
    merge_alerts,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _sample(ts: float, session: float, weekly: float = 0.0) -> dict:
    return {"ts": ts, "session": session, "weekly": weekly}


def _turn(ts: float, output_tokens: int, msg_id: str, cost_usd: float = 0.0):
    return types.SimpleNamespace(
        ts=ts, output_tokens=output_tokens, msg_id=msg_id, cost_usd=cost_usd
    )


def _hot_samples(base: float = 10_000.0):
    """10 samples, 60s cadence, session 0.10 -> 0.55 (+45% over 9 min = crit)."""
    return [_sample(base + i * 60, 0.10 + i * 0.05) for i in range(10)]


# --------------------------------------------------------------------------- #
# detect_fast_burn
# --------------------------------------------------------------------------- #

def test_fast_burn_45pct_9min_is_crit():
    base = 10_000.0
    a = detect_fast_burn(_hot_samples(base), now=base + 540, warn_pm=2.0,
                         crit_pm=5.0, window_s=600)
    assert a.active is True
    assert a.kind == "fast_burn"
    assert a.severity == "crit"
    assert a.rate_pct_per_min == pytest.approx(5.0)
    assert a.delta_pct == pytest.approx(45.0)
    assert a.minutes == pytest.approx(9.0)
    assert a.message == "Burned 45% in 9 min"


def test_fast_burn_warn_boundary():
    # 0.0 -> 0.02 over 60s = exactly 2.0 pct/min -> warn
    s = [_sample(0, 0.0), _sample(60, 0.02)]
    a = detect_fast_burn(s, now=60, warn_pm=2.0, crit_pm=5.0, window_s=600)
    assert a.active and a.severity == "warn"


def test_fast_burn_crit_boundary():
    # 0.0 -> 0.05 over 60s = exactly 5.0 pct/min -> crit
    s = [_sample(0, 0.0), _sample(60, 0.05)]
    a = detect_fast_burn(s, now=60, warn_pm=2.0, crit_pm=5.0, window_s=600)
    assert a.active and a.severity == "crit"


def test_fast_burn_just_below_warn_inactive():
    # 0.0 -> 0.019 over 60s = 1.9 pct/min -> inactive
    s = [_sample(0, 0.0), _sample(60, 0.019)]
    a = detect_fast_burn(s, now=60, warn_pm=2.0, crit_pm=5.0, window_s=600)
    assert a.active is False


def test_fast_burn_flat_inactive():
    s = [_sample(i * 60, 0.30) for i in range(5)]
    a = detect_fast_burn(s, now=240, warn_pm=2.0, crit_pm=5.0, window_s=600)
    assert a.active is False


def test_fast_burn_window_reset_negative_slope_inactive():
    s = [_sample(0, 0.90), _sample(60, 0.0)]
    a = detect_fast_burn(s, now=60, warn_pm=2.0, crit_pm=5.0, window_s=600)
    assert a.active is False


def test_fast_burn_single_sample_inactive():
    a = detect_fast_burn([_sample(0, 0.5)], now=0, warn_pm=2.0, crit_pm=5.0,
                         window_s=600)
    assert a.active is False


def test_fast_burn_empty_inactive():
    a = detect_fast_burn([], now=0, warn_pm=2.0, crit_pm=5.0, window_s=600)
    assert a.active is False


def test_fast_burn_coarse_300s_pair_still_computes():
    # 0.2 -> 0.7 over 300s = 10 pct/min -> crit
    s = [_sample(0, 0.2), _sample(300, 0.7)]
    a = detect_fast_burn(s, now=300, warn_pm=2.0, crit_pm=5.0, window_s=600)
    assert a.active and a.severity == "crit"
    assert a.rate_pct_per_min == pytest.approx(10.0)
    assert a.minutes == pytest.approx(5.0)


def test_fast_burn_excludes_samples_outside_window():
    # old sample far outside window must not anchor the slope
    s = [_sample(0, 0.0), _sample(1000, 0.50), _sample(1060, 0.52)]
    a = detect_fast_burn(s, now=1060, warn_pm=2.0, crit_pm=5.0, window_s=600)
    # only the last two count: 0.50 -> 0.52 over 60s = 2.0 pct/min -> warn
    assert a.active and a.severity == "warn"


# --------------------------------------------------------------------------- #
# detect_token_spike
# --------------------------------------------------------------------------- #

def test_token_spike_40k_over_2k_baseline_active():
    turns = [_turn(100, 40_000, "cand")] + [
        _turn(90 - i, 2_000, f"p{i}") for i in range(6)
    ]
    a = detect_token_spike(turns, multiplier=4.0, min_tokens=20_000,
                           min_baseline_turns=5)
    assert a.active is True
    assert a.kind == "token_spike"
    assert a.severity == "warn"
    assert a.msg_id == "cand"
    assert a.message == "Token spike: 40,000 tokens in one turn"


def test_token_spike_floor_inactive():
    # candidate below the absolute min_tokens floor even if it beats baseline
    turns = [_turn(100, 200, "cand")] + [
        _turn(90 - i, 10, f"p{i}") for i in range(6)
    ]
    a = detect_token_spike(turns, multiplier=4.0, min_tokens=20_000,
                           min_baseline_turns=5)
    assert a.active is False


def test_token_spike_cold_start_inactive():
    turns = [_turn(100, 40_000, "cand"), _turn(90, 2_000, "p0"),
             _turn(80, 2_000, "p1")]
    a = detect_token_spike(turns, multiplier=4.0, min_tokens=20_000,
                           min_baseline_turns=5)
    assert a.active is False


def test_token_spike_multiplier_gate():
    # 30k candidate, 20k baseline: 4x baseline = 80k > 30k -> inactive
    turns = [_turn(100, 30_000, "cand")] + [
        _turn(90 - i, 20_000, f"p{i}") for i in range(6)
    ]
    a = detect_token_spike(turns, multiplier=4.0, min_tokens=20_000,
                           min_baseline_turns=5)
    assert a.active is False


# --------------------------------------------------------------------------- #
# detect_retry_storm
# --------------------------------------------------------------------------- #

def test_retry_storm_3_in_120s_active():
    turns = [_turn(990, 6_000, "a"), _turn(950, 6_000, "b"),
             _turn(910, 6_000, "c")]
    a = detect_retry_storm(turns, now=1000, count=3, window_s=120,
                           min_tokens=5_000)
    assert a.active is True
    assert a.kind == "retry_storm"
    assert a.severity == "warn"
    assert a.msg_id == "a"  # newest qualifying
    assert a.message == "Retry storm: 3 heavy turns in 2 min"


def test_retry_storm_2_qualifying_inactive():
    turns = [_turn(990, 6_000, "a"), _turn(950, 6_000, "b"),
             _turn(800, 6_000, "c")]  # c is outside the 120s window
    a = detect_retry_storm(turns, now=1000, count=3, window_s=120,
                           min_tokens=5_000)
    assert a.active is False


def test_retry_storm_ignores_light_turns():
    turns = [_turn(990, 6_000, "a"), _turn(950, 100, "b"),
             _turn(910, 6_000, "c")]  # b too light
    a = detect_retry_storm(turns, now=1000, count=3, window_s=120,
                           min_tokens=5_000)
    assert a.active is False


# --------------------------------------------------------------------------- #
# merge_alerts
# --------------------------------------------------------------------------- #

def _crit_fb():
    return BurnAlert(active=True, kind="fast_burn", severity="crit")


def _warn_fb():
    return BurnAlert(active=True, kind="fast_burn", severity="warn")


def _spike():
    return BurnAlert(active=True, kind="token_spike", severity="warn")


def _storm():
    return BurnAlert(active=True, kind="retry_storm", severity="warn")


def test_merge_crit_fast_burn_wins():
    m = merge_alerts(_warn_fb(), _spike(), _storm(), _crit_fb())
    assert m.kind == "fast_burn" and m.severity == "crit"


def test_merge_storm_beats_spike_and_warn_fb():
    m = merge_alerts(_warn_fb(), _spike(), _storm())
    assert m.kind == "retry_storm"


def test_merge_spike_beats_warn_fb():
    m = merge_alerts(_warn_fb(), _spike())
    assert m.kind == "token_spike"


def test_merge_warn_fb_lowest():
    m = merge_alerts(_warn_fb())
    assert m.kind == "fast_burn" and m.severity == "warn"


def test_merge_none_active_returns_inactive():
    assert merge_alerts().active is False
    assert merge_alerts(BurnAlert(), BurnAlert()).active is False


# --------------------------------------------------------------------------- #
# BurnMonitor
# --------------------------------------------------------------------------- #

class _Capture:
    def __init__(self):
        self.sends: list = []
        self.events: list = []

    def sender(self, title, body):
        self.sends.append((title, body))

    def on_event(self, ev):
        self.events.append(ev)


def test_monitor_fast_burn_debounce_one_call_while_hot():
    cap = _Capture()
    mon = BurnMonitor({}, sender=cap.sender, on_event=cap.on_event)
    hot = _hot_samples()
    now = 10_000 + 540
    result = None
    for _ in range(3):
        result = mon.check(samples=hot, turns=[], session_reset=5000.0,
                           now=now, notifications_enabled=True)
    assert result.active and result.kind == "fast_burn"
    assert len(cap.sends) == 1
    assert len(cap.events) == 1


def test_monitor_fast_burn_refires_after_session_reset_change():
    cap = _Capture()
    mon = BurnMonitor({}, sender=cap.sender, on_event=cap.on_event)
    hot = _hot_samples()
    now = 10_000 + 540
    mon.check(samples=hot, turns=[], session_reset=5000.0, now=now,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    # same episode key -> still suppressed
    mon.check(samples=hot, turns=[], session_reset=5000.0, now=now,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    # new session_reset re-arms
    mon.check(samples=hot, turns=[], session_reset=6000.0, now=now,
              notifications_enabled=True)
    assert len(cap.sends) == 2


def test_monitor_fast_burn_refires_after_cooldown():
    cap = _Capture()
    mon = BurnMonitor({"burn_alert_cooldown_seconds": 900},
                      sender=cap.sender, on_event=cap.on_event)
    hot = _hot_samples()
    now = 10_000 + 540
    mon.check(samples=hot, turns=[], session_reset=5000.0, now=now,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    # long after cooldown, same key, still hot -> re-fires
    later = _hot_samples(base=now + 2000)
    now2 = now + 2000 + 540
    mon.check(samples=later, turns=[], session_reset=5000.0, now=now2,
              notifications_enabled=True)
    assert len(cap.sends) == 2


def test_monitor_spike_once_per_msg_id_and_prune():
    cap = _Capture()
    mon = BurnMonitor({}, sender=cap.sender, on_event=cap.on_event)
    spike_turns = [_turn(100, 40_000, "A")] + [
        _turn(90 - i, 2_000, f"p{i}") for i in range(6)
    ]
    mon.check(samples=[], turns=spike_turns, session_reset=1.0, now=100,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    # same turns -> A already fired, no new send
    mon.check(samples=[], turns=spike_turns, session_reset=1.0, now=100,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    assert "A" in mon._fired_msg_ids
    # A leaves the turn window -> pruned
    other = [_turn(200, 2_000, "B")] + [
        _turn(190 - i, 2_000, f"q{i}") for i in range(6)
    ]
    mon.check(samples=[], turns=other, session_reset=1.0, now=200,
              notifications_enabled=True)
    assert "A" not in mon._fired_msg_ids
    assert len(cap.sends) == 1


def test_monitor_storm_rearms_after_quiet_gap():
    cap = _Capture()
    mon = BurnMonitor({"spike_min_tokens": 5_000, "retry_storm_turns": 3,
                       "retry_storm_window_seconds": 120},
                      sender=cap.sender, on_event=cap.on_event)
    storm_turns = [_turn(990, 6_000, "a"), _turn(950, 6_000, "b"),
                   _turn(910, 6_000, "c")]
    mon.check(samples=[], turns=storm_turns, session_reset=1.0, now=1000,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    # still storming, no quiet gap -> suppressed
    mon.check(samples=[], turns=storm_turns, session_reset=1.0, now=1000,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    # quiet gap (no qualifying turns) re-arms
    mon.check(samples=[], turns=[], session_reset=1.0, now=2000,
              notifications_enabled=True)
    assert len(cap.sends) == 1
    # storm again -> fires
    storm2 = [_turn(2990, 6_000, "d"), _turn(2950, 6_000, "e"),
              _turn(2910, 6_000, "f")]
    mon.check(samples=[], turns=storm2, session_reset=1.0, now=3000,
              notifications_enabled=True)
    assert len(cap.sends) == 2


def test_monitor_burn_alerts_disabled_suppresses_sender_but_event_fires():
    cap = _Capture()
    mon = BurnMonitor({"burn_alerts_enabled": False},
                      sender=cap.sender, on_event=cap.on_event)
    hot = _hot_samples()
    now = 10_000 + 540
    mon.check(samples=hot, turns=[], session_reset=5000.0, now=now,
              notifications_enabled=True)
    assert len(cap.sends) == 0
    assert len(cap.events) == 1


def test_monitor_notifications_disabled_suppresses_sender_but_event_fires():
    cap = _Capture()
    mon = BurnMonitor({}, sender=cap.sender, on_event=cap.on_event)
    hot = _hot_samples()
    now = 10_000 + 540
    mon.check(samples=hot, turns=[], session_reset=5000.0, now=now,
              notifications_enabled=False)
    assert len(cap.sends) == 0
    assert len(cap.events) == 1


def test_monitor_returns_merged_badge_alert():
    cap = _Capture()
    mon = BurnMonitor({}, sender=cap.sender, on_event=cap.on_event)
    hot = _hot_samples()
    now = 10_000 + 540
    badge = mon.check(samples=hot, turns=[], session_reset=5000.0, now=now,
                      notifications_enabled=True)
    assert badge.active and badge.kind == "fast_burn" and badge.severity == "crit"


def test_monitor_inactive_returns_inactive_badge():
    cap = _Capture()
    mon = BurnMonitor({}, sender=cap.sender, on_event=cap.on_event)
    badge = mon.check(samples=[], turns=[], session_reset=1.0, now=0,
                      notifications_enabled=True)
    assert badge.active is False
    assert len(cap.sends) == 0
    assert len(cap.events) == 0
