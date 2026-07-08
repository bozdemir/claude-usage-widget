# Multi-provider usage: Codex support (full parity with Claude)

**Date:** 2026-07-09
**Status:** Approved design — ready for implementation plan
**Repo:** HOKOCORP/agent-usage-widget (fork of bozdemir/claude-usage-widget)

## Goal

The widget currently shows Claude plan usage on the desktop OSD. We use Codex
(OpenAI `codex` CLI, `gpt-5.5` / `gpt-5-codex`) inside Claude Code for review,
and want Codex usage shown **at full parity** with Claude: rate-limit bars,
token totals, cost, per-project, forecast, and all analytics — as a second
provider block on the same OSD.

## Feasibility (confirmed against live data)

Codex stores everything we need in local JSONL, so **no new dependency and no
network call** is required (Claude needs an OAuth call for reset times; Codex
does not).

- Rollout files: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
- Record shape: `{timestamp, type, payload}`. Relevant records:
  - `session_meta` → `payload.cwd`, `payload.git.{repository_url,branch}`,
    `payload.cli_version`, `payload.originator`
  - `turn_context` / records carrying `payload.model` → model id (`"gpt-5.5"`)
  - `event_msg` with `payload.type == "token_count"` → the load-bearing record:
    ```json
    {"info": {
       "total_token_usage": {"input_tokens","cached_input_tokens","output_tokens","reasoning_output_tokens","total_tokens"},
       "last_token_usage":  {"input_tokens","cached_input_tokens","output_tokens","reasoning_output_tokens","total_tokens"},
       "model_context_window": 258400},
     "rate_limits": {
       "limit_id":"codex","plan_type":"free","rate_limit_reached_type":null,
       "primary":  {"used_percent":5.0,"window_minutes":43200,"resets_at":1786122437},
       "secondary": null,
       "credits":  {"has_credits":false,"unlimited":false,"balance":null}}}
    ```

## Architecture: a provider spine

Today: `collector.collect_all(config) -> UsageStats`, consumed by every skin
(`skins/{hud,dashboard,strip,terminal,brutalist,receipt}` via `widget.py` /
`overlay.py`), by `cli.py` (`--field`/`--json`/`--export`), and by
`api_server.py`. `UsageStats` is already provider-agnostic in shape (bars,
tokens, cost, forecast, trends), so it stays the shared currency.

Introduce a thin provider layer:

```
claude_usage/providers/
  base.py     # Provider protocol: id: str, title: str, collect(config) -> UsageStats
  claude.py   # wraps existing collector.collect_all — behaviour unchanged
  codex.py    # new: reads ~/.codex/sessions/**/*.jsonl -> UsageStats
```

- New `collector.collect_providers(config) -> dict[str, UsageStats]`, ordered by
  `config["providers"]`. `collect_all` is kept as a thin
  `collect_providers(...)["claude"]` alias so nothing that imports it breaks.
- Render layer iterates an ordered list of `(title, UsageStats)` blocks instead
  of one. Each skin stacks N provider blocks (title per block: `CLAUDE`,
  `CODEX`). A provider whose `collect()` raises is rendered as an error block,
  never taking down the other provider (mirrors existing `rate_limit_error`
  handling).

**Rejected alternatives:** parallel `codex_*` modules (duplicates
forecast/history/ticker wiring); a `provider=` field threaded through every
existing function (scatters Claude-vs-Codex branches). One protocol + two
implementations is the minimum that also lets a third agent drop in later.

## Codex → UsageStats mapping

| `UsageStats` field | Codex source & rule |
|---|---|
| `session_*` / `weekly_*` (utilization, reset, label) | From the **newest rollout's last `token_count`**'s `rate_limits` (account-global; newest = current). `secondary` (shorter window) → `session_*`; `primary` (longer window) → `weekly_*`. `*_utilization = used_percent/100`, `*_reset = resets_at`. If `secondary` is null → only the weekly bar. If no `rate_limits` found anywhere → set `rate_limit_error` and show tokens only (same degraded path Claude uses). |
| bar labels | Derived from `window_minutes` via a `window_label(minutes)` helper (300→"5h", 10080→"7d", 43200→"30d") — **replaces the hardcoded "5h"/"weekly" strings** so both providers label from real window sizes. |
| `today_tokens` / `week_tokens`, `today_model_tokens`, `today_hourly` | Sum `last_token_usage.total_tokens` (per-turn delta) over every `token_count` event whose **event `timestamp`** falls in the window — mirrors how the Claude collector attributes per-message tokens and handles window boundaries. Per-model via nearest preceding `payload.model`; hourly via event hour. |
| `today_by_model_detailed` | Per model: sum `last_token_usage` `input`/`output`/`cached_input`(→cache_read)/`reasoning_output`. |
| `today_cost` / `week_cost`, `cache_savings` | `pricing.py` gains OpenAI/Codex entries (`gpt-5.5`, `gpt-5-codex`, …). `cached_input_tokens` priced at the cache-read rate; `reasoning_output_tokens` billed as output. Same `calculate_stats_cost` path. |
| `today_by_project` | `session_meta.cwd` basename (fallback `git.repository_url` repo name), top-N by tokens. |
| `active_sessions`, `live_activity`, `active_subagent_count` | A rollout whose newest event is within the live window = active; subagent count N/A for Codex → 0. |
| `subscription_type` | `rate_limits.plan_type` (`free`/`plus`/`pro`/`team`). Drives the same "flat-fee → API-equivalent value" cost relabeling. |
| forecast, anomaly, heatmaps, hourly histogram, ticker, cache_opportunities | Computed by the **existing** `forecast`/`analytics`/`trends`/`ticker`/`cache_analyzer` modules over the Codex sample/token stream — provider-agnostic once fed Codex data. |

### Token-accounting note
`total_token_usage` is cumulative within a session; `last_token_usage` is the
latest turn's delta. We sum **deltas by event timestamp** (not final
cumulative) so a session spanning midnight/week-boundary attributes correctly.
Sanity check in tests: a session's final `total_token_usage.total_tokens` ≈ sum
of its `last_token_usage` deltas.

## Config additions (`config.py` `DEFAULT_CONFIG`)

```python
"providers": ["claude", "codex"],   # which providers to show, in order
"codex_dir": os.path.expanduser("~/.codex"),
"codex_default_model": "gpt-5.5",   # fallback when a turn has no model id
```
Back-compat: absent `providers` key defaults to `["claude"]` so existing
installs render exactly as before until the user opts in.

## Build in 3 complete, shippable slices

Each phase is fully finished (error paths + tests), not a skeleton.

**Phase 1 — Provider spine + Codex bars & tokens**
- `providers/{base,claude,codex}.py`; `collect_providers`; `collect_all` alias.
- `window_label(minutes)` helper; skins render an ordered list of provider blocks.
- Config keys above.
- Codex collector: rollout discovery, `rate_limits` → bars, per-turn token
  sums (today/week/per-model/hourly), active-session detection.
- **Done when:** OSD shows a CODEX block with primary/secondary bars, reset
  labels, and today/week token totals next to CLAUDE.

**Phase 2 — Cost + per-project**
- OpenAI/Codex pricing entries in `pricing.py` (verify rates at publish time);
  `cached_input`→cache_read, `reasoning_output`→output.
- Codex `today_cost`/`week_cost`/`cache_savings`; `today_by_project` from cwd/repo.
- **Done when:** CODEX block shows cost + top projects at parity with CLAUDE.

**Phase 3 — Analytics parity + surfaces**
- `history.jsonl` gains a `provider` field (old rows default `claude`);
  `append_sample`/`load_samples`/`aggregate` become provider-scoped.
- Per-provider forecast, anomaly, daily/yearly heatmap, hourly histogram,
  ticker, cache_opportunities.
- `api_server.py` exposes per-provider stats; `cli.py` gets `--provider NAME`
  (default `claude` for back-compat with existing status-bar scripts).
- **Done when:** every Claude analytic has a working Codex equivalent on the OSD,
  API, and CLI.

## Out of scope (separate concerns)

- Renaming the `claude_usage` package / `claude-usage` command to HOKO branding
  (tracked separately; keep author in LICENSE/source per fork-attribution rule).
- Codex variants of `ai_report` (Claude-authored summary) and `news_fetcher`
  (Anthropic RSS) — stay Claude-only; generalize later if wanted.

## Testing

Mirror the existing `tests/test_collector.py` style with a fixture Codex
rollout (a few `token_count` events + `session_meta`) under a temp
`codex_dir`:
- rate_limits → correct session/weekly utilization, reset, and window labels;
- token sums bucketed correctly across a day boundary;
- null `secondary` → single bar; missing `rate_limits` → `rate_limit_error` set,
  tokens still populated;
- `window_label` unit cases (300/10080/43200);
- Phase 2: cost from a known token mix; unknown model → fallback pricing + warn;
- Phase 3: history round-trips the `provider` field; old (provider-less) rows
  load as `claude`.
