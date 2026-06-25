# Fault Tolerance

The usage-data fetch is protected against transient network blips and
server-side hiccups with **exponential backoff and jitter**, applied at the
network layer in `claude_usage/collector.py` (`_fetch_oauth_usage`).

## How it works

- **Transient-fault handling** — a momentary connection reset, DNS blip, or
  request timeout no longer surfaces as a failed refresh; the request is
  retried before giving up.
- **Exponential delay** — each retry waits twice as long as the previous one
  (`base_delay * 2**attempt`), so a struggling endpoint isn't hammered.
- **Randomized jitter** — a few random milliseconds are added to every delay
  so a fleet of widgets doesn't retry in lockstep (the thundering-herd
  problem).
- **No retry on most 4xx** — HTTP 401/403 and other 4xx responses return
  immediately; they won't fix themselves, so retrying just delays the error
  the user needs to see (e.g. "re-authenticate with `claude`"). **429 is the
  exception:** a budget-based rate-limit is only retried when the server
  sends an explicit positive `Retry-After`; otherwise the widget bails to a
  calm "rate limited — using last known values" state rather than firing a
  burst that prolongs the throttling.

## Parameters

Defined as module constants in `claude_usage/collector.py`:

| Constant | Default | Meaning |
| --- | --- | --- |
| `_USAGE_MAX_RETRIES` | `2` | Retries after the first attempt (3 tries total). |
| `_USAGE_BASE_DELAY` | `0.2s` | Base delay, doubled each retry, plus jitter. |

Bounds are intentionally tight: both the GUI (which polls every 60s, backing
off adaptively up to 300s when throttled) and CLI status-bar integrations
(`--field`, polled every few seconds by tmux/waybar/polybar) go through this
path, so the worst-case added latency stays well under a second.
