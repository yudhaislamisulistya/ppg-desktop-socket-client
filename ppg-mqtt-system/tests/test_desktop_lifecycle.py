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

    def after(self, _delay, _callback):
        self.sequence += 1
        return f"after-{self.sequence}"

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)


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


class FakeMqtt:
    def __init__(self):
        self.connected = True
        self.connect_count = 0
        self.disconnect_count = 0
        self.samples = []

    def connect(self):
        self.connect_count += 1

    def disconnect(self):
        self.disconnect_count += 1

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

    def test_stop_waits_for_old_reader_before_restart(self):
        first_serial = FakeSerial()
        second_serial = FakeSerial()
        serials = iter((first_serial, second_serial))
        PP2.serial.Serial = lambda *_args, **_kwargs: next(serials)

        app = PP2.ArduinoPlotApp.__new__(PP2.ArduinoPlotApp)
        app.root = FakeRoot()
        app.port_combo = types.SimpleNamespace(get=lambda: "/dev/test")
        app.mqtt = FakeMqtt()
        app.running = False
        app.ser = None
        app.serial_thread = None
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
        app.stop_serial()

        self.assertFalse(first_thread.is_alive())
        self.assertEqual(app.mqtt.disconnect_count, 1)
        self.assertFalse(app.logging_active)
        self.assertFalse(app.measurement_in_progress)
        self.assertIsNone(app.countdown_after_id)
        self.assertTrue(submit_enabled)

        app.start_serial()
        self.assertTrue(second_serial.read_started.wait(1))
        time.sleep(0.05)

        self.assertTrue(app.running)
        self.assertIs(app.ser, second_serial)
        self.assertEqual(app.mqtt.connect_count, 2)
        self.assertEqual(app.mqtt.disconnect_count, 1)

        app.stop_serial()
        self.assertEqual(app.mqtt.disconnect_count, 2)


if __name__ == "__main__":
    unittest.main()
