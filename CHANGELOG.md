# Changelog

All notable changes to this project are documented here.
This project follows [semantic versioning](https://semver.org/).

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
