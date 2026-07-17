"""Penyimpanan SQLite untuk sesi pengukuran PPG."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    last_state TEXT,
    last_seen_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurements (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    patient_code TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    duration_seconds INTEGER,
    age INTEGER,
    height_cm REAL,
    weight_kg REAL,
    bmi REAL,
    si_mean REAL,
    hrv_mean REAL,
    voltage_mean REAL,
    adc_mean REAL,
    mfcc_json TEXT,
    result_json TEXT,
    raw_batch_count INTEGER NOT NULL DEFAULT 0,
    raw_sample_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_measurements_device_started
ON measurements(device_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_measurements_patient_started
ON measurements(patient_code, started_at DESC);

CREATE TABLE IF NOT EXISTS raw_batches (
    measurement_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    sample_period_ms REAL NOT NULL,
    samples_json TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (measurement_id, sequence),
    FOREIGN KEY (measurement_id)
        REFERENCES measurements(id)
        ON DELETE CASCADE
);
"""


def compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


class StorageDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Paho memanggil handler pesan dari network thread, sementara object
        # database dibuat oleh main thread sebelum loop MQTT dimulai.
        self.connection = sqlite3.connect(
            self.path,
            timeout=30,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def update_device_status(
        self,
        *,
        device_id: str,
        state: str,
        timestamp: str,
        received_at: str,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO devices(device_id, last_state, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    last_state = excluded.last_state,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (device_id, state, timestamp, received_at),
            )

    def start_measurement(
        self,
        *,
        device_id: str,
        payload: dict[str, Any],
        received_at: str,
    ) -> None:
        measurement_id = required_text(payload, "measurement_id")
        started_at = required_text(payload, "started_at")

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO measurements(
                    id, device_id, patient_code, started_at, status,
                    duration_seconds, age, height_cm, weight_kg, bmi,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'recording', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    patient_code = excluded.patient_code,
                    duration_seconds = excluded.duration_seconds,
                    age = excluded.age,
                    height_cm = excluded.height_cm,
                    weight_kg = excluded.weight_kg,
                    bmi = excluded.bmi,
                    updated_at = excluded.updated_at
                """,
                (
                    measurement_id,
                    device_id,
                    nullable_text(payload.get("patient_code")),
                    started_at,
                    optional_int(payload.get("duration_seconds")),
                    optional_int(payload.get("age")),
                    optional_float(payload.get("height_cm")),
                    optional_float(payload.get("weight_kg")),
                    optional_float(payload.get("bmi")),
                    received_at,
                    received_at,
                ),
            )

    def store_raw_batch(
        self,
        *,
        device_id: str,
        payload: dict[str, Any],
        received_at: str,
    ) -> bool:
        measurement_id = payload.get("measurement_id")
        if not measurement_id:
            return False

        sequence = int(payload["sequence"])
        samples = payload.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ValueError("samples harus berupa array yang tidak kosong")

        measurement = self.connection.execute(
            "SELECT device_id, status FROM measurements WHERE id = ?",
            (measurement_id,),
        ).fetchone()
        if measurement is None:
            raise ValueError(f"measurement_id belum dimulai: {measurement_id}")
        if measurement["device_id"] != device_id:
            raise ValueError("device_id topic berbeda dengan pemilik measurement")
        if measurement["status"] != "recording":
            return False

        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO raw_batches(
                    measurement_id, sequence, captured_at, received_at,
                    sample_period_ms, samples_json, sample_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    measurement_id,
                    sequence,
                    required_text(payload, "captured_at"),
                    received_at,
                    float(payload["sample_period_ms"]),
                    compact_json(samples),
                    len(samples),
                ),
            )

            inserted = cursor.rowcount == 1
            if inserted:
                self.connection.execute(
                    """
                    UPDATE measurements SET
                        raw_batch_count = raw_batch_count + 1,
                        raw_sample_count = raw_sample_count + ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (len(samples), received_at, measurement_id),
                )
            return inserted

    def finish_measurement(
        self,
        *,
        device_id: str,
        payload: dict[str, Any],
        received_at: str,
    ) -> None:
        measurement_id = required_text(payload, "measurement_id")
        finished_at = required_text(payload, "finished_at")
        status = payload.get("status", "completed")
        if status not in {"completed", "cancelled", "interrupted"}:
            raise ValueError(f"status akhir tidak valid: {status}")

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO measurements(
                    id, device_id, started_at, finished_at, status,
                    si_mean, hrv_mean, voltage_mean, adc_mean,
                    mfcc_json, result_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    finished_at = excluded.finished_at,
                    status = excluded.status,
                    si_mean = excluded.si_mean,
                    hrv_mean = excluded.hrv_mean,
                    voltage_mean = excluded.voltage_mean,
                    adc_mean = excluded.adc_mean,
                    mfcc_json = excluded.mfcc_json,
                    result_json = excluded.result_json,
                    updated_at = excluded.updated_at
                """,
                (
                    measurement_id,
                    device_id,
                    finished_at,
                    finished_at,
                    status,
                    optional_float(payload.get("si_mean")),
                    optional_float(payload.get("hrv_mean")),
                    optional_float(payload.get("voltage_mean")),
                    optional_float(payload.get("adc_mean")),
                    compact_json(payload["mfcc_mean"]) if payload.get("mfcc_mean") is not None else None,
                    compact_json(payload),
                    received_at,
                    received_at,
                ),
            )

    def list_measurements(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                id, device_id, patient_code, started_at, finished_at, status,
                si_mean, hrv_mean, voltage_mean, adc_mean,
                raw_batch_count, raw_sample_count
            FROM measurements
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def get_measurement(self, measurement_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM measurements WHERE id = ?",
            (measurement_id,),
        ).fetchone()

    def get_raw_batches(self, measurement_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT sequence, captured_at, sample_period_ms, samples_json
            FROM raw_batches
            WHERE measurement_id = ?
            ORDER BY sequence
            """,
            (measurement_id,),
        ).fetchall()


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} wajib berupa teks")
    return value.strip()


def nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
