"""Prevent insecure or ephemeral production startup if Render env is incomplete."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class RenderConfigurationTests(unittest.TestCase):
    def run_app(self, **settings):
        # Never inherit credentials from the developer machine into these tests.
        env = {k: v for k, v in os.environ.items() if k not in (
            "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY",
            "SUPABASE_KEY", "API_ACCESS_TOKEN", "RENDER",
        )}
        env.update(RENDER="true", **settings)
        return subprocess.run(
            [sys.executable, "-c", "import main; print(main.health())"],
            cwd=Path(__file__).resolve().parent.parent,
            env=env, capture_output=True, text=True, timeout=15, check=False,
        )

    def test_render_requires_persistent_storage(self):
        result = self.run_app()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SUPABASE_URL", result.stderr)
        self.assertIn("SUPABASE_SERVICE_KEY", result.stderr)

    def test_render_requires_auth_even_with_supabase_configured(self):
        result = self.run_app(
            SUPABASE_URL="https://fake.supabase.co", SUPABASE_SERVICE_KEY="sb_secret_not_a_real_key"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("API_ACCESS_TOKEN", result.stderr)

    def test_render_with_all_settings_starts_in_supabase_mode(self):
        result = self.run_app(
            SUPABASE_URL="https://fake.supabase.co",
            SUPABASE_SERVICE_KEY="sb_secret_not_a_real_key", API_ACCESS_TOKEN="test-only-token"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'storage': 'supabase'", result.stdout)
        self.assertIn("'auth_required': True", result.stdout)


if __name__ == "__main__":
    unittest.main()
