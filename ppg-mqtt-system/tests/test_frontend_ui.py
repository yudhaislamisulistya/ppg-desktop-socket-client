import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


class FrontendUiContractTest(unittest.TestCase):
    def test_theme_and_mfcc_detail_controls_are_wired(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="theme-toggle"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn("<details", html)
        self.assertIn('data-role="mfcc-values"', html)
        self.assertIn(':root[data-theme="light"]', css)
        self.assertIn("function applyTheme(", javascript)
        self.assertIn("renderMfccDetails(values)", javascript)
        self.assertIn('value.toFixed(6)', javascript)

    def test_waveform_has_accessible_fixed_axes(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")
        waveform = (FRONTEND / "waveform.js").read_text(encoding="utf-8")

        self.assertIn("chart-axis-x", html)
        self.assertIn("Samples", html)
        self.assertIn("chart-axis-y", html)
        self.assertIn("Amplitude", html)
        self.assertIn('data-role="chart"', html)
        self.assertIn('aria-label="Grafik waveform PPG realtime"', html)
        self.assertIn(".chart-frame", css)
        self.assertIn("writing-mode: vertical-rl", css)
        self.assertIn("const TRACE_CAPACITY = 1000;", javascript)
        self.assertIn("const TRACE_X_MIN = 0;", javascript)
        self.assertIn("const TRACE_X_MAX = 1000;", javascript)
        self.assertIn("const TRACE_Y_MIN = -200;", javascript)
        self.assertIn("const TRACE_Y_MAX = 200;", javascript)
        self.assertIn(
            "const TRACE_X_TICKS = [0, 200, 400, 600, 800, 1000];",
            javascript,
        )
        self.assertIn(
            "const TRACE_Y_TICKS = [-200, -100, 0, 100, 200];",
            javascript,
        )
        self.assertIn('<script src="waveform.js"></script>', html)
        self.assertIn("const signal = normalizeWaveform(trace);", javascript)
        self.assertIn("function normalizeWaveform(samples)", waveform)

    def test_multi_device_dashboards_are_dynamic_and_bounded(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="device-dashboard-template"', html)
        self.assertIn('id="dashboard-grid"', html)
        self.assertIn('data-role="remove"', html)
        self.assertIn("const MAX_DASHBOARDS = 6;", javascript)
        self.assertIn("const dashboards = new Map();", javascript)
        self.assertIn("class DeviceDashboard", javascript)
        self.assertIn("dashboards.has(deviceId)", javascript)
        self.assertIn("dashboards.size >= MAX_DASHBOARDS", javascript)
        self.assertIn("function removeDashboard(deviceId)", javascript)
        self.assertIn("dashboard-${randomId}", javascript)
        self.assertIn(".dashboard-grid", css)
        self.assertIn(".device-dashboard", css)
        self.assertIn(".device-vitals", css)

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji waveform")
    def test_frontend_waveform_matches_desktop_filter(self):
        samples = [
            512 + 6 * math.sin(2 * math.pi * index / 80)
            + 1.5 * math.sin(2 * math.pi * index / 17)
            for index in range(100)
        ]

        def moving_average_same(values, window_size):
            left = window_size // 2
            right = window_size - left - 1
            return [
                sum(values[max(0, index - left):min(len(values), index + right + 1)])
                / window_size
                for index in range(len(values))
            ]

        smooth = moving_average_same(samples, 5)
        baseline = moving_average_same(smooth, 40)
        signal = [value - baseline[index] for index, value in enumerate(smooth)]
        peak = max(map(abs, signal)) or 1
        expected = [value / peak * 200 for value in signal]

        script = (
            "const {normalizeWaveform}=require(process.argv[1]);"
            "console.log(JSON.stringify(normalizeWaveform(JSON.parse(process.argv[2]))));"
        )
        completed = subprocess.run(
            ["node", "-e", script, str(FRONTEND / "waveform.js"), json.dumps(samples)],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = json.loads(completed.stdout)

        self.assertEqual(len(expected), len(actual))
        self.assertLess(max(abs(left - right) for left, right in zip(expected, actual)), 1e-9)


if __name__ == "__main__":
    unittest.main()
