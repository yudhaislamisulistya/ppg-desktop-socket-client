import unittest
from pathlib import Path


DESKTOP_APP = Path(__file__).resolve().parents[2] / "ppg-desktop" / "pp2.py"


class DesktopChartContractTest(unittest.TestCase):
    def test_waveform_uses_fixed_sample_and_amplitude_ranges(self):
        source = DESKTOP_APP.read_text(encoding="utf-8")

        self.assertIn("ax.set_ylim([-200.0, 200.0])", source)
        self.assertIn("ax.set_yticks([-200, -100, 0, 100, 200])", source)
        self.assertIn("ax.set_xlim(0, 1000)", source)
        self.assertIn("ax.set_xticks([0, 200, 400, 600, 800, 1000])", source)


if __name__ == "__main__":
    unittest.main()
