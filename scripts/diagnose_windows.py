#!/usr/bin/env python3
"""Diagnostic for Windows (or any OS) — dumps the state the widget sees.

Run with:  python scripts/diagnose_windows.py
Safe to share the output for debugging — no prompt content, no tokens.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def main() -> None:
    print("=" * 60)
    print("claude-usage Windows diagnostic")
    print("=" * 60)

    print(f"\n[env]")
    print(f"  platform      : {sys.platform}")
    print(f"  system        : {platform.system()} {platform.release()}")
    print(f"  python        : {sys.version.split()[0]}")
    print(f"  cwd           : {os.getcwd()}")
    print(f"  ~             : {os.path.expanduser('~')}")
    print(f"  os.sep        : {os.sep!r}")
    print(f"  USERPROFILE   : {os.environ.get('USERPROFILE', '(unset)')}")

    claude_dir = os.path.expanduser("~/.claude")
    print(f"\n[claude_dir]  : {claude_dir}")
    print(f"  exists       : {os.path.isdir(claude_dir)}")

    creds_path = os.path.join(claude_dir, ".credentials.json")
    print(f"\n[credentials] : {creds_path}")
    print(f"  exists       : {os.path.isfile(creds_path)}")
    if os.path.isfile(creds_path):
        try:
            with open(creds_path, encoding="utf-8") as f:
                j = json.load(f)
            oauth = j.get("claudeAiOauth") or {}
            print(f"  has token    : {bool(oauth.get('accessToken'))}")
            print(f"  subscription : {oauth.get('subscriptionType', '?')}")
        except Exception as e:
            print(f"  parse error  : {e!r}")

    projects_dir = os.path.join(claude_dir, "projects")
    print(f"\n[projects]    : {projects_dir}")
    if os.path.isdir(projects_dir):
        entries = os.listdir(projects_dir)
        print(f"  count        : {len(entries)}")
        for i, name in enumerate(sorted(entries)[:5]):
            sample_path = os.path.join(projects_dir, name)
            subdirs = 0
            jsonls = 0
            try:
                for f in os.listdir(sample_path):
                    p = os.path.join(sample_path, f)
                    if os.path.isdir(p):
                        subdirs += 1
                    elif f.endswith(".jsonl"):
                        jsonls += 1
            except OSError:
                pass
            print(f"  [{i}] {name!r}  (subdirs={subdirs} jsonls={jsonls})")
        if len(entries) > 5:
            print(f"  ... +{len(entries) - 5} more")
    else:
        print("  (not found)")

    sessions_dir = os.path.join(claude_dir, "sessions")
    print(f"\n[sessions]    : {sessions_dir}")
    if os.path.isdir(sessions_dir):
        files = [f for f in os.listdir(sessions_dir) if f.endswith(".json")]
        print(f"  count        : {len(files)}")
        for fname in files[:3]:
            try:
                with open(os.path.join(sessions_dir, fname), encoding="utf-8") as f:
                    sess = json.load(f)
                print(f"  - {fname}: pid={sess.get('pid')}  cwd_len={len(str(sess.get('cwd', '')))}")
            except Exception as e:
                print(f"  - {fname}: parse error {e!r}")

    print("\n[widget smoke]")
    try:
        from claude_usage import __version__
        print(f"  version      : {__version__}")
    except Exception as e:
        print(f"  import error : {e!r}")
        return

    try:
        from claude_usage.collector import collect_all
        from claude_usage.config import load_config
        cfg = load_config("")  # returns DEFAULT_CONFIG
        stats = collect_all(cfg)
        print(f"  collect_all  : ok")
        print(f"  today_msgs   : {stats.today_messages}")
        print(f"  active_subs  : {stats.active_subagent_count}")
        print(f"  rate_err     : {stats.rate_limit_error or '(none)'}")
        print(f"  session_util : {stats.session_utilization:.2f}")
    except Exception as e:
        import traceback
        print(f"  collect_all  : FAILED")
        print(f"  error        : {e!r}")
        print("  traceback    :")
        traceback.print_exc()

    print("\n[done]")
    print("Paste this output back. No prompt text or tokens are included.")


if __name__ == "__main__":
    main()
