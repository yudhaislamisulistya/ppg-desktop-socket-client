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
        self.assertIn('id="mfcc-values"', html)
        self.assertIn(':root[data-theme="light"]', css)
        self.assertIn("function applyTheme(", javascript)
        self.assertIn("function renderMfccDetails(", javascript)
        self.assertIn('value.toFixed(6)', javascript)

    def test_waveform_has_accessible_fixed_axes(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="chart-x-label"', html)
        self.assertIn("Samples", html)
        self.assertIn('id="chart-y-label"', html)
        self.assertIn("Amplitude", html)
        self.assertIn(
            'aria-describedby="chart-x-label chart-y-label"',
            html,
        )
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
        self.assertIn("function traceScale()", javascript)


if __name__ == "__main__":
    unittest.main()
