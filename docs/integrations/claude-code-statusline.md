# Claude Code statusLine

Show your live Claude usage right inside the Claude Code CLI, on the built-in
status line, using `claude-usage --statusline`.

`--statusline` collects once and prints a single compact line, then exits:

```
S 42% · W 18% · $3.21
```

- `S` — current 5-hour **session** utilisation
- `W` — 7-day **weekly** utilisation
- `$` — **today's** cost (locally computed, so it shows even when offline)
- a model-scoped bar (e.g. `· Fable 55%`) is appended only when Anthropic
  reports one

## Setup

Add a `statusLine` command to your Claude Code `settings.json`
(`~/.claude/settings.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "claude-usage --statusline"
  }
}
```

That's it — Claude Code runs the command on each turn and shows its output.

## Notes

- **One-shot:** the command collects once and exits; it never launches the GUI
  (even if `--detach` is also present).
- **Latency:** it does the full usage scan (local conversation JSONL walk plus
  the `/api/oauth/usage` call), so expect roughly 0.3–0.7 s in the common case.
- **Graceful degradation:** if the API is rate-limited it falls back to the
  last-known session/weekly values from `usage-history.jsonl`. With no
  last-known sample at all (first run / no credentials) the percentages render
  as `S --% · W --%`, but today's cost is still shown.
- **Data source:** it derives everything from `~/.claude` (the same token and
  history the widget uses); it does **not** read the session JSON that Claude
  Code pipes to the command on stdin.
- **Privacy:** output goes through the same redaction as `--json` / the
  localhost API — no raw prompt text is ever emitted.
