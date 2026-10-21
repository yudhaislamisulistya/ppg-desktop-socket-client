import os
import sys
import threading
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage"))

from database import SCHEMA_STATEMENTS, StorageDatabase  # noqa: E402


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


class StoragePolicyTest(unittest.TestCase):
    def test_diabetes_label_rejects_values_other_than_boolean_or_null(self):
        database = StorageDatabase.__new__(StorageDatabase)
        for label in (0, 1, "true", "false", [], {}):
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "true, false, atau null"):
                database.update_diabetes_label(
                    device_id="PPG-TEST0001", measurement_id="test", label=label,
                    updated_at="2026-10-21T00:00:00Z",
                )

    def test_non_300_second_measurement_is_rejected_before_database_write(self):
        database = StorageDatabase.__new__(StorageDatabase)
        with self.assertRaisesRegex(ValueError, "300 detik"):
            database.start_measurement(
                device_id="PPG-TEST0001",
                payload={
                    "measurement_id": "too-short",
                    "started_at": "2026-07-16T01:00:00.000+00:00",
                    "duration_seconds": 60,
                },
                received_at="2026-07-16T01:00:00.000+00:00",
            )


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL untuk menjalankan integrasi PostgreSQL",
)
class StorageDatabaseIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.db = StorageDatabase(TEST_DATABASE_URL)
        self.measurement_ids = []
        self.received_at = "2026-07-16T01:00:00.000+00:00"

    def tearDown(self):
        for measurement_id in self.measurement_ids:
            self.db.connection.execute(
                "DELETE FROM measurements WHERE id = %s",
                (measurement_id,),
            )
        self.db.close()

    def new_measurement_id(self):
        measurement_id = f"test-{uuid4().hex}"
        self.measurement_ids.append(measurement_id)
        return measurement_id

    def start_payload(self, measurement_id):
        return {
            "measurement_id": measurement_id,
            "started_at": self.received_at,
            "patient_name": "Siti Aminah",
            "duration_seconds": 300,
            "age": 30,
            "height_cm": 170,
            "weight_kg": 65,
            "bmi": 22.49,
        }

    def test_live_ignored_recording_saved_and_duplicate_deduplicated(self):
        live_payload = {
            "measurement_id": None,
            "sequence": 0,
            "captured_at": self.received_at,
            "sample_period_ms": 10,
            "samples": [500, 501],
        }
        self.assertFalse(
            self.db.store_raw_batch(
                device_id="PPG-TEST0001",
                payload=live_payload,
                received_at=self.received_at,
            )
        )

        measurement_id = self.new_measurement_id()
        self.db.start_measurement(
            device_id="PPG-TEST0001",
            payload=self.start_payload(measurement_id),
            received_at=self.received_at,
        )

        raw_payload = {
            "measurement_id": measurement_id,
            "sequence": 0,
            "captured_at": self.received_at,
            "sample_period_ms": 10,
            "samples": [500, 501, 502],
        }
        self.assertTrue(
            self.db.store_raw_batch(
                device_id="PPG-TEST0001",
                payload=raw_payload,
                received_at=self.received_at,
            )
        )
        self.assertFalse(
            self.db.store_raw_batch(
                device_id="PPG-TEST0001",
                payload=raw_payload,
                received_at=self.received_at,
            )
        )

        result_payload = {
            "measurement_id": measurement_id,
            "finished_at": "2026-07-16T01:05:00.000+00:00",
            "status": "completed",
            "si_mean": 5.42,
            "hrv_mean": 42.51,
            "voltage_mean": 2.53,
            "adc_mean": 518,
            "mfcc_mean": [float(i) for i in range(13)],
        }
        self.db.finish_measurement(
            device_id="PPG-TEST0001",
            payload=result_payload,
            received_at=result_payload["finished_at"],
        )

        measurement = self.db.get_measurement(measurement_id)
        self.assertEqual(measurement["status"], "completed")
        self.assertEqual(measurement["duration_seconds"], 300)
        self.assertEqual(measurement["patient_name"], "Siti Aminah")
        self.assertEqual(measurement["raw_batch_count"], 1)
        self.assertEqual(measurement["raw_sample_count"], 3)
        self.assertEqual(len(measurement["mfcc"]), 13)

    def test_database_can_be_used_from_mqtt_network_thread(self):
        measurement_id = self.new_measurement_id()
        errors = []

        def mqtt_callback():
            try:
                self.db.start_measurement(
                    device_id="PPG-THREAD01",
                    payload=self.start_payload(measurement_id),
                    received_at=self.received_at,
                )
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=mqtt_callback)
        thread.start()
        thread.join()

        self.assertEqual(errors, [])
        self.assertIsNotNone(self.db.get_measurement(measurement_id))

    def test_result_without_300_second_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "belum dimulai"):
            self.db.finish_measurement(
                device_id="PPG-TEST0001",
                payload={
                    "measurement_id": f"orphan-{uuid4().hex}",
                    "finished_at": self.received_at,
                    "status": "completed",
                },
                received_at=self.received_at,
            )

    def completed_recording(self, device_id="PPG-HISTORY-TEST"):
        measurement_id = self.new_measurement_id()
        self.db.start_measurement(device_id=device_id, payload=self.start_payload(measurement_id), received_at=self.received_at)
        result = {"measurement_id": measurement_id, "status": "completed",
                  "finished_at": "2026-07-16T01:05:00Z", "si_mean": 6.2841}
        self.db.finish_measurement(device_id=device_id, payload=result, received_at=result["finished_at"])
        return measurement_id, result

    def test_history_only_lists_completed_recordings_of_selected_device(self):
        completed_id, _ = self.completed_recording()
        other_id, _ = self.completed_recording("PPG-HISTORY-OTHER")
        recording_id = self.new_measurement_id()
        self.db.start_measurement(device_id="PPG-HISTORY-TEST", payload=self.start_payload(recording_id), received_at=self.received_at)
        rows = self.db.list_history("PPG-HISTORY-TEST")
        self.assertEqual(self.db.count_history("PPG-HISTORY-TEST"), 1)
        self.assertIn(completed_id, [row["id"] for row in rows])
        self.assertNotIn(other_id, [row["id"] for row in rows])
        self.assertNotIn(recording_id, [row["id"] for row in rows])
        self.assertIsNone(next(row for row in rows if row["id"] == completed_id)["diabetes_label"])
        self.assertIsNone(self.db.update_diabetes_label(
            device_id="PPG-HISTORY-OTHER", measurement_id=completed_id, label=True, updated_at=self.received_at))
        self.assertIsNone(self.db.update_diabetes_label(
            device_id="PPG-HISTORY-TEST", measurement_id=recording_id, label=True, updated_at=self.received_at))

    def test_optional_label_can_be_set_changed_cleared_and_survives_duplicate_result(self):
        measurement_id, result = self.completed_recording()
        for label in (True, False, None, True):
            row = self.db.update_diabetes_label(
                device_id="PPG-HISTORY-TEST", measurement_id=measurement_id,
                label=label, updated_at=self.received_at,
            )
            self.assertIs(row["diabetes_label"], label)
            self.db.finish_measurement(device_id="PPG-HISTORY-TEST", payload=result, received_at=result["finished_at"])
            self.assertIs(self.db.get_measurement(measurement_id)["diabetes_label"], label)
        reopened = StorageDatabase(TEST_DATABASE_URL)
        try:
            self.assertIs(reopened.get_measurement(measurement_id)["diabetes_label"], True)
            self.assertEqual(reopened.get_measurement(measurement_id)["si_mean"], 6.2841)
        finally:
            reopened.close()

    def test_history_pagination_is_stable(self):
        for _ in range(3):
            self.completed_recording("PPG-HISTORY-PAGES")
        first = self.db.list_history("PPG-HISTORY-PAGES", limit=2)
        second = self.db.list_history("PPG-HISTORY-PAGES", limit=2, offset=2)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 1)
        self.assertEqual(self.db.count_history("PPG-HISTORY-PAGES"), 3)
        self.assertTrue({row["id"] for row in first}.isdisjoint(row["id"] for row in second))

    def test_history_migration_preserves_legacy_recordings(self):
        schema = f"history_migration_{uuid4().hex}"
        self.db.connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        url = make_conninfo(TEST_DATABASE_URL, options=f"-csearch_path={schema}")
        legacy = psycopg.connect(url, autocommit=True)
        migrated = None
        try:
            legacy.execute(SCHEMA_STATEMENTS[0])
            legacy.execute(
                "INSERT INTO measurements(id, device_id, patient_name, started_at, status, duration_seconds, created_at, updated_at) "
                "VALUES ('legacy', 'PPG-LEGACY', 'Pasien Uji Lama', now(), 'completed', 300, now(), now())"
            )
            migrated = StorageDatabase(url)
            row = migrated.get_measurement("legacy")
            self.assertEqual(row["patient_name"], "Pasien Uji Lama")
            self.assertIsNone(row["diabetes_label"])
            self.assertIsNone(row["label_updated_at"])
            self.assertEqual(migrated.list_history("PPG-LEGACY")[0]["id"], "legacy")
        finally:
            if migrated:
                migrated.close()
            legacy.close()
            self.db.connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    unittest.main()
