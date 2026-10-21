import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PatientStatusPopupTest(unittest.TestCase):
    def test_popup_is_optional_accessible_and_uses_existing_theme(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend/styles.css").read_text(encoding="utf-8")
        self.assertIn('<dialog class="patient-status-dialog" id="patient-status-dialog"', html)
        self.assertIn('aria-labelledby="patient-status-title"', html)
        self.assertIn('aria-describedby="patient-status-description"', html)
        self.assertIn('aria-label="Tutup pengisian status pasien"', html)
        self.assertIn('id="patient-status-later">Isi nanti', html)
        self.assertIn('Pengisian opsional dan manual, bukan hasil prediksi.', html)
        select = html.split('id="patient-status-label"', 1)[1].split('</select>', 1)[0]
        self.assertNotIn('required', select)
        self.assertIn('<option value="">Belum diisi</option>', select)
        self.assertIn('<option value="true">Diabetes</option>', select)
        self.assertIn('<option value="false">Tidak diabetes</option>', select)
        self.assertIn('.patient-status-dialog::backdrop', css)
        self.assertIn('max-height: calc(100dvh - 32px)', css)

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji popup")
    def test_popup_handles_skip_save_retry_duplicates_and_multiple_devices(self):
        script = r"""
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const vm = require('node:vm');
            const source = fs.readFileSync(process.argv[1], 'utf8');
            const Controller = vm.runInNewContext(source + '; MeasurementHistory;', {
                setTimeout(resolve) {resolve();}, console,
            });
            const flush = () => new Promise(setImmediate);
            function fixture() {
                const calls = [], saved = [], devices = new Map();
                for (const deviceId of ['PPG-001', 'PPG-002']) devices.set(deviceId, {
                    deviceId, preview: false,
                    async requestHistory(action, payload) {
                        calls.push({deviceId, action, ...payload});
                        if (action === 'get_label') return {measurement: {id: payload.measurement_id,
                            device_id: deviceId, patient_name: 'Pasien uji', diabetes_label: null}};
                        return {id: payload.measurement_id, diabetes_label: payload.diabetes_label,
                            label_updated_at: '2026-10-21T00:00:00Z'};
                    },
                });
                const controller = Object.create(Controller.prototype);
                Object.assign(controller, {getDevices: () => devices, rows: [], expected: new Map(),
                    drafts: new Map(), saving: new Set(), labelQueue: [], prompted: new Set(), activePrompt: null,
                    ui: {device: {value: 'PPG-001'}, panel: {hidden: true}, badge: {}},
                    render() {}, onLabelSaved(id) {saved.push(id);},
                    prompt: Object.fromEntries(['form', 'context', 'label', 'save', 'message', 'retry']
                        .map(key => [key, {dataset: {}, value: '', setAttribute() {}}])),
                });
                controller.prompt.dialog = {open: false, shown: 0,
                    showModal() {this.open = true; this.shown++;},
                    close() {this.open = false; controller.activePrompt = null; controller.showNextPrompt();},
                };
                return {controller, calls, saved, devices};
            }
            (async () => {
                let {controller: c, calls, saved, devices} = fixture();
                for (const value of [null, '', 'x'.repeat(201)]) c.notifyCompleted('PPG-001', value);
                c.notifyCompleted('PPG-MISSING', 'ignored');
                devices.get('PPG-002').preview = true;
                c.notifyCompleted('PPG-002', 'preview');
                assert.equal(c.prompt.dialog.shown, 0);
                devices.get('PPG-002').preview = false;
                c.notifyCompleted('PPG-001', 'first');
                c.notifyCompleted('PPG-001', 'first');
                await flush();
                assert.equal(c.prompt.dialog.shown, 1);
                assert.equal(c.prompt.label.value, '');
                assert.equal(c.prompt.save.disabled, true);
                assert.equal(c.prompt.label.disabled, false);
                assert.equal(calls.filter(call => call.action === 'set_label').length, 0);
                c.prompt.dialog.close();
                c.notifyCompleted('PPG-001', 'first');
                assert.equal(c.prompt.dialog.open, false);
                assert.equal(c.prompt.dialog.shown, 1);

                c.notifyCompleted('PPG-001', 'second');
                c.notifyCompleted('PPG-002', 'third');
                await flush();
                assert.equal(c.activePrompt.measurementId, 'second');
                assert.equal(c.labelQueue.length, 1);
                c.prompt.label.value = 'true'; c.updatePromptControls();
                await c.savePrompt(); await flush();
                assert.equal(saved[0], 'PPG-001');
                assert.equal(calls.find(call => call.action === 'set_label').diabetes_label, true);
                assert.equal(c.activePrompt.measurementId, 'third');
                assert.equal(c.activePrompt.deviceId, 'PPG-002');
                assert.equal(c.prompt.label.value, '');
                c.prompt.label.value = 'false'; c.updatePromptControls();
                await c.savePrompt();
                assert.equal(calls.filter(call => call.action === 'set_label')[1].diabetes_label, false);
                assert.equal(c.prompt.dialog.open, false);

                ({controller: c, calls, devices} = fixture());
                let attempts = 0;
                const original = devices.get('PPG-001').requestHistory;
                devices.get('PPG-001').requestHistory = async (action, payload) => {
                    if (action === 'get_label' && ++attempts < 4) return {measurement: null};
                    return original(action, payload);
                };
                c.notifyCompleted('PPG-001', 'delayed'); await flush();
                assert.equal(attempts, 4);
                assert.equal(c.prompt.label.disabled, false);
                assert.equal(calls.filter(call => call.action === 'set_label').length, 0);

                ({controller: c, devices} = fixture());
                devices.get('PPG-001').requestHistory = async () => ({measurement: null});
                c.notifyCompleted('PPG-001', 'never-saved'); await flush();
                assert.equal(c.prompt.save.disabled, true);
                assert.equal(c.prompt.retry.hidden, false);
                assert.equal(c.prompt.message.dataset.state, 'error');
                c.prompt.dialog.close();
                assert.equal(c.prompt.dialog.open, false);

                ({controller: c, devices} = fixture());
                devices.get('PPG-001').requestHistory = async (action, payload) => {
                    if (action === 'get_label') return {measurement: {id: payload.measurement_id,
                        device_id: 'PPG-001', diabetes_label: true}};
                    throw new Error('test offline');
                };
                c.notifyCompleted('PPG-001', 'failure'); await flush();
                assert.equal(c.prompt.label.value, 'true');
                c.prompt.label.value = ''; c.updatePromptControls();
                await c.savePrompt();
                assert.equal(c.prompt.dialog.open, true);
                assert.match(c.prompt.message.textContent, /belum terkonfirmasi.*test offline/);
                assert.equal(c.saving.size, 0);
                assert.equal(c.prompt.save.disabled, false);
                c.prompt.dialog.close();

                ({controller: c, devices} = fixture());
                let releaseRead;
                devices.get('PPG-001').requestHistory = () => new Promise(resolve => {releaseRead = resolve;});
                c.notifyCompleted('PPG-001', 'old-read');
                c.notifyCompleted('PPG-002', 'new-read');
                c.prompt.dialog.close(); await flush();
                releaseRead({measurement: {id: 'old-read', device_id: 'PPG-001', diabetes_label: true}});
                await flush();
                assert.equal(c.activePrompt.measurementId, 'new-read');
                assert.equal(c.prompt.label.value, '');
                assert.match(c.prompt.context.textContent, /PPG-002/);

                ({controller: c, devices, saved} = fixture());
                let releaseSave;
                const read = devices.get('PPG-001').requestHistory;
                devices.get('PPG-001').requestHistory = (action, payload) => action === 'set_label'
                    ? new Promise(resolve => {releaseSave = resolve;}) : read(action, payload);
                c.rows = [{id: 'old-save', diabetes_label: null}];
                c.notifyCompleted('PPG-001', 'old-save'); await flush();
                c.prompt.label.value = 'true'; c.updatePromptControls();
                const saving = c.savePrompt();
                assert.equal(c.prompt.save.disabled, true);
                await assert.rejects(c.saveLabel(devices.get('PPG-001'), 'old-save', false), /sedang disimpan/);
                c.notifyCompleted('PPG-002', 'new-save');
                c.prompt.dialog.close(); await flush();
                releaseSave({id: 'old-save', diabetes_label: true});
                await saving;
                assert.equal(c.prompt.dialog.open, true);
                assert.equal(c.activePrompt.measurementId, 'new-save');
                assert.equal(c.rows[0].diabetes_label, true);
                assert.equal(saved[0], 'PPG-001');

                ({controller: c, devices} = fixture());
                devices.get('PPG-001').requestHistory = async () => ({measurement: {
                    id: 'bad-routing', device_id: 'PPG-002', diabetes_label: false}});
                c.notifyCompleted('PPG-001', 'bad-routing'); await flush();
                assert.equal(c.prompt.save.disabled, true);
                assert.equal(c.prompt.message.dataset.state, 'error');
            })().catch(error => {console.error(error); process.exitCode = 1;});
        """
        subprocess.run(["node", "-e", script, str(ROOT / "frontend/history.js")],
                       check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji hasil MQTT")
    def test_cancelled_retained_preview_and_non_300_second_results_do_not_prompt(self):
        script = r"""
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const vm = require('node:vm');
            const source = fs.readFileSync(process.argv[1], 'utf8');
            const calls = [];
            const Dashboard = vm.runInNewContext(source.slice(source.indexOf('class DeviceDashboard'),
                source.indexOf('function removeDashboard')) + '; DeviceDashboard;', {
                console, history: {notifyCompleted(...args) {calls.push(args);}},
                page: {completion: {}, completionMessage: {}}, lastCompletedDevice: null,
            });
            const device = Object.create(Dashboard.prototype);
            Object.assign(device, {deviceId: 'PPG-001', preview: false, durationSeconds: null,
                historyResponseTopic: 'response', noteMessage() {}, hideAlert() {}, setMode() {}, renderResult() {}});
            const send = (fields = {}, packet) => device.handleMessage('ppg/PPG-001/measurement/result',
                JSON.stringify({measurement_id: 'completed', status: 'completed', ...fields}), packet);
            send({status: 'cancelled'});
            send({status: 'interrupted'});
            send({status: undefined});
            send({}, {retain: true});
            send({duration_seconds: 60});
            device.preview = true; send(); device.preview = false;
            device.durationSeconds = 60; send();
            assert.equal(calls.length, 0);
            device.durationSeconds = 300; send();
            assert.equal(calls.length, 1);
            device.durationSeconds = null; send();
            assert.equal(calls.length, 2);
        """
        subprocess.run(["node", "-e", script, str(ROOT / "frontend/app.js")],
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
