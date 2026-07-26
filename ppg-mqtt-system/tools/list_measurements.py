#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage"))

from database import StorageDatabase  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL DSN; default memakai DATABASE_URL atau PG*.",
    )
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    database = StorageDatabase(args.database_url)
    try:
        rows = database.list_measurements(args.limit)
        if not rows:
            print("Belum ada measurement.")
            return

        print("ID\tDEVICE\tPATIENT\tSTARTED\tSTATUS\tSAMPLES")
        for row in rows:
            print(
                f"{row['id']}\t{row['device_id']}\t{row['patient_name'] or '-'}\t"
                f"{row['started_at']}\t{row['status']}\t{row['raw_sample_count']}"
            )
    finally:
        database.close()


if __name__ == "__main__":
    main()
