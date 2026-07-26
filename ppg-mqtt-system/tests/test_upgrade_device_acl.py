import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upgrade-device-acl.sh"


class UpgradeDeviceAclTest(unittest.TestCase):
    def test_missing_device_block_is_restored_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "scripts" / SCRIPT.name
            acl = root / "mosquitto" / "config" / "acl"
            script.parent.mkdir()
            acl.parent.mkdir(parents=True)
            shutil.copy2(SCRIPT, script)
            acl.write_text(
                "user storage\n"
                "topic read ppg/+/raw\n",
                encoding="utf-8",
            )

            for _ in range(2):
                subprocess.run(
                    ["sh", str(script), "PPG-001"],
                    check=True,
                    capture_output=True,
                    text=True,
                )

            content = acl.read_text(encoding="utf-8")
            self.assertEqual(content.count("# BEGIN DEVICE PPG-001"), 1)
            self.assertIn("topic readwrite ppg/PPG-001/raw", content)
            self.assertIn("topic readwrite ppg/PPG-001/metrics", content)
            self.assertIn("topic readwrite ppg/PPG-001/status", content)
            self.assertIn("topic read ppg/PPG-001/command", content)


if __name__ == "__main__":
    unittest.main()
