import pytest
from claude_usage.providers.base import window_label

@pytest.mark.parametrize("minutes,expected", [
    (43200, "30d"),   # Codex primary (monthly)
    (10080, "7d"),    # weekly
    (300, "5h"),      # 5-hour session
    (60, "1h"),
    (90, "90m"),      # not a whole hour → minutes
    (0, ""),
    (-5, ""),
])
def test_window_label(minutes, expected):
    assert window_label(minutes) == expected
