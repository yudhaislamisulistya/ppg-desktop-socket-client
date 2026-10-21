import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage"))
from history import handle_history_request  # noqa: E402
import database as DATABASE_MODULE  # noqa: E402

SPEC = importlib.util.spec_from_file_location("history_acl", ROOT / "scripts/upgrade-history-acl.py")
ACL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACL)


class HistoryProtocolTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji pagination")
    def test_numbered_pagination_and_server_side_page_navigation(self):
        script = r"""
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const vm = require('node:vm');
            const source = fs.readFileSync(process.argv[1], 'utf8');
            const {pages, Controller} = vm.runInNewContext(source + '; ({pages: historyPageNumbers, Controller: MeasurementHistory})');
            assert.deepEqual([...pages(1, 0)], []);
            assert.deepEqual([...pages(1, 1)], [1]);
            assert.deepEqual([...pages(2, 3)], [1, 2, 3]);
            assert.deepEqual([...pages(50, 100)], [1, null, 48, 49, 50, 51, 52, null, 100]);
            for (let total = 1; total <= 100; total++) {
                for (let current = 1; current <= total; current++) {
                    const buttons = [...pages(current, total)].filter(value => value !== null);
                    assert.ok(buttons.includes(current));
                    assert.equal(buttons[0], 1);
                    assert.equal(buttons[buttons.length - 1], total);
                    assert.ok(buttons.length <= 9);
                    assert.equal(new Set(buttons).size, buttons.length);
                    assert.ok(buttons.every(value => value >= 1 && value <= total));
                }
            }
            (async () => {
                const calls = [];
                const records = Array.from({length: 25}, (_, index) => ({id: `row-${index}`}));
                const device = {requestHistory: async (action, {limit, offset}) => {
                    calls.push({limit, offset});
                    return {measurements: records.slice(offset, offset + limit), total: records.length};
                }};
                const history = Object.create(Controller.prototype);
                Object.assign(history, {rows: [], currentPage: 1, total: 0, generation: 0,
                    expected: new Map(), getDevices: () => new Map([['PPG-001', device]]),
                    ui: {device: {value: 'PPG-001'}, 'page-size': {value: '10'},
                         list: {replaceChildren() {}}, 'table-wrap': {}, 'scroll-hint': {}, status: {}, badge: {}, panel: {}, pagination: {}},
                    setBusy(value) {this.busy = value;}, render() {}, renderPagination() {},
                });
                await history.load();
                assert.equal(history.rows.length, 10);
                assert.equal(history.total, 25);
                await history.load({page: 2});
                assert.equal(history.rows[0].id, 'row-10');
                assert.equal(history.currentPage, 2);
                assert.equal(history.rows.length, 10);
                await history.load({page: 99});
                assert.equal(history.currentPage, 3);
                assert.equal(history.rows.length, 5);
                assert.equal(calls[calls.length - 1].offset, 20);
                history.ui['page-size'].value = '20';
                await history.load({page: 1});
                assert.equal(history.rows.length, 20);
                device.requestHistory = async () => {throw new Error('test offline');};
                await history.load();
                assert.match(history.ui.status.textContent, /test offline/);
                assert.equal(history.busy, false);
                assert.equal(history.ui.pagination.hidden, true);
                device.requestHistory = async () => ({measurements: [], total: 0});
                await history.load({page: 3});
                assert.equal(history.currentPage, 1);
                assert.equal(history.rows.length, 0);
            })().catch(error => {console.error(error);process.exitCode = 1;});
        """
        subprocess.run(["node", "-e", script, str(ROOT / "frontend/history.js")], check=True, capture_output=True, text=True)

    def setUp(self):
        self.database = Mock()
        self.database.count_history.return_value = 0
        self.base = {"client_id": "dashboard-test", "request_id": "request-1", "action": "list"}

    def response(self, **fields):
        topic, body = handle_history_request(self.database, "PPG-001", {**self.base, **fields})
        self.assertEqual(topic, "ppg/PPG-001/history/response/dashboard-test")
        return json.loads(body)

    def test_history_is_scoped_to_topic_and_paginates_without_raw_samples(self):
        self.database.list_history.return_value = [{"id": "first", "started_at": datetime(2026, 10, 21, tzinfo=timezone.utc)}, {"id": "second"}]
        self.database.count_history.return_value = 12
        response = self.response(limit=1, offset=2)
        self.database.list_history.assert_called_once_with("PPG-001", limit=2, offset=2)
        self.assertTrue(response["ok"])
        self.assertTrue(response["data"]["has_more"])
        self.assertEqual(len(response["data"]["measurements"]), 1)
        self.assertEqual(response["request_id"], "request-1")
        self.database.count_history.assert_called_once_with("PPG-001")
        self.assertEqual(response["data"]["total"], 12)

    def test_invalid_routing_tokens_do_not_publish_responses(self):
        for field in ("client_id", "request_id"):
            for value in (None, "a/../../other", "#", "+", "x" * 101):
                with self.subTest(field=field, value=value):
                    self.assertIsNone(handle_history_request(self.database, "PPG-001", {**self.base, field: value}))
        self.database.list_history.assert_not_called()

    def test_missing_numeric_values_remain_null_instead_of_breaking_json(self):
        self.database.list_history.return_value = [{"id": "legacy", "si_mean": float("nan"),
                                                   "hrv_mean": float("inf"), "mfcc": [float("-inf"), 1.25]}]
        row = self.response()["data"]["measurements"][0]
        self.assertIsNone(row["si_mean"])
        self.assertIsNone(row["hrv_mean"])
        self.assertEqual(row["mfcc"], [None, 1.25])

    def test_invalid_device_action_and_pagination_are_rejected(self):
        for fields in ({"device_id": "PPG-OTHER"}, {"action": "delete"}, {"limit": 101},
                       {"limit": True}, {"offset": -1}, {"offset": "0"}):
            with self.subTest(fields=fields):
                self.assertFalse(self.response(**fields)["ok"])
        self.database.list_history.assert_not_called()

    def test_label_accepts_only_true_false_or_null_and_requires_existing_recording(self):
        for label in (True, False, None):
            self.database.update_diabetes_label.return_value = {"id": "record-1", "diabetes_label": label}
            response = self.response(action="set_label", measurement_id="record-1", diabetes_label=label)
            self.assertIs(response["data"]["diabetes_label"], label)
            self.assertEqual(self.database.update_diabetes_label.call_args.kwargs["device_id"], "PPG-001")
        for label in (0, 1, "false", [], {}):
            with self.subTest(label=label):
                self.assertFalse(self.response(action="set_label", measurement_id="record-1", diabetes_label=label)["ok"])
        self.assertFalse(self.response(action="set_label", measurement_id="record-1")["ok"])
        self.database.update_diabetes_label.return_value = None
        self.assertFalse(self.response(action="set_label", measurement_id="record-1", diabetes_label=True)["ok"])

    def test_history_acl_migration_is_idempotent_and_preserves_other_permissions(self):
        original = ("user storage\ntopic read ppg/+/raw\n\nuser dashboard\ntopic read ppg/+/metrics\n"
                    "# BEGIN DEVICE PPG-001\nuser PPG-001\ntopic readwrite ppg/PPG-001/raw\n# END DEVICE PPG-001\n")
        upgraded = ACL.upgrade_history_acl(original)
        self.assertEqual(ACL.upgrade_history_acl(upgraded), upgraded)
        self.assertIn("topic read ppg/+/history/request", upgraded)
        self.assertIn("topic write ppg/+/history/response/#", upgraded)
        self.assertIn("topic write ppg/PPG-001/history/request", upgraded)
        self.assertIn("topic read ppg/PPG-001/history/response/#", upgraded)
        self.assertNotIn("topic readwrite ppg/PPG-001/history/response", upgraded)
        self.assertIn("user dashboard\ntopic read ppg/+/metrics\n", upgraded)
        self.assertIn("topic readwrite ppg/PPG-001/raw", upgraded)

    def test_storage_subscribes_and_replies_without_recording_history_requests(self):
        spec = importlib.util.spec_from_file_location("storage_history_test", ROOT / "storage/app.py")
        worker = importlib.util.module_from_spec(spec)
        self.database.list_history.return_value = []
        with patch.dict(os.environ, {"MQTT_PASSWORD": "unit-test-password"}), \
                patch.object(DATABASE_MODULE, "StorageDatabase", return_value=self.database):
            spec.loader.exec_module(worker)
        client = Mock()
        worker.on_connect(client, None, None, 0, None)
        self.assertIn(("ppg/+/history/request", 1), client.subscribe.call_args.args[0])
        message = SimpleNamespace(topic="ppg/PPG-001/history/request", retain=False,
                                  payload=json.dumps(self.base).encode())
        worker.on_message(client, None, message)
        topic, body = client.publish.call_args.args
        self.assertEqual(topic, "ppg/PPG-001/history/response/dashboard-test")
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(client.publish.call_args.kwargs, {"qos": 1, "retain": False})
        self.database.start_measurement.assert_not_called()
        self.database.store_raw_batch.assert_not_called()
        self.database.finish_measurement.assert_not_called()
        client.publish.reset_mock()
        message.retain = True
        worker.on_message(client, None, message)
        client.publish.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji History")
    def test_browser_history_requests_are_correlated_and_cancelled_on_disconnect(self):
        script = r"""
            const assert = require('node:assert/strict');
            const fs = require('node:fs');
            const vm = require('node:vm');
            const source = fs.readFileSync(process.argv[1], 'utf8');
            const timers = new Map();
            let nextId = 0;
            const Dashboard = vm.runInNewContext(source.slice(source.indexOf('class DeviceDashboard'),
                source.indexOf('function removeDashboard')) + '; DeviceDashboard;', {
                setTimeout(fn) { timers.set(++nextId, fn); return nextId; },
                clearTimeout(id) { timers.delete(id); },
                crypto: {randomUUID: () => `request-${nextId + 1}`}, console,
            });
            (async () => {
                const device = Object.create(Dashboard.prototype);
                Object.assign(device, {deviceId: 'PPG-001', historyClientId: 'dashboard-test',
                    historyResponseTopic: 'ppg/PPG-001/history/response/dashboard-test',
                    historyRequests: new Map(), links: new Map(), noteMessage() {}, hideAlert() {}});
                let published;
                device.client = {connected: true, publish(topic, body, options, callback) {
                    published = {topic, body: JSON.parse(body), options}; callback();
                }};
                const request = device.requestHistory('list');
                assert.equal(published.topic, 'ppg/PPG-001/history/request');
                assert.equal(published.options.qos, 1);
                assert.equal(published.options.retain, false);
                device.handleMessage('ppg/OTHER/history/response/dashboard-test', JSON.stringify({request_id: published.body.request_id, ok: true}));
                assert.equal(device.historyRequests.size, 1);
                device.handleMessage(device.historyResponseTopic, JSON.stringify({request_id: published.body.request_id, ok: true, data: {measurements: []}}));
                assert.equal((await request).measurements.length, 0);
                assert.equal(timers.size, 0);
                const next = device.requestHistory('list');
                const rejected = assert.rejects(next, /terputus/);
                device.rejectHistoryRequests();
                await rejected;
                assert.equal(timers.size, 0);
                const timeout = device.requestHistory('list');
                const timedOut = assert.rejects(timeout, /belum merespons/);
                [...timers.values()][0]();
                await timedOut;
                assert.equal(device.historyRequests.size, 0);
                device.client.connected = false;
                await assert.rejects(device.requestHistory('list'), /belum aktif/);
                device.client.connected = true;
                device.links.set('history/response', {granted: false});
                await assert.rejects(device.requestHistory('list'), /ACL broker/);
            })().catch(error => {console.error(error); process.exitCode = 1;});
        """
        subprocess.run(["node", "-e", script, str(ROOT / "frontend/app.js")], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
