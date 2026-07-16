#!/usr/bin/env python3
"""Launcher pp2.py dengan integrasi MQTT tanpa mengubah file aslinya."""

from __future__ import annotations

import importlib.util
import math
import os
from pathlib import Path
from types import ModuleType

import tkinter as tk
from tkinter import messagebox

from mqtt_flow import PpgMqttFlow, load_config


DEFAULT_PP2_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "ppg-desktop-socket-client"
    / "pp2.py"
)
PP2_SOURCE = Path(os.getenv("PP2_SOURCE", DEFAULT_PP2_SOURCE)).expanduser().resolve()
MQTT_CONFIG = Path(
    os.getenv("MQTT_CONFIG", Path(__file__).with_name("config.json"))
).expanduser().resolve()


def load_pp2_module(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(
            f"pp2.py tidak ditemukan di {path}. Atur environment PP2_SOURCE."
        )

    spec = importlib.util.spec_from_file_location("pp2_original", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Gagal memuat module dari {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pp2 = load_pp2_module(PP2_SOURCE)


class ArduinoPlotMqttApp(pp2.ArduinoPlotApp):
    def __init__(self, root: tk.Tk) -> None:
        self._metric_si_m_s: float | None = None
        self._metric_hrv_ms: float | None = None
        self._metric_bmi: float | None = None
        self._metric_age_years: int | None = None
        self._metric_mfcc: list[float] | None = None
        self._metric_voltage_v: float | None = None
        self._metric_adc: float | None = None
        self._metrics_after_id: str | None = None

        super().__init__(root)
        self.mqtt = PpgMqttFlow.from_config(
            load_config(MQTT_CONFIG),
            status_callback=self.on_mqtt_status,
        )
        self._schedule_metrics_publish()

    @staticmethod
    def _number_or_none(value: object) -> float | None:
        if isinstance(value, str) or value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _schedule_metrics_publish(self) -> None:
        try:
            self._metrics_after_id = self.root.after(
                self.mqtt.metrics_interval_ms,
                self._publish_metrics_tick,
            )
        except tk.TclError:
            self._metrics_after_id = None

    def _publish_metrics_tick(self) -> None:
        self._metrics_after_id = None
        if self.running:
            recording = self.mqtt.measurement_id is not None
            self.mqtt.publish_metrics(
                # SI, BMI, dan Age membutuhkan data pasien dari Submit.
                si_m_s=self._metric_si_m_s if recording else None,
                hrv_ms=self._metric_hrv_ms,
                bmi=self._metric_bmi if recording else None,
                age_years=self._metric_age_years if recording else None,
                mfcc=self._metric_mfcc,
                voltage_v=self._metric_voltage_v,
                adc=self._metric_adc,
            )
        self._schedule_metrics_publish()

    def update_si_label(self, si: object) -> None:
        self._metric_si_m_s = self._number_or_none(si)
        super().update_si_label(si)

    def update_hrv_label(self, hrv: object) -> None:
        self._metric_hrv_ms = self._number_or_none(hrv)
        super().update_hrv_label(hrv)

    def update_bmi_label(self, bmi: object) -> None:
        self._metric_bmi = self._number_or_none(bmi)
        super().update_bmi_label(bmi)

    def update_age_value_label(self, age: object) -> None:
        number = self._number_or_none(age)
        self._metric_age_years = int(round(number)) if number is not None else None
        super().update_age_value_label(age)

    def update_mfcc_label(self, mfccs: object) -> None:
        if isinstance(mfccs, str):
            self._metric_mfcc = None
        else:
            try:
                values = [float(value) for value in mfccs]
                self._metric_mfcc = (
                    values
                    if values and all(math.isfinite(value) for value in values)
                    else None
                )
            except (TypeError, ValueError):
                self._metric_mfcc = None
        super().update_mfcc_label(mfccs)

    def update_vol_label(self, vol: object) -> None:
        self._metric_voltage_v = self._number_or_none(vol)
        super().update_vol_label(vol)

    def update_adc_label(self, adc: object) -> None:
        number = self._number_or_none(adc)
        self._metric_adc = (
            float(max(0, min(1023, round(number))))
            if number is not None
            else None
        )
        super().update_adc_label(adc)

    def on_mqtt_status(self, status: str) -> None:
        colors = {
            "connected": "#34c759",
            "connecting": "#ff9500",
            "reconnecting": "#ff9500",
            "rejected": "#ff3b30",
            "error": "#ff3b30",
            "disconnected": "#ff3b30",
        }

        def update() -> None:
            serial_status = "on" if self.running else "off"
            self.status_label.config(
                text=f"Serial: {serial_status} | MQTT: {status}",
                fg=colors.get(status, self.accent_color),
            )

        try:
            self.root.after(0, update)
        except tk.TclError:
            pass

    def start_serial(self) -> None:
        was_running = self.running
        super().start_serial()
        if not was_running and self.running:
            self.mqtt.connect()

    def stop_serial(self) -> None:
        super().stop_serial()
        if hasattr(self, "mqtt"):
            self.mqtt.disconnect()

    def serial_reader(self) -> None:
        while self.running and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("ascii").strip()
                if not line:
                    continue

                value = float(line)
                with self.data_lock:
                    self.dataList.append(value)
                    if len(self.dataList) > 5000:
                        self.dataList = self.dataList[-5000:]

                self.mqtt.add_sample(value)
            except ValueError:
                continue
            except pp2.serial.SerialException as error:
                print("Serial error:", error)
                break
            except Exception as error:
                print("Unexpected error:", error)
                break

        self.running = False
        self.mqtt.disconnect()
        try:
            self.root.after(
                0,
                lambda: self.status_label.config(
                    text="Disconnected",
                    fg="#ff3b30",
                ),
            )
        except tk.TclError:
            pass

    def submit_height(self) -> None:
        if self.measurement_in_progress:
            messagebox.showwarning(
                "Measurement Active",
                "Measurement sedang berjalan!\n"
                "Tunggu hingga selesai atau stop terlebih dahulu.",
            )
            return

        try:
            age_str = pp2.clean_number_input(self.age_entry.get())
            height_str = pp2.clean_number_input(self.height_entry.get())
            weight_str = pp2.clean_number_input(self.weight_entry.get())

            if not age_str or not height_str or not weight_str:
                raise ValueError("Empty input")

            age_yr = float(age_str)
            height_cm = float(height_str)
            weight_kg = float(weight_str)
            if age_yr <= 0 or height_cm <= 0 or weight_kg <= 0:
                raise ValueError("Negative or zero value")

            self.last_age = int(round(age_yr))
            self.last_height = height_cm
            self.last_weight = weight_kg
            self.last_filename = self.filename_entry.get().strip()
            self.last_bmi = weight_kg / ((height_cm / 100.0) ** 2)

            self.mqtt.begin_measurement(
                patient_code=self.last_filename or "N/A",
                age=self.last_age,
                height_cm=self.last_height,
                weight_kg=self.last_weight,
                bmi=self.last_bmi,
                duration_seconds=300,
            )

            self.update_bmi_label(self.last_bmi)
            self.update_age_value_label(self.last_age)
            self.measurement_in_progress = True
            self.disable_submit_button()
            self.start_logging()
            self.start_countdown()
        except RuntimeError as error:
            messagebox.showerror("MQTT Error", str(error))
        except ValueError:
            messagebox.showerror(
                "Invalid Input",
                "Masukkan umur, tinggi, berat yang valid.\n\n"
                "Pastikan:\n"
                "- Semua field terisi\n"
                "- Hanya angka dan titik desimal\n"
                "- Nilai lebih dari 0",
            )

    def finish_logging(self) -> None:
        if not self.logging_active:
            return

        avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc = (
            self.realTimePlot.compute_overall_means()
        )
        self.mqtt.complete_measurement(
            si_mean=avg_si,
            hrv_mean=avg_hrv,
            mfcc_mean=avg_mfcc,
            voltage_mean=avg_vol,
            adc_mean=avg_adc,
        )
        super().finish_logging()

    def enable_submit_button(self) -> None:
        # Method ini juga dipanggil saat popup measurement ditutup manual.
        if (
            hasattr(self, "mqtt")
            and self.mqtt.measurement_id is not None
            and not self.logging_active
        ):
            self.mqtt.cancel_measurement("measurement_window_closed")
        super().enable_submit_button()

    def on_close(self) -> None:
        if self._metrics_after_id is not None:
            try:
                self.root.after_cancel(self._metrics_after_id)
            except tk.TclError:
                pass
            self._metrics_after_id = None
        if hasattr(self, "mqtt"):
            self.mqtt.disconnect()
        super().on_close()


def main() -> None:
    root = tk.Tk()
    app = ArduinoPlotMqttApp(root)
    app.run()


if __name__ == "__main__":
    main()
