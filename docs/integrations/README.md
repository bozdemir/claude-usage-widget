# Shell and Status-Bar Integrations

These snippets pull live usage data from either the CLI (`claude-usage
--field …`) or the localhost JSON API (`curl http://127.0.0.1:8765/usage`).

| Integration | Backend | Refresh cadence |
|-------------|---------|-----------------|
| zsh prompt  | CLI     | on every prompt |
| tmux        | CLI     | 15 s (tmux refresh) |
| waybar      | CLI     | 30 s (waybar interval) |
| polybar     | CLI     | 30 s |
| starship    | CLI     | on every prompt |

Any tool that can `GET` HTTP (Grafana, Home Assistant, curl in cron) can
pull the JSON API directly. Enable it with `"api_server_enabled": true`
in `config.json`.
