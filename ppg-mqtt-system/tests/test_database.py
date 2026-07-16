import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage"))

from database import StorageDatabase  # noqa: E402


class StorageDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = StorageDatabase(Path(self.temp_dir.name) / "test.sqlite3")
        self.received_at = "2026-07-16T01:00:00.000+00:00"

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

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

        start_payload = {
            "measurement_id": "measurement-1",
            "started_at": self.received_at,
            "patient_code": "P-001",
            "duration_seconds": 300,
            "age": 30,
            "height_cm": 170,
            "weight_kg": 65,
            "bmi": 22.49,
        }
        self.db.start_measurement(
            device_id="PPG-TEST0001",
            payload=start_payload,
            received_at=self.received_at,
        )

        raw_payload = {
            "measurement_id": "measurement-1",
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
            "measurement_id": "measurement-1",
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

        measurement = self.db.get_measurement("measurement-1")
        self.assertEqual(measurement["status"], "completed")
        self.assertEqual(measurement["raw_batch_count"], 1)
        self.assertEqual(measurement["raw_sample_count"], 3)
        self.assertEqual(len(json.loads(measurement["mfcc_json"])), 13)


if __name__ == "__main__":
    unittest.main()
