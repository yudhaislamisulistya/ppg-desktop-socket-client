import json
import math
import re
import shutil
import subprocess
import unittest
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


class FrontendUiContractTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji perangkat bawaan")
    def test_preset_devices_require_login_before_reusing_session_credentials(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-preset="PPG-001"', html)
        self.assertIn('data-preset="PPG-002"', html)
        script = r"""
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const vm = require('node:vm');
            const source = fs.readFileSync(process.argv[1], 'utf8');
            const controller = source.slice(source.indexOf('function connectPreset('), source.indexOf('function addDashboard('));
            const calls = [];
            const devices = new Map();
            const page = {deviceId: {}, username: {dataset: {}}, password: {value: '', focus() {this.focused = true;}},
                connection: {scrollIntoView() {}}, historyPanel: {hidden: true}};
            const context = vm.createContext({page, dashboards: devices, PRESET_DEVICE_IDS: ['PPG-001', 'PPG-002'],
                addDashboard(options) {calls.push(options);}, showView() {}, history: {open(id) {calls.push(id);}}});
            const run = code => vm.runInContext(code, context);
            run(controller + '; connectPreset("PPG-001");');
            assert.equal(calls.length, 0);
            assert.equal(page.deviceId.value, 'PPG-001');
            assert.equal(page.username.value, 'PPG-001');
            assert.equal(page.password.value, '');
            assert.equal(page.password.focused, true);
            const first = {deviceId: 'PPG-001', username: 'PPG-001', node: {scrollIntoView() {}},
                client: {connected: true, options: {password: 'private-test-session'}}};
            devices.set('PPG-001', first);
            run('connectPreset("PPG-002");');
            assert.equal(calls.length, 1);
            assert.equal(calls[0].deviceId, 'PPG-002');
            assert.equal(calls[0].username, 'PPG-002');
            assert.equal(calls[0].password, 'private-test-session');
            first.client.connected = false;
            run('connectPreset("PPG-002"); connectPreset("PPG-OTHER");');
            assert.equal(calls.length, 1);
            first.client.connected = true;
            first.username = 'other-account';
            run('connectPreset("PPG-002");');
            assert.equal(calls.length, 1);
            page.historyPanel.hidden = false;
            run('connectPreset("PPG-001");');
            assert.equal(calls[1], 'PPG-001');
        """
        subprocess.run(["node", "-e", script, str(FRONTEND / "app.js")], check=True, capture_output=True, text=True)

    def test_history_uses_an_accessible_table_and_numbered_pagination(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        history = (FRONTEND / "history.js").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<table class="history-table">', html)
        self.assertIn('<tbody id="history-list">', html)
        self.assertIn('scope="col"', html)
        self.assertIn('id="history-page-size"', html)
        self.assertIn('id="history-previous"', html)
        self.assertIn('id="history-next"', html)
        self.assertIn('id="history-pages"', html)
        self.assertNotIn('id="history-more"', html)
        self.assertIn('setAttribute("aria-current", "page")', history)
        self.assertIn('patient.scope = "row"', history)
        self.assertIn('.history-table-wrap { position: relative; overflow-x: auto;', css)

    def test_history_is_persistent_and_label_is_optional_and_manual(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        history = (FRONTEND / "history.js").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="history-button"', html)
        self.assertIn('id="history-panel"', html)
        self.assertIn('Label diabetes diisi manual, opsional', html)
        self.assertIn('new Option("Belum diisi", "")', history)
        self.assertIn('new Option("Diabetes", "true")', history)
        self.assertIn('new Option("Tidak diabetes", "false")', history)
        self.assertIn('diabetes_label: select.value === "" ? null : select.value === "true"', history)
        self.assertNotIn('select.required', history)
        self.assertNotIn('localStorage.', history)
        self.assertIn('device.requestHistory("list"', history)
        self.assertIn('device.requestHistory("set_label"', history)
        self.assertIn('history.notifyCompleted(this.deviceId, payload.measurement_id)', javascript)

    def test_vitals_keep_full_precision_and_reflow_without_clipping(self):
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")

        def declarations(selector):
            return re.search(re.escape(selector) + r"\s*\{([^}]+)\}", css).group(1)

        row = declarations(".vital-row")
        self.assertIn("flex-direction: column", row)
        self.assertIn("align-items: flex-start", row)
        for selector in (".vital-val", ".vital-unit"):
            styles = declarations(selector)
            with self.subTest(selector=selector):
                self.assertIn("max-width: 100%", styles)
                self.assertIn("overflow-wrap: anywhere", styles)
                self.assertNotIn("overflow: hidden", styles)
                self.assertNotIn("text-overflow", styles)
                self.assertNotIn("white-space: nowrap", styles)

        for width, columns in ((1050, 3), (520, 2)):
            responsive = css.split(f"@media (max-width: {width}px)", 1)[1].split("@media", 1)[0]
            self.assertRegex(responsive, r"\.device-vitals\s*\{[^}]*grid-template-columns:\s*"
                             + rf"repeat\({columns}, minmax\(0, 1fr\)\)")

        for identifier, digits in (("si", 4), ("hrv", 2), ("bmi", 2),
                                   ("age", 0), ("volt", 2), ("adc", 0)):
            self.assertRegex(javascript, rf'\{{ id: "{identifier}",[^\n]+digits: {digits} \}}')
        self.assertIn("const text = formatNumber(value, digits);", javascript)

    def test_both_themes_have_readable_text_contrast(self):
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        themes = re.findall(r':root\[data-theme="(light|dark)"\]\s*\{([^}]+)\}', css)
        self.assertEqual({theme for theme, _ in themes}, {"light", "dark"})

        def luminance(color):
            channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                      for value in channels]
            return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for theme, declarations in themes:
            colors = dict(re.findall(r'(--[\w-]+):\s*(#[\da-fA-F]{6});', declarations))
            for foreground in ("--text", "--text-dim", "--text-faint"):
                for background in ("--bg", "--bg-panel", "--bg-raised"):
                    left, right = sorted((luminance(colors[foreground]), luminance(colors[background])))
                    with self.subTest(theme=theme, foreground=foreground, background=background):
                        self.assertGreaterEqual((right + 0.05) / (left + 0.05), 4.5)

    def test_preview_is_manual_and_separate_from_real_devices(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")

        self.assertIn("Glucometer PPG Merah Putih", html)
        self.assertIn("Data simulasi", html)
        self.assertIn("bukan hasil pengukuran dan tidak disimpan", html)
        self.assertIn('<script src="preview.js"></script>', html)
        self.assertIn('      async\n      src="https://unpkg.com/mqtt@', html)
        self.assertIn('id="preview-connect"', html)
        self.assertIn('id="preview-button" aria-expanded="false"', html)
        self.assertRegex(html, r'id="preview-notice"[^>]*\bhidden')
        self.assertIn('Belum ada perangkat', html)
        self.assertIn('data-role="preview-toggle"', html)
        self.assertIn('function togglePreview()', javascript)
        self.assertIn('page.previewButton.addEventListener("click", () => {', javascript)
        self.assertIn('  togglePreview();', javascript)
        self.assertIn('if (preview) this.startPreview();', javascript)
        self.assertIn('else this.connect(password);', javascript)
        self.assertIn('clearInterval(previewTimer);', javascript)
        self.assertIn('previewDashboard?.destroy();', javascript)
        self.assertIn('this.ui["device-more"].hidden = true;', javascript)
        self.assertIn('this.ui["broker-lamp"].hidden = true;', javascript)
        self.assertIn('if (!document.hidden)', javascript)
        self.assertIn('if (this.previewPaused || this.closed) return;', javascript)
        self.assertIn('prefers-reduced-motion: reduce', javascript)
        self.assertIn('typeof mqtt === "undefined"', javascript)

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji kontrol preview")
    def test_preview_lifecycle_requires_explicit_user_action(self):
        script = """
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const vm = require('node:vm');
            const source = fs.readFileSync(process.argv[1], 'utf8');
            const controller = source.slice(source.indexOf('function stopPreview()'),
                                            source.indexOf('function drawWaveform('));
            const timers = new Map();
            const created = [];
            let nextTimer = 0;
            const page = Object.fromEntries([
                'chipDevice', 'chipMode', 'chipModeWrap', 'lampBroker', 'lampBrokerText',
                'empty', 'previewNotice', 'previewButton', 'connectButton',
            ].map(name => [name, {dataset: {}, setAttribute(key, value) {this[key] = value;}}]));
            const context = vm.createContext({
                page, document: {hidden: false}, dashboards: new Map(), MAX_DASHBOARDS: 6,
                setInterval(callback, delay) {
                    assert.equal(delay, 100);
                    timers.set(++nextTimer, callback);
                    return nextTimer;
                },
                clearInterval(id) {timers.delete(id);},
                DeviceDashboard: class {
                    constructor(options) {
                        assert.equal(options.preview, true);
                        this.frames = 0;
                        created.push(this);
                    }
                    destroy() {this.destroyed = true;}
                    advancePreview() {this.frames++;}
                },
            });
            const run = code => vm.runInContext(code, context);
            run('let previewDashboard = null; let previewTimer = null;' + controller);
            run('updateSummary();');
            assert.equal(created.length, 0);
            assert.equal(timers.size, 0);
            assert.equal(page.empty.hidden, false);
            assert.equal(page.previewNotice.hidden, true);
            assert.equal(page.previewButton['aria-expanded'], 'false');

            run('togglePreview(); updateSummary();');
            assert.equal(created.length, 1);
            assert.equal(timers.size, 1);
            assert.equal(page.empty.hidden, true);
            assert.equal(page.previewNotice.hidden, false);
            assert.equal(page.previewButton.textContent, 'Tutup preview');
            assert.equal(page.previewButton['aria-expanded'], 'true');
            timers.get(nextTimer)();
            assert.equal(created[0].frames, 1);
            context.document.hidden = true;
            timers.get(nextTimer)();
            assert.equal(created[0].frames, 1);

            run('togglePreview();');
            assert.equal(created[0].destroyed, true);
            assert.equal(timers.size, 0);
            assert.equal(page.empty.hidden, false);
            assert.equal(page.previewButton.textContent, 'Preview');

            run('togglePreview();');
            context.dashboards.set('PPG-TEST', {client: {connected: true}});
            run('updateSummary(); togglePreview();');
            assert.equal(created.length, 2);
            assert.equal(created[1].destroyed, true);
            assert.equal(timers.size, 0);
            assert.equal(page.previewButton.disabled, true);
            assert.equal(page.previewNotice.hidden, true);

            context.dashboards.clear();
            run('updateSummary();');
            assert.equal(created.length, 2);
            assert.equal(timers.size, 0);
            assert.equal(page.empty.hidden, false);
            assert.equal(page.previewButton.disabled, false);
        """
        subprocess.run(
            ["node", "-e", script, str(FRONTEND / "app.js")],
            check=True, capture_output=True, text=True,
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji pratinjau")
    def test_preview_signal_is_finite_deterministic_and_matches_chart_range(self):
        script = """
            const assert = require('node:assert/strict');
            const {previewSamples, PREVIEW_MFCC} = require(process.argv[1]);
            const {normalizeWaveform} = require(process.argv[2]);
            const samples = previewSamples(0, 1000);
            assert.equal(samples.length, 1000);
            assert.ok(samples.every(Number.isFinite));
            assert.ok(samples.some(value => value < 0));
            assert.ok(samples.some(value => value > 0));
            assert.deepEqual(samples, previewSamples(0, 1000));
            assert.deepEqual(
                [...samples, ...previewSamples(1000, 10)],
                previewSamples(0, 1010),
            );
            assert.deepEqual(previewSamples(0, 0), []);
            const signal = normalizeWaveform(samples);
            assert.equal(signal.length, 1000);
            assert.ok(signal.every(value => Number.isFinite(value) && Math.abs(value) <= 200));
            assert.equal(PREVIEW_MFCC.length, 13);
            assert.ok(PREVIEW_MFCC.every(Number.isFinite));
        """
        subprocess.run(
            ["node", "-e", script, str(FRONTEND / "preview.js"), str(FRONTEND / "waveform.js")],
            check=True, capture_output=True, text=True,
        )

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
