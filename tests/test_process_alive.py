"""Tests for the platform-safe process-liveness probe."""

from __future__ import annotations

import os
import sys
import unittest

from claude_usage.collector import _process_alive


class TestProcessAlive(unittest.TestCase):
    def test_negative_pid_is_dead(self) -> None:
        self.assertFalse(_process_alive(-1))

    def test_zero_pid_is_dead(self) -> None:
        self.assertFalse(_process_alive(0))

    def test_own_pid_is_alive(self) -> None:
        self.assertTrue(_process_alive(os.getpid()))

    @unittest.skipIf(sys.platform == "win32", "POSIX-only PID guarantee")
    def test_unlikely_pid_is_dead(self) -> None:
        # On POSIX, PIDs are bounded by /proc/sys/kernel/pid_max; 999_999_999
        # is reliably unused. On Windows the handle is 32-bit and this test
        # could theoretically collide, so we skip.
        self.assertFalse(_process_alive(999_999_999))


if __name__ == "__main__":
    unittest.main()
