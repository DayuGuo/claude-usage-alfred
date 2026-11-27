import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


STATUSLINE = Path(__file__).resolve().parents[1] / "statusline.py"


class StatusLineCacheTests(unittest.TestCase):
    def test_null_cache_is_rebuilt_from_current_reading(self):
        reading = {"used_percentage": 12}
        payload = {"rate_limits": {"five_hour": reading}}

        with tempfile.TemporaryDirectory() as config_dir:
            cache = Path(config_dir) / "usage-limits.json"
            cache.write_text("null", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(STATUSLINE)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "CLAUDE_CONFIG_DIR": config_dir,
                    "CLAUDE_USAGE_STATUSLINE_CMD": "",
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("5h 12%", result.stdout)
            self.assertEqual(json.loads(cache.read_text())["five_hour"], reading)
