# Changelog

All notable changes to this project are documented here.
This project follows [semantic versioning](https://semver.org/).

## 0.12.1

### Changed
- **Scroll-wheel zoom now reaches 4.0×** (was 2.0×) — on hi-DPI / large displays
  a corner OSD stays readable from across the room. `SCALE_MIN`/`SCALE_STEP`
  and the default size are unchanged. Thanks @faithpricejp-source (#22).

## 0.12.0

### Added
- **Second provider: OpenAI Codex (opt-in).** Add `"codex"` to the `providers`
  config and the widget shows your local OpenAI Codex 5h/weekly usage beneath
  Claude's — two extra bars in bars view, a 2×2 ring grid in gauge — rendered
  natively in **all 11 themes**. It reads `codex app-server` over JSON-RPC
  (`account/rateLimits/read`), throttled to `codex_poll_seconds` (default 300 s)
  with an on-disk cache and a deadline-bounded read that can't hang a refresh;
  the rows auto-hide when the `codex` CLI is missing, logged out, or returns no
  data. Off by default, POSIX-only. Thanks @faithpricejp-source (#17/#18/#21).
- **statusLine-fed rate limits (opt-in).** Point `statusline_cache_path` at a
  JSON file your Claude Code `statusLine` command dumps its rate-limit payload
  to, and the widget uses it as a zero-cost, seconds-fresh source: it skips the
  `/api/oauth/usage` call while the dump is fresh (forcing a real one at most
  once per `usage_endpoint_min_seconds`) and falls back to it when the endpoint
  throttles. Off by default. Thanks @faithpricejp-source (#20).

### Fixed
- **Single-instance guard.** Launching a second `claude-usage` no longer stacks
  another OSD on top of the first — a per-user `QLockFile` makes the extra
  launch exit cleanly, and a hard-killed instance's stale lock is reclaimed
  automatically. Thanks @faithpricejp-source (#19).

## 0.11.1

### Fixed
- **Accurate pricing for current models.** `claude-fable-5` was billed at the
  Sonnet fallback (`$3/$15`) instead of its real premium tier (**`$10/$50`**),
  under-reporting Fable cost ~3.3× everywhere it's shown (cost popup, budget,
  `--statusline`, `--json`). Added explicit table entries for
  **Opus 4.8** (`$5/$25`), **Fable 5** (`$10/$50`) and **Sonnet 5**
  (`$2/$10` intro → `$3/$15` after 2026-08-31), plus a `fable` family fallback
  so future point releases inherit the right tier. Also silences the "unknown
  model" warnings these ids emitted on every refresh.

## 0.11.0

### Added
- **`--statusline`** — a one-shot CLI flag that prints one compact line
  (`S 42% · W 18% · $3.21`, plus a scoped bar when present) for Claude Code's
  native `statusLine` setting. Reuses the `--json`/`--field` collect→redact
  path, so graceful degradation (last-known restore on 429) is inherited; it
  never launches the GUI, even with `--detach`. See
  `docs/integrations/claude-code-statusline.md`.
- **Real-time burn / spike / retry-storm alerts.** A bright OSD badge
  (`▲42%` fast-burn, `▲SPIKE`, `▲STORM`) on the bars title row + gauge, plus a
  **debounced, once-per-episode** desktop notification and `burn_alert`
  webhook, when the 5-hour window burns abnormally fast or a single turn /
  retry loop spikes tokens. Fully tunable (`burn_*`, `spike_*`, `retry_storm_*`
  keys); off via `burn_alerts_enabled: false`. The badge ships for the 5
  built-in themes (the 6 skins are a follow-up; notifications fire regardless).
- **Peak-window awareness.** An unobtrusive "reduced 5h limit until …" hint in
  the detail popup during Anthropic's weekday reduced-limit window (default
  ~5–11 AM US Pacific). Data-driven and fully overridable (`peak_*` keys); the
  default Pacific path uses self-contained DST math, so it needs no `tzdata`
  and works on Windows out of the box.
- **Monthly budget cap + projection.** Set `monthly_budget_usd` > 0 to see
  month-to-date spend and a linear end-of-month projection in the popup
  (`$X / $Y this month · projected $Z`, red when over), plus a once-per-month
  notification + `budget_projection` webhook when on track to exceed the cap.
  Off (and its extra month-wide scan skipped) at the `0.0` default.

### Notes
- Extended-thinking cost breakout was investigated and **dropped as
  infeasible**: verified against 29,981 real assistant messages, `message.usage`
  reports no separate reasoning/thinking token count (it's folded into
  `output_tokens`) and on-disk thinking blocks are signature-only, so no count
  or usable proxy exists. Revisit if Claude Code starts emitting an
  `output_reasoning_tokens`-style field.

## 0.10.0

### Added
- **Model-scoped weekly usage bar** ([#15](https://github.com/bozdemir/claude-usage-widget/issues/15)).
  When Anthropic reports a separate weekly cap for a specific model — the
  new **Fable** weekly limit is the first — a third bar appears
  automatically below Session and Weekly, labelled with the model's name
  (e.g. "Fable"). It's parsed generically from the `/api/oauth/usage`
  `limits` array (the `weekly_scoped` entries), so it also covers any
  future scoped model, and it **auto-hides** when the API stops reporting
  it (the Fable cap is temporary — Anthropic moves it to usage credits
  after the free window). Rendered natively in **bars, gauge, all 6
  Claude-designed skins, and the detail popup**; the last-known value is
  retained (and expired windows cleared) across a throttled poll, exactly
  like the session/weekly bars.
- **Update-available check.** On startup and once every 24 h a daemon
  thread queries the GitHub Releases API for the latest tag; when a newer
  version is published it fires a single desktop notification
  (`Update with: pip install --upgrade claude-usage-widget`) and shows a
  banner in the right-click menu. It notifies only once per new version,
  so a user who hasn't upgraded yet isn't nagged daily, and every call is
  best-effort — a failed or throttled request is silently ignored.
- **Widget version in the right-click menu.** A dim, disabled
  `claude-usage v<version>` line at the foot of the context menu so you
  can see which build is running at a glance.

## 0.9.3

### Fixed
Twelve bugs from a comprehensive audit (10 parallel reviewers over the
post-v0.6 churn):

- **False "Credentials expired" on transient faults.** 5xx responses from
  `/api/oauth/usage` are now retried with the existing backoff, and the
  `/v1/messages` x-api-key fallback is skipped entirely for OAuth tokens —
  it could only 401 and mislabeled any server blip as an auth failure.
- **Minimized OSD hijacked clicks into the browser** when a news headline
  was cached (the news click region went negative at the 6px minimized
  height); the region now also requires the news feature to be enabled.
- **"Always on top" toggle could break the window**: re-creating the native
  window dropped the translucency / taskbar-skip / macOS-visibility
  attributes, leaving an opaque black box or a taskbar entry. All are
  re-asserted now.
- **`--detach` crashed on macOS** (AppKit init in a fork()ed child aborts);
  it now respawns a fresh process via `subprocess.Popen`.
- **News strip fixes**: fetched with the certifi SSL context (was always
  empty on macOS python.org builds), animated even when the cost ticker is
  idle (was frozen off-screen), hidden after opting back out (a cached
  headline kept rendering), and the cache honours `XDG_CONFIG_HOME`.
- **Popup cost arithmetic**: per-model rate lines now use the same
  family-fallback pricing as the computed totals, so "tokens × rate = $"
  adds up for not-yet-tabled models (both classic and skin popups).
- **Expired-window clamp bypass**: the last-known fallback now searches
  session/weekly reset timestamps independently, so a sample carrying only
  one key can't bury the other and resurrect a finished window.
- **Receipt skin paper grain** was erased by the shared painter's
  background fill every frame; custom drag positions stayed stale after a
  wheel-resize; the scrolling popup's window chrome matched the real 10px
  scrollbar width; `osd_visible: false` now restores as minimized (a truly
  hidden restore had no UI path back).

## 0.9.2

### Fixed
- **macOS: blank session/weekly from TLS verification.** Added a certifi CA
  bundle so HTTPS to `api.anthropic.com` verifies on macOS python.org builds
  (which don't trust the system keychain), which otherwise failed with
  `CERTIFICATE_VERIFY_FAILED` and blanked the bars. Complements the 0.9.1
  credential fix — the two cover different macOS failure modes. ([#14](https://github.com/bozdemir/claude-usage-widget/pull/14))

### Changed
- `certifi` is now a (small, pure-Python) runtime dependency alongside
  PySide6-Essentials; docs reframed from "single dependency" to "two
  pure-pip wheels, no system libraries".

## 0.9.1

### Added
- **"Always on top" toggle** in the right-click menu — turn it off to use the
  OSD as a normal background desktop widget the window manager stacks behind
  focused windows (`osd_always_on_top`). ([#13](https://github.com/bozdemir/claude-usage-widget/issues/13))

### Fixed
- **macOS: blank session/weekly usage.** Hardened credential loading so a
  Keychain-only install (or a GUI launch without Keychain access) no longer
  silently shows blank bars. Lookup now mirrors Claude Code: the
  `CLAUDE_CODE_OAUTH_TOKEN` env var → `~/.claude/.credentials.json` → Keychain
  (multiple service names), with an actionable error instead of a silent
  blank.

## 0.9.0

### Changed
- **Adaptive poll interval.** Default refresh is now 60s and backs off
  exponentially up to 300s when the usage endpoint rate-limits, snapping back
  on the next clean refresh (`refresh_seconds` / `refresh_max_seconds`).
- **Refined 429 handling.** A budget-based 429 (no/zero `Retry-After`) is no
  longer retried in-poll; only an explicit positive `Retry-After` is waited
  out. Expired rate-limit windows are clamped to zero on a throttled poll
  instead of resurrecting stale percentages. ([#12](https://github.com/bozdemir/claude-usage-widget/pull/12))

## 0.8.x

### Fixed
- **429 from `/api/oauth/usage` mislabeled "Credentials expired"** and blanked
  the reset countdown; now surfaces a calm "rate limited" state and retains
  the last-known reset times. ([#11](https://github.com/bozdemir/claude-usage-widget/issues/11))
- **macOS:** OSD and popups no longer auto-hide when the app loses focus
  (`WA_MacAlwaysShowToolWindow`). ([#10](https://github.com/bozdemir/claude-usage-widget/pull/10))

### Added
- **OSD Position** presets (four corners + remembered custom drag position)
  ([#4](https://github.com/bozdemir/claude-usage-widget/issues/4)), session-state
  persistence (scale / minimized / visible), and a `--detach` flag to run the
  GUI in the background.

## 0.7.x

### Added
- **Exponential backoff with jitter** on the usage fetch for transient faults.
- **Live news ticker** (opt-in) showing Anthropic/Claude headlines.

## 0.6.x

### Changed
- **Switched the primary data source to `/api/oauth/usage`** — the same
  plan-level utilisation the Claude UI shows — replacing the old per-API-key
  rate-limit header read, which under-reported real usage.

### Added
- **Six Claude-designed skins** (terminal, dashboard, hud, receipt, strip,
  brutalist) on top of the five classic palettes — 11 themes in all.
- A **theme-tinted right-click menu**, popup detail screens for every skin,
  and a per-theme loading state.

---

Earlier releases (0.1–0.5) established the core OSD overlay, detail popup,
cost estimation, forecasting, history/heatmaps, notifications, webhooks, the
localhost JSON API, CLI mode, PyPI packaging, and the Homebrew tap.
