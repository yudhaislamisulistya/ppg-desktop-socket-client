"""Penyimpanan PostgreSQL khusus sesi pengukuran PPG 300 detik."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS measurements (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        patient_name TEXT,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        status TEXT NOT NULL CHECK (
            status IN ('recording', 'completed', 'cancelled', 'interrupted')
        ),
        duration_seconds INTEGER NOT NULL CHECK (duration_seconds = 300),
        age INTEGER,
        height_cm DOUBLE PRECISION,
        weight_kg DOUBLE PRECISION,
        bmi DOUBLE PRECISION,
        si_mean DOUBLE PRECISION,
        hrv_mean DOUBLE PRECISION,
        voltage_mean DOUBLE PRECISION,
        adc_mean DOUBLE PRECISION,
        mfcc JSONB,
        result JSONB,
        raw_batch_count INTEGER NOT NULL DEFAULT 0,
        raw_sample_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_device_started
    ON measurements(device_id, started_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_patient_started
    ON measurements(patient_name, started_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS measurement_raw_batches (
        measurement_id TEXT NOT NULL
            REFERENCES measurements(id)
            ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        captured_at TIMESTAMPTZ NOT NULL,
        received_at TIMESTAMPTZ NOT NULL,
        sample_period_ms DOUBLE PRECISION NOT NULL,
        samples JSONB NOT NULL,
        sample_count INTEGER NOT NULL CHECK (sample_count > 0),
        PRIMARY KEY (measurement_id, sequence)
    )
    """,
)


class StorageDatabase:
    def __init__(self, database_url: str | None = None) -> None:
        # Tanpa URL, psycopg memakai PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD.
        self.connection = psycopg.connect(
            database_url or "",
            autocommit=True,
            row_factory=dict_row,
        )
        for statement in SCHEMA_STATEMENTS:
            self.connection.execute(statement)

    def close(self) -> None:
        self.connection.close()

    def start_measurement(
        self,
        *,
        device_id: str,
        payload: dict[str, Any],
        received_at: str,
    ) -> None:
        measurement_id = required_text(payload, "measurement_id")
        started_at = required_text(payload, "started_at")
        duration_seconds = optional_int(payload.get("duration_seconds"))
        if duration_seconds != 300:
            raise ValueError("hanya measurement berdurasi 300 detik yang disimpan")

        patient_name = nullable_text(
            payload.get("patient_name", payload.get("patient_code"))
        )
        with self.connection.transaction():
            self.connection.execute(
                """
                INSERT INTO measurements(
                    id, device_id, patient_name, started_at, status,
                    duration_seconds, age, height_cm, weight_kg, bmi,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, 'recording',
                    %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT(id) DO UPDATE SET
                    patient_name = excluded.patient_name,
                    age = excluded.age,
                    height_cm = excluded.height_cm,
                    weight_kg = excluded.weight_kg,
                    bmi = excluded.bmi,
                    updated_at = excluded.updated_at
                WHERE measurements.device_id = excluded.device_id
                  AND measurements.status = 'recording'
                """,
                (
                    measurement_id,
                    device_id,
                    patient_name,
                    started_at,
                    duration_seconds,
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

        with self.connection.transaction():
            measurement = self.connection.execute(
                """
                SELECT device_id, status
                FROM measurements
                WHERE id = %s AND duration_seconds = 300
                """,
                (measurement_id,),
            ).fetchone()
            if measurement is None:
                raise ValueError(
                    f"measurement 300 detik belum dimulai: {measurement_id}"
                )
            if measurement["device_id"] != device_id:
                raise ValueError(
                    "device_id topic berbeda dengan pemilik measurement"
                )
            if measurement["status"] != "recording":
                return False

            inserted = self.connection.execute(
                """
                INSERT INTO measurement_raw_batches(
                    measurement_id, sequence, captured_at, received_at,
                    sample_period_ms, samples, sample_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(measurement_id, sequence) DO NOTHING
                RETURNING sequence
                """,
                (
                    measurement_id,
                    sequence,
                    required_text(payload, "captured_at"),
                    received_at,
                    float(payload["sample_period_ms"]),
                    Jsonb(samples),
                    len(samples),
                ),
            ).fetchone()
            if inserted is None:
                return False

            self.connection.execute(
                """
                UPDATE measurements SET
                    raw_batch_count = raw_batch_count + 1,
                    raw_sample_count = raw_sample_count + %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (len(samples), received_at, measurement_id),
            )
            return True

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

        with self.connection.transaction():
            updated = self.connection.execute(
                """
                UPDATE measurements SET
                    finished_at = %s,
                    status = %s,
                    si_mean = %s,
                    hrv_mean = %s,
                    voltage_mean = %s,
                    adc_mean = %s,
                    mfcc = %s,
                    result = %s,
                    updated_at = %s
                WHERE id = %s
                  AND device_id = %s
                  AND duration_seconds = 300
                RETURNING id
                """,
                (
                    finished_at,
                    status,
                    optional_float(payload.get("si_mean")),
                    optional_float(payload.get("hrv_mean")),
                    optional_float(payload.get("voltage_mean")),
                    optional_float(payload.get("adc_mean")),
                    Jsonb(payload["mfcc_mean"])
                    if payload.get("mfcc_mean") is not None
                    else None,
                    Jsonb(payload),
                    received_at,
                    measurement_id,
                    device_id,
                ),
            ).fetchone()
            if updated is None:
                raise ValueError(
                    f"measurement 300 detik belum dimulai: {measurement_id}"
                )

    def list_measurements(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.connection.execute(
            """
            SELECT
                id, device_id, patient_name, started_at, finished_at, status,
                si_mean, hrv_mean, voltage_mean, adc_mean,
                raw_batch_count, raw_sample_count
            FROM measurements
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (max(1, int(limit)),),
        ).fetchall()

    def get_measurement(self, measurement_id: str) -> dict[str, Any] | None:
        return self.connection.execute(
            "SELECT * FROM measurements WHERE id = %s",
            (measurement_id,),
        ).fetchone()

    def get_raw_batches(self, measurement_id: str) -> list[dict[str, Any]]:
        return self.connection.execute(
            """
            SELECT sequence, captured_at, sample_period_ms, samples
            FROM measurement_raw_batches
            WHERE measurement_id = %s
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
