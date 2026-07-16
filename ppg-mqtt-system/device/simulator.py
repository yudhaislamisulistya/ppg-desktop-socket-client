#!/usr/bin/env python3
"""Simulator satu alat untuk menguji broker, storage, dan frontend tanpa Arduino."""

from __future__ import annotations

import argparse
import logging
import math
import random
import time

from mqtt_flow import PpgMqttFlow, load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--preview-seconds", type=int, default=5)
    parser.add_argument("--record-seconds", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    flow = PpgMqttFlow.from_config(load_config(args.config), print)
    flow.connect()

    if not flow.wait_connected(10):
        raise SystemExit("MQTT tidak terhubung dalam 10 detik.")

    started = time.monotonic()
    recording_started: float | None = None

    try:
        while True:
            elapsed = time.monotonic() - started
            signal = 512 + 80 * math.sin(elapsed * 2 * math.pi * 1.2)
            adc = signal + random.uniform(-4, 4)
            flow.add_sample(adc)

            recording = recording_started is not None
            flow.publish_metrics(
                si_m_s=5.42 + 0.05 * math.sin(elapsed) if recording else None,
                hrv_ms=42.51 + 1.5 * math.sin(elapsed * 0.4),
                bmi=22.49 if recording else None,
                age_years=30 if recording else None,
                mfcc=[
                    float(index) + 0.1 * math.sin(elapsed + index)
                    for index in range(1, 14)
                ],
                voltage_v=adc * 5.0 / 1023.0,
                adc=adc,
            )

            if recording_started is None and elapsed >= args.preview_seconds:
                flow.begin_measurement(
                    patient_code="SIM-001",
                    age=30,
                    height_cm=170,
                    weight_kg=65,
                    bmi=22.49,
                    duration_seconds=args.record_seconds,
                )
                recording_started = time.monotonic()

            if recording_started is not None:
                recording_elapsed = time.monotonic() - recording_started
                if recording_elapsed >= args.record_seconds:
                    flow.complete_measurement(
                        si_mean=5.42,
                        hrv_mean=42.51,
                        voltage_mean=2.53,
                        adc_mean=518,
                        mfcc_mean=[float(i) for i in range(1, 14)],
                    )
                    break

            time.sleep(flow.sample_period_ms / 1000.0)
    finally:
        flow.disconnect()


if __name__ == "__main__":
    main()
