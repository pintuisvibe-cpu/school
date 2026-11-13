"""Run the dependency-free Node browser simulation when Node is available."""
import shutil
import subprocess
import unittest
from pathlib import Path


class FrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_admin_and_scanner(self):
        script = Path(__file__).with_name("frontend_smoke.js")
        completed = subprocess.run(
            ["node", str(script)], text=True, capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
