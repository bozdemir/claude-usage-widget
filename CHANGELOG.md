# Changelog

All notable changes to this project are documented here.
This project follows [semantic versioning](https://semver.org/).

## 0.13.7

### Changed

- **The scrolling ticker and news strip use a third of the CPU.** They
  scroll at 25 frames a second, and every frame redrew the whole widget,
  although only the strips move. That cost 1 to 2 seconds of CPU a minute
  depending on the theme, more than the refreshes themselves after 0.13.6.
  Everything that doesn't scroll is now drawn once and reused, and each frame
  only draws the moving text: 0.3 to 0.4 seconds a minute in every theme. The
  widget looks exactly the same, pixel for pixel. The minimized widget and
  the gauge view without news had no animation and are unchanged.

## 0.13.6

### Fixed

- **The widget pinned a CPU core for a second or two every minute.** Each
  refresh re-read and re-decoded every recent Claude Code transcript, and
  four separate scans (today/week tokens, prompt-cache tips, the cost ticker
  and the LIVE badge) each did it again over the same files. On a busy
  `~/.claude` that is a few hundred thousand JSON lines a minute. On top of
  that, the 90-day usage history was rewritten in full on every refresh. Now
  each transcript line is decoded once, when it is appended, and the history
  file is rewritten about once a day. A refresh after the first takes about
  a seventh of the CPU it did, and the numbers are exactly the same.
  Thanks @dmitryuk (#39).
- **A minimized widget dragged next to the clock reopened somewhere else.**
  At startup the saved position was fitted for the full-size panel and only
  then shrunk to the thin strip, so a strip dropped at the bottom of the
  screen came back a whole panel height higher. It now reopens exactly where
  you left it, and restoring the full panel near the bottom edge keeps it on
  screen. Thanks @dmitryuk (#38).

## 0.13.5

### Changed

- **An expired Claude Code token no longer looks like live data.** Claude
  Code's access token lasts a few hours and only Claude Code refreshes it, so
  after a night without running `claude` the widget fell back to its last
  known numbers and painted them as if they were current. By then the 5-hour
  window has usually rolled over, so the bars read 0% with no explanation.
  The Claude rows are now dimmed next to a "token expired · run claude" hint,
  in every view and theme and at the top of the minimized tooltip. Run
  `claude` once and the next poll is live again. The widget stays read-only:
  it never refreshes or writes the token itself. Codex rows are unaffected.
  Thanks @atl3tico (#37).

## 0.13.4

### Fixed

- **The minimized widget was nearly invisible on a dark desktop panel.** Its
  track is close to the theme's background tone, so on a dark panel it
  disappeared, and at a low session % only a 4-pixel dot was left. The
  capsule now has a thin outline in the opposite tone of its track, and a
  slightly more solid track, so an empty capsule stands out on dark and light
  panels in all 11 themes. Thanks @dmitryuk (#34).

### Added

- **Hover the minimized widget to see every number.** The minimized capsule
  shows only the session %, so hovering it now shows a tooltip with each
  row's % and reset time: Session, Weekly, and the Fable and Codex rows when
  you have them. Thanks @dmitryuk (#35).

## 0.13.3

### Fixed

- **Codex plans without a 5-hour limit showed their weekly usage as "Codex
  5h".** The widget took the first window Codex reports to be the 5-hour one
  and the second to be the weekly one. Plans with only a weekly limit (such as
  business prolite) send their weekly window first, so it appeared as
  "Codex 5h", above an empty "Codex 7d 0%" row. Windows are now told apart by
  their length, and a window the plan doesn't have gets no row at all, in
  every theme and in both bars and gauge view. In gauge view a lone weekly
  ring sits under Claude's Weekly ring. Only matters if you've added `"codex"`
  to `providers`. Thanks @atl3tico (#33).

## 0.13.2

### Fixed

- **The widget crashed on Python 3.10 and 3.11 with PySide6 6.12.0.**
  PySide6-Essentials 6.12.0 (released 2026-10-08) drops a reference to `None`
  on every void Qt call such as `setPen` or `fillRect`. Python 3.12+ is
  unaffected because `None` is immortal there, but on 3.10/3.11 the count
  reaches zero after a few hundred skin paints and the process aborts with
  `Fatal Python error: none_dealloc`. The dependency now excludes 6.12.0.
  If you installed on 3.10/3.11 since 8 October, upgrading the widget
  downgrades PySide6 to a working release automatically, or run
  `pip install 'PySide6-Essentials!=6.12.0'`.
- **Sonnet 5.5 is tabled, and its cache reads cost half what the widget
  showed.** Untabled, every refresh logged an "unknown model" warning and the
  Sonnet fallback billed it as Sonnet 5. Sonnet 5.5 is $2/$10 like Sonnet 5,
  but like Opus 5.5 its cache hits are 0.05x input: $0.10, not $0.20.
  Thanks @Vincentcchu (#31).
- **Haiku 5.5 was shown at about 10x its real cost.** It was untabled, so it
  was billed as Haiku 4.5 ($1/$5). It is now priced at its own rates,
  including its prompt-length tier: up to 100,000 prompt tokens a request is
  $0.10/$0.50, over that the whole request is $0.50/$2.50. The tier is
  decided for each request on its own, cache reads and writes included, as
  Anthropic bills it.
- **Mythos 5.1 and Mythos 5 were under-reported 3.3x.** They matched no model
  family and fell all the way to the generic Sonnet fallback. They are now
  tabled at their $10/$50 tier.

Every row of Anthropic's model pricing table now matches the widget's
exactly.

## 0.13.1

### Fixed

- **`claude-opus-5-5` priced at its own tier** ($4/$20, cache reads $0.20).
  Untabled, the Opus family fallback billed it at Opus 5's rates: 25% high on
  input/output and 2.5x high on cache reads ($0.50 vs $0.20). Claude Code
  traffic is mostly cache reads, so Opus 5.5 cost showed about **2x** its real
  figure (a real day: $43.09 shown vs $20.94 actual). It also logged an
  "unknown model" warning every refresh. Cross-checked against the cost
  Claude Code itself records for a session: identical to the cent.
  Thanks @boordg (#30).

### Changed

- **The family fallback now leans toward over-counting.** It only ever prices
  a model release the table has not caught up with yet, and for those it now
  uses the most expensive current member of the family: Opus 5 rather than
  the cheaper Opus 5.5, and Fable 5 rather than Fable 5.1. In a spend tool an
  over-count is the safer mistake, and the unknown-model warning still fires
  so the release gets tabled. No current model is affected.

## 0.13.0

### Fixed

- **Token and cost figures were roughly 2.7x too high.** Claude Code writes one
  JSONL line per content block of a response (text, `tool_use`, thinking), and
  every one of those lines repeats that response's full `usage` block. Both
  token scans summed every line, so today/week/month tokens, cost, and the
  month-to-date budget were all inflated. On a week of real logs there were
  about 2.2 assistant lines per unique `message.id`. They now count each
  `message.id` once, the same key the cost ticker and the live badge already
  deduped on. **Your numbers will drop sharply after upgrading. The new ones
  are the correct ones.** Thanks @boordg (#26).
- **Task subagent spend was missing entirely.** Subagent transcripts live under
  `projects/<project>/<session>/subagents/`, which the old glob never reached,
  so everything your Task subagents burned was invisible. They are separate API
  calls with their own message ids, not replays of the parent's usage, and they
  are now scanned and attributed to the parent project. The cost ticker and the
  live tok/min rate cover them too, so the tape adds up to the today figure.
  Thanks @boordg (#26).
- **Fable 5.1 cost several times too much.** `claude-fable-5-1` was not in the
  pricing table, so it inherited Fable 5's `$1.00`/MTok cache-read rate. Fable
  5.1 bills cache hits at 0.025x input, which is `$0.25`/MTok, and since Claude
  Code traffic is mostly cache reads this dominated the figure. Thanks @boordg
  (#27).
- **Older model ids were priced as their newest sibling.** The family fallback
  sends an unknown id to the most recent member of its family, which is wrong
  for the dated ids Claude Code logs still carry (Task subagents often pin
  them): Sonnet 4.5 was billed at Sonnet 5's `$2`/`$10` instead of `$3`/`$15`,
  and Opus 4.0/4.1 at Opus 5's `$5`/`$25` instead of `$15`/`$75`. Sonnet 4.5/4,
  Opus 4.5/4.1/4 and undated `claude-haiku-4-5` are now tabled, and a trailing
  `-YYYYMMDD` is stripped before lookup. Thanks @boordg (#27).
- **1-hour cache writes were under-priced.** They bill at 2x input, not the
  5-minute 1.25x. The collector now carries
  `usage.cache_creation.ephemeral_1h_input_tokens` as a subset bucket and the
  cost card shows the blended rate, so tokens x rate still equals the dollar
  figure in all 11 themes.
- **A `~` in `claude_dir` silently zeroed everything.** `"claude_dir":
  "~/.claude"` in `config.json` was used literally, failed `os.path.isdir`, and
  every local figure read 0 with no error. The same trap in
  `statusline_cache_path` is fixed too. Thanks @boordg (#29).
- **A resumed session could hide a turn's real usage.** Resuming or forking
  writes a replay of the turn with every usage field zeroed, and whichever copy
  the scan reached first won. One message in testing carried 956k cache-read
  tokens in one file and zeros in another, and the zeroed copy won on directory
  order. Only real usage claims a message id now, so the result no longer
  depends on filesystem ordering.
- **`tests/test_config.py` did not collect on Windows**, erroring out all 30
  tests in the file because the `skipIf` called `os.getuid()` at class
  definition time. CI is Ubuntu-only so it never showed up. Thanks @boordg
  (#29).

### Changed

- **The AI weekly report is now opt-in** (`"ai_report_enabled": true`, off by
  default). It spends your Claude subscription credentials on a Haiku call
  without ever asking, and a failed attempt cached nothing so it retried on
  every refresh. It now has a one-hour cooldown after a failure, and turning it
  off also stops a cached report from being displayed. Thanks @boordg (#28).

## 0.12.5

### Fixed
- **"Show cost ticker" now works in the designed skins** — terminal,
  dashboard, hud, receipt and brutalist. The toggle only ever applied to the 5
  built-in themes: skins painted the ticker unconditionally, and each refresh
  restarted the marquee timer, so switching it off paused the strip for a few
  seconds and then it scrolled on regardless. With the toggle off the skin now
  gets no ticker items and the marquee stays stopped. The panel keeps its
  height on the skins by design — the strip is part of each skin's
  composition, so the row goes blank rather than the panel collapsing.
  Thanks @carr-james (#25).
- **`claude-opus-5` priced explicitly** ($5/$25, same tier as Opus 4.8) —
  the family fallback already landed on the right numbers, but every refresh
  logged an "unknown model" warning; that's gone.

## 0.12.4

### Fixed
- **`budget_projection` and `burn_alert` webhooks actually fire.** Both were
  advertised in 0.11.0, but `KNOWN_EVENTS` was never extended and the
  dispatcher silently drops unknown events — so neither webhook ever sent a
  single request. Found by a documentation audit cross-checking the config
  comment against the dispatcher; a regression test now pins every advertised
  event to the gate.
- **`show_news` added to `DEFAULT_CONFIG`** — it was the only documented key
  missing from the defaults dict (runtime behavior was already correct via
  `cfg.get` fallbacks; now `config.json.example` and the defaults agree).

### Docs
- **The GitHub wiki is retired** to a single pointer page — it had drifted
  several releases behind the README and started giving wrong answers. Its
  unique content moved into the repo first: an expanded README (FAQ section
  with a corrected privacy answer, systemd/autostart recipe, off-screen and
  Codex troubleshooting entries), `CONTRIBUTING.md`, `SECURITY.md`,
  issue/PR templates, and `docs/RELEASING.md` (maintainer checklist,
  replacing `docs/homebrew.md` and fixing its wrong sdist filename in the
  sha256 step). ~40 more stale spots fixed across README (stray Turkish
  heading, duplicate config row, outdated window-flag/Wayland/fallback
  claims). CI now runs the suite on Python 3.10–3.12 for every push and PR.

## 0.12.3

### Fixed
- **"Always on top" did nothing on X11 — and the menu looked out of sync.**
  The OSD was unconditionally typed `_NET_WM_WINDOW_TYPE_NOTIFICATION` to keep
  it out of the dock / taskbar / Alt-Tab, but X11 window managers also stack
  notification windows in a layer *above* normal ones. So turning the toggle
  off left the OSD pinned on top regardless, and the right-click menu — which
  correctly showed the setting as off — read as "wrong" against a window that
  refused to sink. Dropping the `WindowStaysOnTopHint`/`BypassWindowManagerHint`
  flags in 0.9.1 (#13) was necessary but not sufficient. The window type now
  tracks the setting: `Notification` when pinned, and unpinned it falls back to
  the `_NET_WM_WINDOW_TYPE_UTILITY` that `Qt.Tool` already sets — which
  taskbars skip just the same, so nothing is lost but the pin.

## 0.12.2

### Fixed
- **Window dragging on native Wayland.** Under a native Wayland session
  (`QT_QPA_PLATFORM=wayland`) the OSD couldn't be dragged — Wayland forbids a
  client moving its own window. It now hands the drag to the compositor via
  `QWindow.startSystemMove()`, leaving the X11 / macOS / Windows path unchanged.
  Thanks @hdogan (#23). (The drop position isn't persisted as a "custom" spot on
  Wayland, since a client can't read its own global coordinates there.)

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
