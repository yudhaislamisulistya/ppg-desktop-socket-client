#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage"))

from database import StorageDatabase  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("measurement_id")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL DSN; default memakai DATABASE_URL atau PG*.",
    )
    parser.add_argument("--output")
    args = parser.parse_args()

    output = Path(args.output or f"{args.measurement_id}.csv")
    database = StorageDatabase(args.database_url)
    try:
        measurement = database.get_measurement(args.measurement_id)
        if measurement is None:
            raise SystemExit("Measurement tidak ditemukan.")

        batches = database.get_raw_batches(args.measurement_id)
        with output.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "measurement_id",
                    "device_id",
                    "patient_name",
                    "batch_sequence",
                    "captured_at",
                    "sample_index",
                    "sample_period_ms",
                    "adc",
                ]
            )
            for batch in batches:
                for index, adc in enumerate(batch["samples"]):
                    writer.writerow(
                        [
                            measurement["id"],
                            measurement["device_id"],
                            measurement["patient_name"] or "",
                            batch["sequence"],
                            batch["captured_at"],
                            index,
                            batch["sample_period_ms"],
                            adc,
                        ]
                    )
        print(output)
    finally:
        database.close()


if __name__ == "__main__":
    main()
