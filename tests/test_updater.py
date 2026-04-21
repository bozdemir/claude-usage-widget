"""Tests for the GitHub Releases update checker."""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from claude_usage.updater import _semver_greater, check_latest_version


class TestSemverCompare(unittest.TestCase):
    def test_greater_minor(self):
        self.assertTrue(_semver_greater("0.3.0", "0.2.9"))

    def test_greater_patch(self):
        self.assertTrue(_semver_greater("0.2.10", "0.2.9"))

    def test_equal_is_not_greater(self):
        self.assertFalse(_semver_greater("0.2.0", "0.2.0"))

    def test_pre_release_ignored(self):
        self.assertTrue(_semver_greater("v0.3.0-rc1", "0.2.0"))

    def test_v_prefix_stripped(self):
        self.assertTrue(_semver_greater("v1.0.0", "0.9.9"))

    def test_malformed_returns_false(self):
        self.assertFalse(_semver_greater("garbage", "0.1.0"))


class TestCheckLatestVersion(unittest.TestCase):
    def _fake_response(self, tag: str) -> MagicMock:
        payload = json.dumps({"tag_name": tag}).encode()
        m = MagicMock()
        m.__enter__.return_value = BytesIO(payload)
        m.__exit__.return_value = False
        return m

    def test_returns_tag_when_available(self):
        with patch("claude_usage.updater.urlopen", return_value=self._fake_response("v0.3.0")):
            result = check_latest_version("0.2.0")
        self.assertEqual(result, ("v0.3.0", True))

    def test_returns_no_update_when_equal(self):
        with patch("claude_usage.updater.urlopen", return_value=self._fake_response("v0.2.0")):
            result = check_latest_version("0.2.0")
        self.assertEqual(result, ("v0.2.0", False))

    def test_network_failure_returns_none(self):
        with patch("claude_usage.updater.urlopen", side_effect=OSError("dns fail")):
            result = check_latest_version("0.2.0")
        self.assertEqual(result, (None, False))


if __name__ == "__main__":
    unittest.main()
