#!/usr/bin/env python3
"""Claude Usage Desktop Widget -- system tray app for Claude Code usage tracking.

This file is kept for developers who clone the repo and run
``python3 main.py``.  Production users install via ``pip install
claude-usage-widget`` and run the ``claude-usage`` console script, which
points at ``claude_usage.cli:main`` directly.
"""

from __future__ import annotations

import sys

from claude_usage.cli import main

if __name__ == "__main__":
    sys.exit(main())
