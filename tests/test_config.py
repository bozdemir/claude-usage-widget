"""Tests for the claude_usage.config module, covering default values and file-based config loading."""

import json
import os
import tempfile
import unittest

from claude_usage.config import load_config, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):
    def test_default_config_has_required_keys(self):
        """Verifies that DEFAULT_CONFIG contains all mandatory configuration keys."""
        cfg = DEFAULT_CONFIG
        self.assertIn("claude_dir", cfg)
        self.assertIn("daily_message_limit", cfg)
        self.assertIn("weekly_message_limit", cfg)
        self.assertIn("daily_token_limit", cfg)
        self.assertIn("refresh_seconds", cfg)

    def test_load_config_from_file(self):
        """Verifies that values from a JSON config file override defaults while keeping unset defaults intact."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"daily_message_limit": 999}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["daily_message_limit"], 999)
            # defaults still present
            self.assertIn("refresh_seconds", cfg)
        finally:
            os.unlink(path)

    def test_load_config_missing_file_returns_defaults(self):
        """Verifies that load_config returns DEFAULT_CONFIG unchanged when the given path does not exist."""
        cfg = load_config("/nonexistent/path.json")
        self.assertEqual(cfg, DEFAULT_CONFIG)

    def test_load_config_malformed_json_returns_defaults_with_warning(self):
        """Verifies that malformed JSON causes load_config to return defaults and emit a WARNING to stderr."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{this is not valid json")
            path = f.name
        try:
            import io
            import sys
            captured = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = captured
            try:
                cfg = load_config(path)
            finally:
                sys.stderr = old_stderr
            # Should return defaults without crashing
            self.assertEqual(cfg, DEFAULT_CONFIG)
            # Should have printed a warning
            warning_output = captured.getvalue()
            self.assertIn("WARNING", warning_output)
        finally:
            os.unlink(path)

    def test_load_config_extra_unknown_keys_are_included(self):
        """Verifies that unrecognised keys from the config file are merged into the returned config dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"unknown_key": "some_value", "another_key": 42}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["unknown_key"], "some_value")
            self.assertEqual(cfg["another_key"], 42)
            # Defaults still present
            self.assertIn("refresh_seconds", cfg)
        finally:
            os.unlink(path)

    def test_load_config_osd_opacity_and_osd_scale(self):
        """Verifies that osd_opacity and osd_scale values are loaded correctly from a config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"osd_opacity": 0.5, "osd_scale": 2.0}, f)
            path = f.name
        try:
            cfg = load_config(path)
            self.assertEqual(cfg["osd_opacity"], 0.5)
            self.assertEqual(cfg["osd_scale"], 2.0)
            # Other defaults still present
            self.assertIn("daily_message_limit", cfg)
        finally:
            os.unlink(path)

    def test_default_config_has_osd_keys(self):
        """Verifies that DEFAULT_CONFIG includes osd_opacity and osd_scale with their expected default values."""
        self.assertIn("osd_opacity", DEFAULT_CONFIG)
        self.assertIn("osd_scale", DEFAULT_CONFIG)
        self.assertEqual(DEFAULT_CONFIG["osd_opacity"], 0.75)
        self.assertEqual(DEFAULT_CONFIG["osd_scale"], 1.0)


if __name__ == "__main__":
    unittest.main()
