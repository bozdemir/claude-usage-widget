"""Tests for the claude_usage.config module.

Covers default values, file-based config loading, merge behaviour, error
handling, and immutability of the DEFAULT_CONFIG singleton.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from typing import Any

from claude_usage.config import DEFAULT_CONFIG, load_config, save_config, user_config_path


class TestDefaultConfig(unittest.TestCase):
    """Tests that DEFAULT_CONFIG contains all expected keys with sane values."""

    def test_has_required_keys(self) -> None:
        """DEFAULT_CONFIG contains all mandatory configuration keys."""
        required_keys = [
            "claude_dir",
            "daily_message_limit",
            "weekly_message_limit",
            "daily_token_limit",
            "weekly_token_limit",
            "refresh_seconds",
        ]
        for key in required_keys:
            with self.subTest(key=key):
                self.assertIn(key, DEFAULT_CONFIG)

    def test_has_osd_keys(self) -> None:
        """DEFAULT_CONFIG includes osd_opacity and osd_scale with their expected default values."""
        self.assertIn("osd_opacity", DEFAULT_CONFIG)
        self.assertIn("osd_scale", DEFAULT_CONFIG)
        self.assertEqual(DEFAULT_CONFIG["osd_opacity"], 0.75)
        self.assertEqual(DEFAULT_CONFIG["osd_scale"], 1.0)

    def test_claude_dir_is_absolute(self) -> None:
        """The default claude_dir value is an absolute path (tilde has been expanded)."""
        self.assertTrue(
            os.path.isabs(DEFAULT_CONFIG["claude_dir"]),
            f"Expected absolute path, got: {DEFAULT_CONFIG['claude_dir']}",
        )

    def test_claude_dir_does_not_contain_tilde(self) -> None:
        """The default claude_dir does not contain a literal '~' character."""
        self.assertNotIn("~", DEFAULT_CONFIG["claude_dir"])

    def test_numeric_limits_are_positive(self) -> None:
        """All numeric limit/threshold defaults are positive numbers."""
        numeric_keys = [
            "daily_message_limit",
            "weekly_message_limit",
            "daily_token_limit",
            "weekly_token_limit",
            "refresh_seconds",
        ]
        for key in numeric_keys:
            with self.subTest(key=key):
                self.assertGreater(DEFAULT_CONFIG[key], 0)

    def test_osd_opacity_within_valid_range(self) -> None:
        """osd_opacity is between 0.0 and 1.0 inclusive."""
        self.assertGreaterEqual(DEFAULT_CONFIG["osd_opacity"], 0.0)
        self.assertLessEqual(DEFAULT_CONFIG["osd_opacity"], 1.0)

    def test_osd_scale_is_positive(self) -> None:
        """osd_scale is a positive number."""
        self.assertGreater(DEFAULT_CONFIG["osd_scale"], 0.0)


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config covering file reading, merging, and error paths."""

    def test_load_from_valid_file_overrides_defaults(self) -> None:
        """Values from a JSON config file override the corresponding defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"daily_message_limit": 999}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["daily_message_limit"], 999)
            # Unset defaults are still present
            self.assertIn("refresh_seconds", cfg)
            self.assertEqual(cfg["refresh_seconds"], DEFAULT_CONFIG["refresh_seconds"])
        finally:
            os.unlink(path)

    def test_missing_file_returns_defaults(self) -> None:
        """load_config returns DEFAULT_CONFIG (as a new dict) when the path does not exist."""
        cfg = load_config("/nonexistent/path.json")
        self.assertEqual(cfg, DEFAULT_CONFIG)

    def test_missing_file_does_not_return_same_object(self) -> None:
        """The dict returned for a missing file is a copy, not the DEFAULT_CONFIG singleton itself."""
        cfg = load_config("/nonexistent/path.json")
        self.assertIsNot(cfg, DEFAULT_CONFIG)

    def test_malformed_json_returns_defaults_with_warning(self) -> None:
        """Malformed JSON causes load_config to return defaults and emit a WARNING to stderr."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{this is not valid json")
            path = f.name
        try:
            import io

            captured = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = captured
            try:
                cfg = load_config(path)
            finally:
                sys.stderr = old_stderr

            self.assertEqual(cfg, DEFAULT_CONFIG)
            warning_output = captured.getvalue()
            self.assertIn("WARNING", warning_output)
        finally:
            os.unlink(path)

    def test_extra_unknown_keys_are_included(self) -> None:
        """Unrecognised keys from the config file are merged into the returned dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"unknown_key": "some_value", "another_key": 42}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["unknown_key"], "some_value")
            self.assertEqual(cfg["another_key"], 42)
            self.assertIn("refresh_seconds", cfg)
        finally:
            os.unlink(path)

    def test_osd_opacity_and_osd_scale_from_file(self) -> None:
        """osd_opacity and osd_scale values are loaded correctly from a config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"osd_opacity": 0.5, "osd_scale": 2.0}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["osd_opacity"], 0.5)
            self.assertEqual(cfg["osd_scale"], 2.0)
            self.assertIn("daily_message_limit", cfg)
        finally:
            os.unlink(path)

    def test_empty_json_object_returns_all_defaults(self) -> None:
        """An empty JSON object {} merges nothing, so all defaults are preserved."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg, DEFAULT_CONFIG)
        finally:
            os.unlink(path)

    def test_overriding_all_defaults(self) -> None:
        """Every default key can be overridden by the config file."""
        overrides: dict[str, Any] = {
            "claude_dir": "/custom/path",
            "daily_message_limit": 1,
            "weekly_message_limit": 2,
            "daily_token_limit": 3,
            "weekly_token_limit": 4,
            "refresh_seconds": 5,
            "osd_opacity": 0.1,
            "osd_scale": 3.0,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(overrides, f)
            path = f.name
        try:
            cfg = load_config(path)
            for key, value in overrides.items():
                with self.subTest(key=key):
                    self.assertEqual(cfg[key], value)
        finally:
            os.unlink(path)

    def test_null_value_overrides_default(self) -> None:
        """A JSON null value overrides the default for that key (sets it to None)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"daily_message_limit": None}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertIsNone(cfg["daily_message_limit"])
        finally:
            os.unlink(path)

    def test_load_config_does_not_mutate_default_config(self) -> None:
        """Loading a config file must not alter the DEFAULT_CONFIG singleton."""
        original_copy: dict[str, Any] = dict(DEFAULT_CONFIG)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"daily_message_limit": 12345, "custom_field": "hello"}, f)
            path = f.name
        try:
            _ = load_config(path)
            self.assertEqual(DEFAULT_CONFIG, original_copy)
            self.assertNotIn("custom_field", DEFAULT_CONFIG)
        finally:
            os.unlink(path)

    def test_directory_path_treated_as_missing(self) -> None:
        """When the path points to a directory (not a file), defaults are returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = load_config(tmpdir)
            self.assertEqual(cfg, DEFAULT_CONFIG)

    def test_config_with_nested_dict_value(self) -> None:
        """A config file containing a nested dict merges it as-is into the result."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"custom_nested": {"a": 1, "b": [2, 3]}}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["custom_nested"], {"a": 1, "b": [2, 3]})
            self.assertIn("refresh_seconds", cfg)
        finally:
            os.unlink(path)

    def test_config_with_boolean_values(self) -> None:
        """Boolean values in a config file are preserved correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"debug_mode": True, "verbose": False}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertIs(cfg["debug_mode"], True)
            self.assertIs(cfg["verbose"], False)
        finally:
            os.unlink(path)

    def test_config_with_string_number_values(self) -> None:
        """Numeric values stored as strings in JSON are loaded as strings (no auto-coercion)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"daily_message_limit": "500"}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["daily_message_limit"], "500")
            self.assertIsInstance(cfg["daily_message_limit"], str)
        finally:
            os.unlink(path)

    @unittest.skipIf(os.getuid() == 0, "Cannot test permission errors as root")
    def test_unreadable_file_returns_defaults_with_warning(self) -> None:
        """A file that exists but is not readable returns defaults and warns."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"daily_message_limit": 42}, f)
            path = f.name
        try:
            os.chmod(path, 0o000)
            import io

            captured = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = captured
            try:
                cfg = load_config(path)
            finally:
                sys.stderr = old_stderr

            self.assertEqual(cfg, DEFAULT_CONFIG)
            warning_output = captured.getvalue()
            self.assertIn("WARNING", warning_output)
        finally:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            os.unlink(path)

    def test_multiple_loads_are_independent(self) -> None:
        """Two successive calls to load_config return independent dict objects."""
        cfg_a = load_config("/nonexistent/a.json")
        cfg_b = load_config("/nonexistent/b.json")
        cfg_a["daily_message_limit"] = 999999
        self.assertNotEqual(cfg_b["daily_message_limit"], 999999)


class TestSaveConfig(unittest.TestCase):
    """Tests for :func:`save_config` — atomic writes, dir creation, round-trips."""

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "subdir", "config.json")
            cfg = dict(DEFAULT_CONFIG)
            cfg["theme"] = "dracula"
            save_config(path, cfg)
            loaded = load_config(path)
            self.assertEqual(loaded["theme"], "dracula")

    def test_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a", "b", "c", "config.json")
            save_config(path, {"theme": "nord"})
            self.assertTrue(os.path.isfile(path))

    def test_atomic_write_leaves_no_tmp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            save_config(path, {"theme": "default"})
            leftovers = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_overwrites_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            save_config(path, {"theme": "dracula"})
            save_config(path, {"theme": "nord"})
            loaded = load_config(path)
            self.assertEqual(loaded["theme"], "nord")


class TestUserConfigPath(unittest.TestCase):
    """Tests for :func:`user_config_path` — XDG awareness + fallback."""

    def test_respects_xdg_config_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = tmp
            try:
                path = user_config_path()
                self.assertTrue(path.startswith(tmp + os.sep))
                self.assertTrue(path.endswith("config.json"))
            finally:
                if original is None:
                    del os.environ["XDG_CONFIG_HOME"]
                else:
                    os.environ["XDG_CONFIG_HOME"] = original

    def test_falls_back_to_dot_config(self) -> None:
        original = os.environ.pop("XDG_CONFIG_HOME", None)
        try:
            path = user_config_path()
            self.assertIn(os.path.join(".config", "claude-usage", "config.json"), path)
        finally:
            if original is not None:
                os.environ["XDG_CONFIG_HOME"] = original


if __name__ == "__main__":
    unittest.main()
