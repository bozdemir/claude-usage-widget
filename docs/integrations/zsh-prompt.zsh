# Drop this into ~/.zshrc. Adds a right-prompt segment showing session usage.
# Requires claude-usage to be on PATH.

_claude_usage_rprompt() {
  command -v claude-usage >/dev/null 2>&1 || return

  local pct
  pct=$(claude-usage --field session_utilization 2>/dev/null) || return
  [[ -z "$pct" ]] && return

  local pct_int
  pct_int=$(awk -v p="$pct" 'BEGIN { printf "%d", p * 100 }')

  if   (( pct_int < 60 )); then echo "%F{green}C:${pct_int}%%%f"
  elif (( pct_int < 85 )); then echo "%F{yellow}C:${pct_int}%%%f"
  else                          echo "%F{red}C:${pct_int}%%%f"
  fi
}

setopt PROMPT_SUBST
RPROMPT='$(_claude_usage_rprompt)'
