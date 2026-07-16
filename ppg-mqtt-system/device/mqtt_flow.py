"""Alur MQTT minimal untuk Raspberry Pi/pp2.py.

Start  -> connect(), add_sample(), publish_metrics(): realtime, tidak disimpan.
Submit -> begin_measurement(): membuat measurement_id dan mengaktifkan storage.
Selesai -> complete_measurement(): menyimpan hasil dan kembali ke live preview.
Stop -> disconnect(): membatalkan sesi aktif lalu memutus MQTT.
"""

from __future__ import annotations

import json
import logging
import math
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import paho.mqtt.client as mqtt


LOGGER = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def suggested_device_id() -> str:
    """Menghasilkan ID dari serial Raspberry Pi, dengan fallback hostname."""
    serial_path = Path("/proc/device-tree/serial-number")
    if serial_path.exists():
        serial = serial_path.read_text(encoding="ascii").strip("\x00\n ")
        if serial:
            return f"PPG-{serial[-8:].upper()}"

    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("serial"):
                serial = line.partition(":")[2].strip()
                if serial:
                    return f"PPG-{serial[-8:].upper()}"

    safe_hostname = "".join(c for c in socket.gethostname().upper() if c.isalnum() or c in "_-")
    return f"PPG-{safe_hostname or 'UNREGISTERED'}"


def load_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class PpgMqttFlow:
    def __init__(
        self,
        *,
        device_id: str,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_username: str,
        mqtt_password: str,
        sample_period_ms: float = 10.0,
        batch_size: int = 10,
        metrics_interval_ms: int = 200,
        tls: bool = False,
        ca_file: str | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        if not device_id.startswith("PPG-"):
            raise ValueError("device_id harus diawali PPG-")
        if batch_size < 1:
            raise ValueError("batch_size minimal 1")
        if metrics_interval_ms < 50:
            raise ValueError("metrics_interval_ms minimal 50")

        self.device_id = device_id
        self.sample_period_ms = float(sample_period_ms)
        self.batch_size = int(batch_size)
        self.metrics_interval_ms = int(metrics_interval_ms)
        self.status_callback = status_callback

        self._lock = threading.RLock()
        self._batch: list[float] = []
        self._measurement_id: str | None = None
        self._measurement_sequence = 0
        self._live_sequence = 0
        self._metrics_sequence = 0
        self._last_metrics_publish_at = 0.0
        self._network_started = False
        self._connected = threading.Event()

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=device_id,
            protocol=mqtt.MQTTv311,
        )
        self.client.username_pw_set(mqtt_username, mqtt_password)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        if tls:
            self.client.tls_set(ca_certs=ca_file)

        self.client.will_set(
            self._topic("status"),
            self._encode(
                {
                    "device_id": self.device_id,
                    "state": "offline",
                    "reason": "connection_lost",
                }
            ),
            qos=1,
            retain=True,
        )

        self._mqtt_host = mqtt_host
        self._mqtt_port = int(mqtt_port)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        status_callback: Callable[[str], None] | None = None,
    ) -> "PpgMqttFlow":
        return cls(
            device_id=config["device_id"],
            mqtt_host=config["mqtt_host"],
            mqtt_port=config.get("mqtt_port", 1883),
            mqtt_username=config.get("mqtt_username", config["device_id"]),
            mqtt_password=config["mqtt_password"],
            sample_period_ms=config.get("sample_period_ms", 10.0),
            batch_size=config.get("batch_size", 10),
            metrics_interval_ms=config.get("metrics_interval_ms", 200),
            tls=config.get("tls", False),
            ca_file=config.get("ca_file"),
            status_callback=status_callback,
        )

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def measurement_id(self) -> str | None:
        with self._lock:
            return self._measurement_id

    def connect(self) -> None:
        """Dipanggil bersama tombol Start."""
        with self._lock:
            if self._network_started:
                return
            self._network_started = True

        self._notify_status("connecting")
        try:
            self.client.connect_async(self._mqtt_host, self._mqtt_port, keepalive=30)
            self.client.loop_start()
        except Exception:
            with self._lock:
                self._network_started = False
            self._notify_status("error")
            raise

    def wait_connected(self, timeout: float = 5.0) -> bool:
        return self._connected.wait(timeout)

    def add_sample(self, value: float) -> None:
        """Dipanggil dari serial_reader untuk setiap nilai ADC."""
        with self._lock:
            self._batch.append(float(value))
            if len(self._batch) >= self.batch_size:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def publish_metrics(
        self,
        *,
        si_m_s: float | None,
        hrv_ms: float | None,
        bmi: float | None,
        age_years: int | None,
        mfcc: list[float] | None,
        voltage_v: float | None,
        adc: float | None,
        force: bool = False,
    ) -> bool:
        """Kirim satu snapshot SI/HRV/BMI/Age/MFCC/Voltage/ADC.

        Payload dibatasi oleh metrics_interval_ms agar callback UI boleh
        memanggil method ini lebih sering tanpa membanjiri broker.
        """
        if not self.connected:
            return False

        with self._lock:
            now = time.monotonic()
            minimum_interval = self.metrics_interval_ms / 1000.0
            if not force and now - self._last_metrics_publish_at < minimum_interval:
                return False

            measurement_id = self._measurement_id
            payload = {
                "device_id": self.device_id,
                "measurement_id": measurement_id,
                "mode": "recording" if measurement_id else "live",
                "sequence": self._metrics_sequence,
                "captured_at": utc_now(),
                "si_m_s": si_m_s,
                "hrv_ms": hrv_ms,
                "bmi": bmi,
                "age_years": age_years,
                "mfcc": mfcc,
                "voltage_v": voltage_v,
                "adc": adc,
            }
            published = self._publish_json(
                self._topic("metrics"),
                payload,
                qos=0,
            )
            if published:
                self._metrics_sequence += 1
                self._last_metrics_publish_at = now
            return published

    def begin_measurement(
        self,
        *,
        patient_code: str,
        age: int,
        height_cm: float,
        weight_kg: float,
        bmi: float,
        duration_seconds: int = 300,
    ) -> str:
        """Dipanggil setelah input Submit dinyatakan valid."""
        if not self.connected:
            raise RuntimeError("MQTT belum terhubung; tekan Start dan tunggu koneksi.")

        with self._lock:
            if self._measurement_id is not None:
                raise RuntimeError("Pengukuran masih aktif.")

            # Sampel sebelum Submit tetap menjadi live preview dan tidak ikut sesi.
            self._flush_locked()
            self._measurement_id = uuid4().hex
            self._measurement_sequence = 0
            measurement_id = self._measurement_id

            payload = {
                "measurement_id": measurement_id,
                "device_id": self.device_id,
                "patient_code": patient_code,
                "started_at": utc_now(),
                "age": int(age),
                "height_cm": float(height_cm),
                "weight_kg": float(weight_kg),
                "bmi": float(bmi),
                "duration_seconds": int(duration_seconds),
                "status": "recording",
            }
            published = self._publish_json(
                self._topic("measurement/start"),
                payload,
                qos=1,
                wait=True,
            )
            if not published:
                self._measurement_id = None
                raise RuntimeError("Event awal measurement gagal dikirim ke MQTT.")
            return measurement_id

    def complete_measurement(self, **result: Any) -> str | None:
        """Dipanggil setelah countdown selesai dan nilai rata-rata tersedia."""
        with self._lock:
            if self._measurement_id is None:
                return None

            self._flush_locked()
            measurement_id = self._measurement_id
            payload = {
                "measurement_id": measurement_id,
                "device_id": self.device_id,
                "finished_at": utc_now(),
                "status": "completed",
                **result,
            }
            self._publish_json(
                self._topic("measurement/result"),
                payload,
                qos=1,
                wait=True,
            )
            self._measurement_id = None
            self._measurement_sequence = 0
            return measurement_id

    def cancel_measurement(self, reason: str = "cancelled_by_user") -> str | None:
        with self._lock:
            if self._measurement_id is None:
                return None

            self._flush_locked()
            measurement_id = self._measurement_id
            self._publish_json(
                self._topic("measurement/result"),
                {
                    "measurement_id": measurement_id,
                    "device_id": self.device_id,
                    "finished_at": utc_now(),
                    "status": "cancelled",
                    "reason": reason,
                },
                qos=1,
                wait=True,
            )
            self._measurement_id = None
            self._measurement_sequence = 0
            return measurement_id

    def disconnect(self) -> None:
        """Dipanggil bersama tombol Stop atau saat aplikasi ditutup."""
        with self._lock:
            if not self._network_started:
                return
            if self._measurement_id is not None:
                self.cancel_measurement("device_stopped")
            self._flush_locked()
            self._publish_json(
                self._topic("status"),
                {
                    "device_id": self.device_id,
                    "state": "offline",
                    "timestamp": utc_now(),
                    "reason": "graceful_disconnect",
                },
                qos=1,
                retain=True,
                wait=True,
            )
            self._network_started = False

        self.client.disconnect()
        self.client.loop_stop()
        self._connected.clear()
        self._notify_status("disconnected")

    def _flush_locked(self) -> None:
        if not self._batch:
            return

        samples = self._batch
        self._batch = []
        measurement_id = self._measurement_id

        if measurement_id is None:
            sequence = self._live_sequence
            self._live_sequence += 1
            mode = "live"
            qos = 0
        else:
            sequence = self._measurement_sequence
            self._measurement_sequence += 1
            mode = "recording"
            qos = 1

        self._publish_json(
            self._topic("raw"),
            {
                "device_id": self.device_id,
                "measurement_id": measurement_id,
                "mode": mode,
                "sequence": sequence,
                "captured_at": utc_now(),
                "sample_period_ms": self.sample_period_ms,
                "samples": samples,
            },
            qos=qos,
        )

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code != 0:
            LOGGER.error("MQTT connection rejected: %s", reason_code)
            self._connected.clear()
            self._notify_status("rejected")
            return

        self._connected.set()
        self._notify_status("connected")
        self._publish_json(
            self._topic("status"),
            {
                "device_id": self.device_id,
                "state": "online",
                "timestamp": utc_now(),
            },
            qos=1,
            retain=True,
        )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self._connected.clear()
        if self._network_started:
            self._notify_status("reconnecting")
        else:
            self._notify_status("disconnected")

    def _topic(self, suffix: str) -> str:
        return f"ppg/{self.device_id}/{suffix}"

    def _publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        qos: int,
        retain: bool = False,
        wait: bool = False,
    ) -> bool:
        if not self._network_started and topic != self._topic("status"):
            return False

        info = self.client.publish(topic, self._encode(payload), qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning("MQTT publish gagal untuk %s: rc=%s", topic, info.rc)
            return False
        if wait:
            try:
                info.wait_for_publish(timeout=3)
            except (RuntimeError, ValueError):
                LOGGER.warning("MQTT publish belum terkonfirmasi untuk %s", topic)
                return False
            if not info.is_published():
                LOGGER.warning("MQTT publish timeout untuk %s", topic)
                return False
        return True

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        def normalize(value: Any) -> Any:
            if hasattr(value, "tolist"):
                return normalize(value.tolist())
            if hasattr(value, "item"):
                return normalize(value.item())
            if isinstance(value, dict):
                return {str(key): normalize(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [normalize(item) for item in value]
            if isinstance(value, float) and not math.isfinite(value):
                return None
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            raise TypeError(f"{type(value).__name__} tidak dapat diubah menjadi JSON")

        return json.dumps(
            normalize(payload),
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _notify_status(self, status: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(status)
        except Exception:
            LOGGER.exception("Status callback gagal")


def demo() -> None:
    assert suggested_device_id().startswith("PPG-")
    encoded = PpgMqttFlow._encode({"value": 1.5, "missing": float("nan")})
    assert encoded == '{"value":1.5,"missing":null}'


if __name__ == "__main__":
    demo()
