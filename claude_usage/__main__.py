"""Enable `python -m claude_usage` as an equivalent entry point to the CLI."""

from __future__ import annotations

import sys

from claude_usage.cli import main

if __name__ == "__main__":
    sys.exit(main())
