import os
import sys
import threading
import unittest
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage"))

from database import StorageDatabase  # noqa: E402


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


class StoragePolicyTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
