"""Check GitHub Releases for a newer version of claude-usage-widget.

Pure networking — runs once on startup from a daemon thread, never blocks
the UI. Uses only urllib (stdlib).
"""

from __future__ import annotations

import json
import re
from typing import Tuple
from urllib.request import Request, urlopen


RELEASE_URL = "https://api.github.com/repos/bozdemir/claude-usage-widget/releases/latest"


_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _parse(version: str) -> tuple[int, int, int] | None:
    m = _SEMVER_RE.match(version.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _semver_greater(latest: str, current: str) -> bool:
    """Return True iff *latest* is a strictly greater semver than *current*."""
    a, b = _parse(latest), _parse(current)
    if a is None or b is None:
        return False
    return a > b


def check_latest_version(current: str) -> Tuple[str | None, bool]:
    """Fetch the latest release tag and compare against *current*.

    Returns ``(tag, update_available)``. Returns ``(None, False)`` on any
    network or parse error.
    """
    req = Request(RELEASE_URL, headers={"User-Agent": "claude-usage-widget"})
    try:
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None, False

    tag = data.get("tag_name") if isinstance(data, dict) else None
    if not isinstance(tag, str):
        return None, False
    return tag, _semver_greater(tag, current)
