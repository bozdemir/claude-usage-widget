#!/usr/bin/env python3
"""Claude Usage Widget — repo-local entry point.

Production users install via ``pip install claude-usage-widget`` and invoke
the ``claude-usage`` console script.  This file exists so developers who
clone the repository can still run ``python3 main.py`` directly.
"""

from __future__ import annotations

import sys

from claude_usage.cli import main

if __name__ == "__main__":
    sys.exit(main())
