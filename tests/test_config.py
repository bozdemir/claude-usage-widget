import json
import os
import tempfile
import unittest

from claude_usage.config import load_config, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):
    def test_default_config_has_required_keys(self):
        cfg = DEFAULT_CONFIG
        self.assertIn("claude_dir", cfg)
        self.assertIn("daily_message_limit", cfg)
        self.assertIn("weekly_message_limit", cfg)
        self.assertIn("daily_token_limit", cfg)
        self.assertIn("refresh_seconds", cfg)

    def test_load_config_from_file(self):
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
        cfg = load_config("/nonexistent/path.json")
        self.assertEqual(cfg, DEFAULT_CONFIG)


if __name__ == "__main__":
    unittest.main()
