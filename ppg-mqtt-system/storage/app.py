#!/usr/bin/env python3
"""Subscriber MQTT yang menyimpan hanya sesi setelah tombol Submit."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from database import StorageDatabase


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("ppg-storage")

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "storage")
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
SQLITE_PATH = os.getenv("SQLITE_PATH", "/data/ppg.sqlite3")

stop_event = threading.Event()
database = StorageDatabase(SQLITE_PATH)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_topic(topic: str) -> tuple[str, str]:
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != "ppg":
        raise ValueError(f"topic tidak valid: {topic}")
    return parts[1], "/".join(parts[2:])


def on_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: mqtt.ConnectFlags,
    reason_code: mqtt.ReasonCode,
    properties: mqtt.Properties | None,
) -> None:
    if reason_code != 0:
        LOGGER.error("MQTT ditolak: %s", reason_code)
        return

    client.subscribe(
        [
            ("ppg/+/raw", 1),
            ("ppg/+/measurement/start", 1),
            ("ppg/+/measurement/result", 1),
            ("ppg/+/status", 1),
        ]
    )
    LOGGER.info("Terhubung ke MQTT dan mulai menyimpan data pengukuran.")


def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    received_at = utc_now()
    try:
        device_id, event = parse_topic(message.topic)
        payload = json.loads(message.payload.decode("utf-8"))
        payload_device_id = payload.get("device_id")
        if payload_device_id and payload_device_id != device_id:
            raise ValueError("device_id payload berbeda dengan topic")

        if event == "status":
            database.update_device_status(
                device_id=device_id,
                state=str(payload.get("state", "unknown")),
                timestamp=str(payload.get("timestamp", received_at)),
                received_at=received_at,
            )
        elif event == "measurement/start":
            database.start_measurement(
                device_id=device_id,
                payload=payload,
                received_at=received_at,
            )
            LOGGER.info("Mulai measurement %s dari %s", payload["measurement_id"], device_id)
        elif event == "raw":
            inserted = database.store_raw_batch(
                device_id=device_id,
                payload=payload,
                received_at=received_at,
            )
            if inserted:
                LOGGER.debug(
                    "Simpan raw %s sequence=%s",
                    payload["measurement_id"],
                    payload["sequence"],
                )
        elif event == "measurement/result":
            database.finish_measurement(
                device_id=device_id,
                payload=payload,
                received_at=received_at,
            )
            LOGGER.info(
                "Selesai measurement %s status=%s",
                payload["measurement_id"],
                payload.get("status"),
            )
    except Exception:
        LOGGER.exception("Pesan ditolak topic=%s", message.topic)


def shutdown(signum: int, frame: Any) -> None:
    stop_event.set()


def main() -> None:
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="ppg-storage",
        clean_session=False,
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()

    try:
        stop_event.wait()
    finally:
        client.disconnect()
        client.loop_stop()
        database.close()


if __name__ == "__main__":
    main()
