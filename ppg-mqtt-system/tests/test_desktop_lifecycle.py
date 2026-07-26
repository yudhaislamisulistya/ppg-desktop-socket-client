import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_desktop_module():
    serial_module = types.ModuleType("serial")
    serial_module.__path__ = []
    serial_module.SerialException = type("SerialException", (Exception,), {})
    serial_tools = types.ModuleType("serial.tools")
    serial_tools.__path__ = []
    list_ports = types.ModuleType("serial.tools.list_ports")
    list_ports.comports = lambda: []
    serial_module.tools = serial_tools
    serial_tools.list_ports = list_ports

    paho = types.ModuleType("paho")
    paho.__path__ = []
    paho_mqtt = types.ModuleType("paho.mqtt")
    paho_mqtt.__path__ = []
    paho_client = types.ModuleType("paho.mqtt.client")
    paho.mqtt = paho_mqtt
    paho_mqtt.client = paho_client

    sys.modules.update(
        {
            "serial": serial_module,
            "serial.tools": serial_tools,
            "serial.tools.list_ports": list_ports,
            "librosa": types.ModuleType("librosa"),
            "paho": paho,
            "paho.mqtt": paho_mqtt,
            "paho.mqtt.client": paho_client,
        }
    )

    spec = importlib.util.spec_from_file_location(
        "pp2_lifecycle_test",
        ROOT / "ppg-desktop" / "pp2.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PP2 = load_desktop_module()


class FakeRoot:
    def __init__(self):
        self.sequence = 0
        self.cancelled = []
        self.callbacks = {}

    def after(self, delay, callback):
        self.sequence += 1
        callback_id = f"after-{self.sequence}"
        self.callbacks[callback_id] = (delay, callback)
        return callback_id

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)
        self.callbacks.pop(callback_id, None)

    def run_ready(self):
        ready = [
            callback_id
            for callback_id, (delay, _callback) in self.callbacks.items()
            if delay == 0
        ]
        for callback_id in ready:
            _delay, callback = self.callbacks.pop(callback_id)
            callback()


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.read_started = threading.Event()
        self.release_read = threading.Event()

    def readline(self):
        self.read_started.set()
        self.release_read.wait(1)
        if not self.is_open:
            raise PP2.serial.SerialException("closed")
        return b"500\n"

    def close(self):
        self.is_open = False
        self.release_read.set()

    def cancel_read(self):
        self.release_read.set()


class FakeMqtt:
    def __init__(self, disconnect_release=None):
        self.connected = True
        self.connect_count = 0
        self.disconnect_count = 0
        self.disconnect_started = threading.Event()
        self.disconnect_release = disconnect_release
        self.samples = []

    def connect(self):
        self.connect_count += 1

    def disconnect(self):
        self.disconnect_count += 1
        self.disconnect_started.set()
        if self.disconnect_release is not None:
            self.disconnect_release.wait(2)

    def add_sample(self, value):
        self.samples.append(value)


class DesktopLifecycleTest(unittest.TestCase):
    def test_language_theme_and_mfcc_detail_contract(self):
        self.assertEqual(PP2.translated("id", "patient_name"), "NAMA PASIEN")
        self.assertEqual(PP2.translated("en", "patient_name"), "PATIENT NAME")
        self.assertEqual(
            PP2.mfcc_detail_lines([1, -2.5]),
            ["C01     1.000000", "C02    -2.500000"],
        )
        self.assertEqual(set(PP2.I18N["id"]), set(PP2.I18N["en"]))
        self.assertEqual(set(PP2.DARK_THEME), set(PP2.LIGHT_THEME))

    def test_submit_uses_required_patient_name(self):
        app = PP2.ArduinoPlotApp.__new__(PP2.ArduinoPlotApp)
        app.measurement_in_progress = False
        app.patient_name_entry = types.SimpleNamespace(get=lambda: "Siti Aminah")
        app.age_entry = types.SimpleNamespace(get=lambda: "42")
        app.height_entry = types.SimpleNamespace(get=lambda: "160")
        app.weight_entry = types.SimpleNamespace(get=lambda: "55")
        published = []
        app.mqtt = types.SimpleNamespace(
            begin_measurement=lambda **payload: published.append(payload)
        )
        app.update_bmi_label = lambda _value: None
        app.update_age_value_label = lambda _value: None
        app.disable_submit_button = lambda: None
        app.start_logging = lambda: None
        app.start_countdown = lambda: None

        app.submit_height()

        self.assertEqual(published[0]["patient_code"], "Siti Aminah")
        self.assertEqual(app.last_patient_name, "Siti Aminah")

    def test_mqtt_flow_rejects_non_300_second_measurement(self):
        flow = PP2.PpgMqttFlow.__new__(PP2.PpgMqttFlow)
        with self.assertRaisesRegex(ValueError, "300 detik"):
            flow.begin_measurement(
                patient_code="Siti Aminah",
                age=42,
                height_cm=160,
                weight_kg=55,
                bmi=21.48,
                duration_seconds=60,
            )

    def test_mqtt_timeout_stops_silent_serial_session(self):
        app = PP2.ArduinoPlotApp.__new__(PP2.ArduinoPlotApp)
        app.running = True
        app.mqtt = types.SimpleNamespace(connected=False)
        app.mqtt_connect_after_id = "watchdog"
        stopped = []
        errors = []
        app.stop_serial = lambda: stopped.append(True)
        original_showerror = PP2.messagebox.showerror
        PP2.messagebox.showerror = lambda title, message: errors.append((title, message))
        try:
            app.mqtt_connection_timeout()
        finally:
            PP2.messagebox.showerror = original_showerror

        self.assertEqual(stopped, [True])
        self.assertEqual(errors[0][0], "MQTT Tidak Terhubung")
        self.assertIsNone(app.mqtt_connect_after_id)

    def test_stop_is_non_blocking_and_start_waits_for_clean_session(self):
        first_serial = FakeSerial()
        second_serial = FakeSerial()
        serials = iter((first_serial, second_serial))
        PP2.serial.Serial = lambda *_args, **_kwargs: next(serials)
        release_first_mqtt = threading.Event()
        first_mqtt = FakeMqtt(disconnect_release=release_first_mqtt)
        second_mqtt = FakeMqtt()
        mqtt_flows = iter((first_mqtt, second_mqtt))

        app = PP2.ArduinoPlotApp.__new__(PP2.ArduinoPlotApp)
        app.root = FakeRoot()
        app.port_combo = types.SimpleNamespace(get=lambda: "/dev/test")
        app.mqtt = first_mqtt
        app.create_mqtt_flow = lambda: next(mqtt_flows)
        app.running = False
        app.ser = None
        app.serial_thread = None
        app.mqtt_cleanup_thread = None
        app.start_after_stop = False
        app.mqtt_connect_after_id = None
        app.countdown_after_id = None
        app.logging_active = False
        app.measurement_in_progress = False
        app.averages_window = None
        app.dataList = []
        app.data_lock = threading.Lock()
        app.set_serial_state = lambda *_args: None
        submit_enabled = []
        app.enable_submit_button = lambda: submit_enabled.append(True)

        app.start_serial()
        self.assertTrue(first_serial.read_started.wait(1))

        app.logging_active = True
        app.measurement_in_progress = True
        app.countdown_after_id = "countdown"
        first_thread = app.serial_thread
        started_at = time.monotonic()
        app.stop_serial()

        self.assertLess(time.monotonic() - started_at, 0.5)
        self.assertTrue(first_mqtt.disconnect_started.wait(1))
        self.assertFalse(app.logging_active)
        self.assertFalse(app.measurement_in_progress)
        self.assertIsNone(app.countdown_after_id)
        self.assertTrue(submit_enabled)
        self.assertEqual(first_mqtt.samples, [])

        app.start_serial()
        self.assertTrue(app.start_after_stop)
        self.assertFalse(second_serial.read_started.is_set())

        cleanup_thread = app.mqtt_cleanup_thread
        release_first_mqtt.set()
        cleanup_thread.join(1)
        app.root.run_ready()

        self.assertFalse(first_thread.is_alive())
        self.assertTrue(second_serial.read_started.wait(1))
        time.sleep(0.05)

        self.assertTrue(app.running)
        self.assertIs(app.ser, second_serial)
        self.assertIs(app.mqtt, second_mqtt)
        self.assertEqual(first_mqtt.connect_count, 1)
        self.assertEqual(first_mqtt.disconnect_count, 1)
        self.assertEqual(second_mqtt.connect_count, 1)
        self.assertEqual(second_mqtt.disconnect_count, 0)

        app._mqtt_state = ("connected", "green")
        app._render_lamps = lambda: None
        app.on_mqtt_status("disconnected", first_mqtt)
        app.root.run_ready()
        self.assertEqual(app._mqtt_state, ("connected", "green"))

        app.stop_serial()
        self.assertTrue(second_mqtt.disconnect_started.wait(1))
        app.mqtt_cleanup_thread.join(1)
        app.root.run_ready()
        self.assertEqual(second_mqtt.disconnect_count, 1)

    def test_mqtt_disconnect_does_not_wait_for_network_loop_thread(self):
        class BlockingClient:
            def __init__(self):
                self.loop_started = threading.Event()
                self.release_loop = threading.Event()

            def disconnect(self):
                return None

            def loop_stop(self):
                self.loop_started.set()
                self.release_loop.wait(2)

        client = BlockingClient()
        statuses = []
        flow = PP2.PpgMqttFlow.__new__(PP2.PpgMqttFlow)
        flow._lock = threading.RLock()
        flow._network_started = True
        flow._measurement_id = None
        flow._batch = []
        flow._connected = threading.Event()
        flow._connected.set()
        flow.device_id = "PPG-TEST0001"
        flow.status_callback = statuses.append
        flow.client = client
        flow._publish_json = lambda *_args, **_kwargs: True

        started_at = time.monotonic()
        flow.disconnect()

        self.assertLess(time.monotonic() - started_at, 0.5)
        self.assertTrue(client.loop_started.wait(1))
        self.assertFalse(flow.connected)
        self.assertEqual(statuses[-1], "disconnected")
        client.release_loop.set()


if __name__ == "__main__":
    unittest.main()
