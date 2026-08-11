# Security Policy

## Supported versions

Only the latest release on PyPI is supported with security fixes.

## Reporting a vulnerability

Please **do not** open a public issue for security-sensitive reports
(anything involving the OAuth token handling, the localhost API, webhook
dispatch, or data redaction).

Instead, use GitHub's private vulnerability reporting: **Security →
[Report a vulnerability](https://github.com/bozdemir/claude-usage-widget/security/advisories/new)**
on this repository. You'll get a response within a few days.

## Scope notes

- The widget never stores credentials of its own; it reads Claude Code's OAuth
  token (env var → `~/.claude/.credentials.json` → macOS Keychain) and keeps it
  in memory only.
- Tokens and raw prompt text are redacted from `--json`, `--field`,
  `--statusline`, and the localhost API at the serialization boundary — a
  report that shows either leaking through any surface is always in scope.
