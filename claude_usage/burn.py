"""Real-time burn / spike / retry-storm detection.

Pure module — no PySide6, no network, no filesystem, no reading of the real
clock. Every function that needs "now" takes it as a parameter, so behaviour is
fully deterministic under test.

Two layers:

1. **Stateless detectors** (:func:`detect_fast_burn`, :func:`detect_token_spike`,
   :func:`detect_retry_storm`) that turn raw samples/turns into a
   :class:`BurnAlert`. :func:`merge_alerts` collapses several into the single
   highest-severity alert that drives the OSD badge.

2. **A stateful :class:`BurnMonitor`** that debounces those detectors into
   at-most-once episode notifications. It stays pure by taking *injected*
   callables — ``sender`` (desktop notification) and ``on_event`` (webhook) —
   instead of importing a real notifier, mirroring
   :class:`claude_usage.notifier.UsageNotifier`.

Input shapes (matched exactly to the real caller):

* ``samples``: ``list[dict]``, each ``{'ts': float_epoch, 'session': 0..1,
  'weekly': float, ...}``. Fast-burn reads ``sample['ts']`` and
  ``sample['session']``.
* ``turns``: objects (newest-FIRST) with attributes ``.ts`` (float epoch),
  ``.output_tokens`` (int), ``.msg_id`` (str), ``.cost_usd`` (float).
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import Callable, Optional


@dataclass
class BurnAlert:
    """A single burn/spike/storm signal (also the OSD badge payload)."""

    active: bool = False
    kind: str = ""
    severity: str = ""
    rate_pct_per_min: float = 0.0
    delta_pct: float = 0.0
    minutes: float = 0.0
    msg_id: str = ""
    message: str = ""


# --------------------------------------------------------------------------- #
# Stateless detectors
# --------------------------------------------------------------------------- #

def detect_fast_burn(
    samples: list[dict],
    now: float,
    warn_pm: float,
    crit_pm: float,
    window_s: float,
) -> BurnAlert:
    """Detect a fast rise in session utilization over a recent window.

    Filters ``samples`` to those with ``ts`` in ``[now - window_s, now]``, needs
    at least two, then fits a straight line between the first and last of them:
    ``slope = (u_last - u_first) / (t_last - t_first)`` in fraction/second.
    ``pct_per_min = slope * 60 * 100``.

    Severity is ``'crit'`` at/above ``crit_pm``, ``'warn'`` at/above ``warn_pm``,
    otherwise inactive. A non-positive slope (a post-reset drop or flat usage)
    or fewer than two in-window samples yields an inactive alert.
    """
    lo = now - window_s
    win = [s for s in samples if lo <= float(s.get("ts", 0.0)) <= now]
    if len(win) < 2:
        return BurnAlert()

    win.sort(key=lambda s: float(s.get("ts", 0.0)))
    first, last = win[0], win[-1]
    t0 = float(first.get("ts", 0.0))
    t1 = float(last.get("ts", 0.0))
    u0 = float(first.get("session", 0.0))
    u1 = float(last.get("session", 0.0))

    dt = t1 - t0
    if dt <= 0:
        return BurnAlert()

    slope = (u1 - u0) / dt
    if slope <= 0:  # flat or post-reset drop — not a burn
        return BurnAlert()

    pct_per_min = slope * 60 * 100
    if pct_per_min >= crit_pm:
        severity = "crit"
    elif pct_per_min >= warn_pm:
        severity = "warn"
    else:
        return BurnAlert()

    delta_pct = (u1 - u0) * 100
    minutes = dt / 60
    return BurnAlert(
        active=True,
        kind="fast_burn",
        severity=severity,
        rate_pct_per_min=pct_per_min,
        delta_pct=delta_pct,
        minutes=minutes,
        message=f"Burned {delta_pct:.0f}% in {minutes:.0f} min",
    )


def detect_token_spike(
    turns: list,
    multiplier: float,
    min_tokens: int,
    min_baseline_turns: int,
) -> BurnAlert:
    """Detect a single turn whose output dwarfs the recent baseline.

    Needs ``len(turns) > min_baseline_turns`` so there are enough *prior* turns
    (``turns[1:]``) to establish a baseline. The candidate is the newest turn
    (``turns[0]``); the baseline is the median output of the prior turns. Fires
    iff ``candidate.output_tokens >= max(min_tokens, multiplier * baseline)``.

    A cold start (too few prior turns) yields an inactive alert.
    """
    if len(turns) <= min_baseline_turns:
        return BurnAlert()

    prior = turns[1:]
    if not prior:
        return BurnAlert()

    baseline = statistics.median(t.output_tokens for t in prior)
    candidate = turns[0]
    threshold = max(min_tokens, multiplier * baseline)
    if candidate.output_tokens >= threshold:
        return BurnAlert(
            active=True,
            kind="token_spike",
            severity="warn",
            msg_id=candidate.msg_id,
            message=(
                f"Token spike: {candidate.output_tokens:,} tokens in one turn"
            ),
        )
    return BurnAlert()


def detect_retry_storm(
    turns: list,
    now: float,
    count: int,
    window_s: float,
    min_tokens: int,
) -> BurnAlert:
    """Detect a burst of heavy turns in a short window (a retry/loop storm).

    Counts turns whose *own* ``ts`` is at/after ``now - window_s`` and whose
    ``output_tokens`` is at/above ``min_tokens``. Fires iff that count reaches
    ``count``. The reported ``msg_id`` is the newest (largest-``ts``) qualifying
    turn.
    """
    lo = now - window_s
    qualifying = [
        t for t in turns if t.ts >= lo and t.output_tokens >= min_tokens
    ]
    if len(qualifying) < count:
        return BurnAlert()

    newest = max(qualifying, key=lambda t: t.ts)
    return BurnAlert(
        active=True,
        kind="retry_storm",
        severity="warn",
        msg_id=newest.msg_id,
        message=(
            f"Retry storm: {len(qualifying)} heavy turns "
            f"in {window_s // 60:.0f} min"
        ),
    )


# Rank of an active alert. Higher wins. Inactive alerts rank 0.
def _rank(a: BurnAlert) -> int:
    if not a.active:
        return 0
    if a.kind == "fast_burn" and a.severity == "crit":
        return 4
    if a.kind == "retry_storm":
        return 3
    if a.kind == "token_spike":
        return 2
    if a.kind == "fast_burn" and a.severity == "warn":
        return 1
    return 0


def merge_alerts(*alerts: BurnAlert) -> BurnAlert:
    """Collapse several alerts into the single highest-severity one.

    Ordering: crit fast_burn > retry_storm > token_spike > warn fast_burn.
    Returns an inactive :class:`BurnAlert` if none are active.
    """
    best: Optional[BurnAlert] = None
    best_rank = 0
    for a in alerts:
        r = _rank(a)
        if r > best_rank:
            best_rank = r
            best = a
    return best if best is not None else BurnAlert()


# --------------------------------------------------------------------------- #
# Stateful monitor (debounced notifications)
# --------------------------------------------------------------------------- #

_TITLES = {
    "fast_burn": "Claude usage burning fast",
    "token_spike": "Claude token spike",
    "retry_storm": "Claude retry storm",
}


class BurnMonitor:
    """Debounces the stateless detectors into at-most-once episode alerts.

    ``sender`` is invoked ONLY when both ``burn_alerts_enabled`` (config) and
    ``notifications_enabled`` (per-call) are true. ``on_event`` (webhook) is
    invoked whenever an episode fires, regardless of either flag — mirroring
    :class:`claude_usage.notifier.UsageNotifier`. Both callables are injected so
    the module stays pure and testable.
    """

    def __init__(
        self,
        config: dict,
        sender: Optional[Callable[[str, str], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        self.enabled = bool(config.get("burn_alerts_enabled", True))
        self.warn_pm = float(config.get("burn_warn_pct_per_min", 2.0))
        self.crit_pm = float(config.get("burn_crit_pct_per_min", 5.0))
        self.window_s = float(config.get("burn_window_seconds", 600))
        self.spike_mult = float(config.get("spike_token_multiplier", 4.0))
        self.spike_min = int(config.get("spike_min_tokens", 20_000))
        self.spike_baseline = int(config.get("spike_baseline_min_turns", 5))
        self.storm_count = int(config.get("retry_storm_turns", 3))
        self.storm_window = float(config.get("retry_storm_window_seconds", 120))
        self.cooldown = float(config.get("burn_alert_cooldown_seconds", 900))

        self._sender = sender
        self._on_event = on_event

        # Fast-burn debounce state (one episode per session_reset key).
        self._burn_suppressed = False
        self._burn_fired_reset: object = None
        self._burn_fired_ts: Optional[float] = None
        # Token-spike: msg_ids already fired (pruned as turns age out).
        self._fired_msg_ids: set = set()
        # Retry-storm: armed after a quiet gap, disarmed on fire.
        self._storm_armed = True

    def check(
        self,
        *,
        samples: list[dict],
        turns: list,
        session_reset: float,
        now: float,
        notifications_enabled: bool,
    ) -> BurnAlert:
        """Run all detectors, dispatch any newly-fired episodes, return the badge.

        The returned value is the merged (highest-severity) current alert for the
        OSD badge, computed every call regardless of debounce state.
        """
        fb = detect_fast_burn(
            samples, now, self.warn_pm, self.crit_pm, self.window_s
        )
        spike = detect_token_spike(
            turns, self.spike_mult, self.spike_min, self.spike_baseline
        )
        storm = detect_retry_storm(
            turns, now, self.storm_count, self.storm_window, self.spike_min
        )

        self._handle_fast_burn(fb, session_reset, now, notifications_enabled)
        self._handle_spike(spike, turns, notifications_enabled)
        self._handle_storm(storm, turns, now, notifications_enabled)

        return merge_alerts(fb, spike, storm)

    # -- per-detector debounce ---------------------------------------------- #

    def _handle_fast_burn(
        self,
        fb: BurnAlert,
        session_reset: float,
        now: float,
        notifications_enabled: bool,
    ) -> None:
        # Re-arm on any of: new episode key, cooldown elapsed, rate fell below
        # the warn hysteresis floor.
        if session_reset != self._burn_fired_reset:
            self._burn_suppressed = False
        elif (
            self._burn_fired_ts is not None
            and (now - self._burn_fired_ts) >= self.cooldown
        ):
            self._burn_suppressed = False
        elif fb.rate_pct_per_min < self.warn_pm * 0.5:
            self._burn_suppressed = False

        if fb.active and not self._burn_suppressed:
            self._burn_suppressed = True
            self._burn_fired_reset = session_reset
            self._burn_fired_ts = now
            self._dispatch(fb, notifications_enabled)

    def _handle_spike(
        self,
        spike: BurnAlert,
        turns: list,
        notifications_enabled: bool,
    ) -> None:
        # Prune msg_ids no longer present in the turn window so a later reuse of
        # the same id can fire again.
        present = {getattr(t, "msg_id", None) for t in turns}
        self._fired_msg_ids &= present

        if spike.active and spike.msg_id not in self._fired_msg_ids:
            self._fired_msg_ids.add(spike.msg_id)
            self._dispatch(spike, notifications_enabled)

    def _handle_storm(
        self,
        storm: BurnAlert,
        turns: list,
        now: float,
        notifications_enabled: bool,
    ) -> None:
        # A quiet gap (no qualifying heavy turn in the window) re-arms the storm.
        lo = now - self.storm_window
        qualifying = any(
            t.ts >= lo and t.output_tokens >= self.spike_min for t in turns
        )
        if not qualifying:
            self._storm_armed = True

        if storm.active and self._storm_armed:
            self._storm_armed = False
            self._dispatch(storm, notifications_enabled)

    # -- dispatch ------------------------------------------------------------ #

    def _dispatch(self, alert: BurnAlert, notifications_enabled: bool) -> None:
        if self.enabled and notifications_enabled and self._sender is not None:
            try:
                self._sender(_TITLES.get(alert.kind, "Claude burn alert"),
                             alert.message)
            except Exception:
                pass
        if self._on_event is not None:
            try:
                self._on_event(asdict(alert))
            except Exception:
                pass
