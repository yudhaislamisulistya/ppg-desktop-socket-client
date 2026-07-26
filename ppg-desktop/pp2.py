import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from tkinter import font as tkfont
import time
import serial
import serial.tools.list_ports as list_ports
# pyrefly: ignore [missing-import]
import matplotlib.pyplot as plt
# pyrefly: ignore [missing-import]
import matplotlib.animation as animation
# pyrefly: ignore [missing-import]
import numpy as np
# pyrefly: ignore [missing-import]
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
# pyrefly: ignore [missing-import]
from scipy.signal import find_peaks
# pyrefly: ignore [missing-import]
import librosa
import threading
import csv
from datetime import datetime
import os
import platform
import warnings
import re
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
MQTT_DEVICE_DIR = Path(
    os.getenv(
        "MQTT_DEVICE_DIR",
        APP_DIR.parent / "ppg-mqtt-system" / "device",
    )
).expanduser().resolve()
MQTT_FLOW_FILE = MQTT_DEVICE_DIR / "mqtt_flow.py"
if not MQTT_FLOW_FILE.exists():
    raise FileNotFoundError(
        f"mqtt_flow.py tidak ditemukan di {MQTT_FLOW_FILE}. "
        "Atur environment MQTT_DEVICE_DIR ke folder device ppg-mqtt-system."
    )
if str(MQTT_DEVICE_DIR) not in sys.path:
    sys.path.insert(0, str(MQTT_DEVICE_DIR))

# pyrefly: ignore [missing-import]
from mqtt_flow import PpgMqttFlow, load_config


MQTT_CONFIG = Path(
    os.getenv("MQTT_CONFIG", APP_DIR / "mqtt_config.json")
).expanduser().resolve()

warnings.filterwarnings("ignore", category=UserWarning)

SERIAL_BAUD = 9600

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


# ==================== TEMA & BAHASA ====================
# Bahasa visual monitor pasien bedside. Nilai warna sengaja identik dengan
# ppg-mqtt-system/frontend/styles.css supaya satu metrik selalu punya warna
# yang sama, baik di layar alat maupun di dashboard web.
DARK_THEME = {
    "bg": "#070b10",
    "panel": "#0d131b",
    "raised": "#131c27",
    "input": "#080e15",
    "line": "#1b2734",
    "line_soft": "#141d28",
    "text": "#e6eef6",
    "text_dim": "#7b8fa4",
    "text_faint": "#6b8095",
    "ch_pleth": "#22d3ee",
    "ch_si": "#fbbf24",
    "ch_hrv": "#4ade80",
    "ch_bmi": "#a78bfa",
    "ch_age": "#f472b6",
    "ch_volt": "#38bdf8",
    "ch_adc": "#94a3b8",
    "ch_mfcc": "#2dd4bf",
    "rec": "#fb4e62",
    "ok": "#4ade80",
    "warn": "#fbbf24",
    "plot_bg": "#050a0f",
    "ch_mfcc_negative": "#1b8f86",
}

LIGHT_THEME = {
    "bg": "#f1f5f9",
    "panel": "#ffffff",
    "raised": "#e2e8f0",
    "input": "#ffffff",
    "line": "#cbd5e1",
    "line_soft": "#e2e8f0",
    "text": "#0f172a",
    "text_dim": "#475569",
    "text_faint": "#64748b",
    "ch_pleth": "#0e7490",
    "ch_si": "#a16207",
    "ch_hrv": "#15803d",
    "ch_bmi": "#7c3aed",
    "ch_age": "#be185d",
    "ch_volt": "#0369a1",
    "ch_adc": "#475569",
    "ch_mfcc": "#0f766e",
    "rec": "#be123c",
    "ok": "#15803d",
    "warn": "#a16207",
    "plot_bg": "#f8fafc",
    "ch_mfcc_negative": "#115e59",
}

THEMES = {"dark": DARK_THEME, "light": LIGHT_THEME}
THEME = DARK_THEME.copy()

I18N = {
    "id": {
        "refresh": "Segarkan",
        "start": "Mulai",
        "stop": "Berhenti",
        "settings": "Pengaturan",
        "patient_name": "NAMA PASIEN",
        "age": "UMUR",
        "height": "TINGGI CM",
        "weight": "BERAT KG",
        "numpad": "Papan angka",
        "submit": "Kirim",
        "waveform": "Gelombang",
        "samples": "{samples} sampel · {peaks} puncak",
        "mfcc_waiting": "menunggu data",
        "mfcc_summary": "{count} koefisien · puncak {peak:.1f}",
        "mfcc_detail": "Detail",
        "mfcc_detail_title": "Detail Koefisien MFCC",
        "mfcc_detail_empty": "Belum ada nilai koefisien MFCC.",
        "mfcc_beat_short": "Denyut terlalu pendek",
        "mfcc_waiting_peaks": "Menunggu puncak (MFCC)",
        "mfcc_calculating": "Menghitung…",
        "mfcc_error": "Kesalahan MFCC",
        "theme_dark": "Tema: Gelap",
        "theme_light": "Tema: Terang",
        "age_unit": "th",
        "voltage": "VOLTASE",
        "status_connected": "terhubung",
        "status_connecting": "menghubungkan",
        "status_reconnecting": "menyambung ulang",
        "status_rejected": "ditolak",
        "status_error": "gagal",
        "status_disconnected": "terputus",
        "status_off": "mati",
        "ports_found": "{count} port terdeteksi",
        "no_serial_port": "Tidak ada port serial",
        "no_port_title": "Port Belum Dipilih",
        "no_port_message": "Silakan pilih port terlebih dahulu.",
        "serial_error": "Gagal membuka port {port}:\n{error}",
        "serial_error_title": "Kesalahan Serial",
        "mqtt_start_error": "Gagal memulai MQTT:\n{error}",
        "mqtt_error_title": "Kesalahan MQTT",
        "mqtt_config_error_title": "Kesalahan Konfigurasi MQTT",
        "mqtt_timeout_title": "MQTT Tidak Terhubung",
        "mqtt_timeout_message": (
            "Serial berhasil dibuka, tetapi MQTT tidak terhubung dalam 10 detik.\n\n"
            "Periksa konfigurasi {config}, koneksi internet, Device ID, username, "
            "dan password MQTT."
        ),
        "settings_title": "Pengaturan MFCC",
        "mfcc_parameters": "PARAMETER MFCC",
        "sample_rate": "Laju sampel (Hz)",
        "frame_length": "Panjang frame (ms)",
        "hop_length": "Panjang hop (ms)",
        "mfcc_count": "Jumlah MFCC",
        "window": "Jendela",
        "mfcc_mode": "Mode MFCC",
        "cancel": "Batal",
        "save": "Simpan",
        "invalid_input_title": "Input Tidak Valid",
        "invalid_settings": "Pastikan semua parameter diisi dengan benar.",
        "csv_saved": "CSV tersimpan: {filename}",
        "csv_error_title": "Kesalahan CSV",
        "measurement_active_title": "Pengukuran Aktif",
        "measurement_active": (
            "Pengukuran sedang berjalan!\n"
            "Tunggu hingga selesai atau berhenti terlebih dahulu."
        ),
        "invalid_measurement": (
            "Masukkan umur, tinggi, dan berat yang valid.\n\nPastikan:\n"
            "- Semua field terisi\n- Hanya angka dan titik desimal\n- Nilai lebih dari 0"
        ),
        "measurement_title": "Pengukuran 300 detik",
        "recording": "MEREKAM",
        "seconds_left": "detik tersisa",
        "measuring": "mengukur…",
        "stop_close": "Berhenti & Tutup",
        "completed": "Selesai",
        "unavailable": "tidak tersedia",
    },
    "en": {
        "refresh": "Refresh",
        "start": "Start",
        "stop": "Stop",
        "settings": "Settings",
        "patient_name": "PATIENT NAME",
        "age": "AGE",
        "height": "HEIGHT CM",
        "weight": "WEIGHT KG",
        "numpad": "Numpad",
        "submit": "Submit",
        "waveform": "Waveform",
        "samples": "{samples} samples · {peaks} peaks",
        "mfcc_waiting": "waiting for data",
        "mfcc_summary": "{count} coefficients · peak {peak:.1f}",
        "mfcc_detail": "Details",
        "mfcc_detail_title": "MFCC Coefficient Details",
        "mfcc_detail_empty": "No MFCC coefficient values yet.",
        "mfcc_beat_short": "Beat too short",
        "mfcc_waiting_peaks": "Waiting for peaks (MFCC)",
        "mfcc_calculating": "Calculating…",
        "mfcc_error": "MFCC error",
        "theme_dark": "Theme: Dark",
        "theme_light": "Theme: Light",
        "age_unit": "yr",
        "voltage": "VOLTAGE",
        "status_connected": "connected",
        "status_connecting": "connecting",
        "status_reconnecting": "reconnecting",
        "status_rejected": "rejected",
        "status_error": "failed",
        "status_disconnected": "disconnected",
        "status_off": "off",
        "ports_found": "{count} ports detected",
        "no_serial_port": "No serial port detected",
        "no_port_title": "No Port Selected",
        "no_port_message": "Please select a port first.",
        "serial_error": "Failed to open port {port}:\n{error}",
        "serial_error_title": "Serial Error",
        "mqtt_start_error": "Failed to start MQTT:\n{error}",
        "mqtt_error_title": "MQTT Error",
        "mqtt_config_error_title": "MQTT Configuration Error",
        "mqtt_timeout_title": "MQTT Not Connected",
        "mqtt_timeout_message": (
            "The serial port opened, but MQTT did not connect within 10 seconds.\n\n"
            "Check {config}, the internet connection, Device ID, MQTT username, "
            "and password."
        ),
        "settings_title": "MFCC Settings",
        "mfcc_parameters": "MFCC PARAMETERS",
        "sample_rate": "Sample rate (Hz)",
        "frame_length": "Frame length (ms)",
        "hop_length": "Hop length (ms)",
        "mfcc_count": "MFCC count",
        "window": "Window",
        "mfcc_mode": "MFCC mode",
        "cancel": "Cancel",
        "save": "Save",
        "invalid_input_title": "Invalid Input",
        "invalid_settings": "Make sure every parameter contains a valid value.",
        "csv_saved": "CSV saved: {filename}",
        "csv_error_title": "CSV Error",
        "measurement_active_title": "Measurement Active",
        "measurement_active": (
            "A measurement is already running!\n"
            "Wait until it finishes or stop it first."
        ),
        "invalid_measurement": (
            "Enter a valid age, height, and weight.\n\nMake sure:\n"
            "- Every field is filled\n- Values contain only numbers and decimals\n"
            "- Values are greater than 0"
        ),
        "measurement_title": "300-second Measurement",
        "recording": "RECORDING",
        "seconds_left": "seconds remaining",
        "measuring": "measuring…",
        "stop_close": "Stop & Close",
        "completed": "Completed",
        "unavailable": "unavailable",
    },
}


def translated(language, key, **values):
    return I18N.get(language, I18N["id"]).get(key, key).format(**values)


def mfcc_detail_lines(values):
    if not values:
        return []
    return [f"C{index:02d}    {float(value): .6f}" for index, value in enumerate(values, 1)]


def clean_number_input(text):
    """Membersihkan input angka dari karakter tidak valid"""
    if text is None:
        return ""
    cleaned = re.sub(r'[^\d.\-]', '', str(text).strip())
    parts = cleaned.split('.')
    if len(parts) > 2:
        cleaned = parts[0] + '.' + ''.join(parts[1:])
    return cleaned


def pick_font(candidates, fallback="Helvetica"):
    """Memilih font pertama yang benar-benar tersedia di sistem.

    Raspberry Pi OS umumnya punya keluarga DejaVu, macOS punya Helvetica.
    """
    try:
        available = set(tkfont.families())
    except tk.TclError:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Persegi bersudut membulat memakai polygon halus."""
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class FlatButton(tk.Canvas):
    """Tombol bersudut membulat; Tkinter tidak menyediakannya secara bawaan."""

    def __init__(self, parent, text, command, *, fill, fg, font,
                 width=88, height=34, surface=None, radius=8):
        super().__init__(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=surface or parent.cget("bg"),
            takefocus=1,
        )
        self._command = command
        self._fill = fill
        self._fg = fg
        self._enabled = True
        # Jangan pakai nama _w/_h: Tkinter memakai self._w sebagai path Tcl widget.
        self._btn_w = width
        self._btn_h = height
        self._radius = radius

        self._shape = round_rect(self, 1, 1, width - 1, height - 1, radius, fill=fill, outline="")
        self._label = self.create_text(
            width / 2, height / 2 + 1, text=text, fill=fg, font=font,
        )

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", self._on_keyboard)
        self.bind("<space>", self._on_keyboard)
        self.bind("<FocusIn>", self._on_enter)
        self.bind("<FocusOut>", self._on_leave)

    @staticmethod
    def _shade(color, factor):
        color = color.lstrip("#")
        rgb = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
        if factor >= 0:
            rgb = [int(value + (255 - value) * factor) for value in rgb]
        else:
            rgb = [int(value * (1 + factor)) for value in rgb]
        return "#%02x%02x%02x" % tuple(max(0, min(255, value)) for value in rgb)

    def _paint(self, fill, fg):
        self.itemconfig(self._shape, fill=fill)
        self.itemconfig(self._label, fill=fg)

    def _on_enter(self, _event):
        if self._enabled:
            self._paint(self._shade(self._fill, 0.14), self._fg)

    def _on_leave(self, _event):
        if self._enabled:
            self._paint(self._fill, self._fg)

    def _on_press(self, _event):
        if self._enabled:
            self._paint(self._shade(self._fill, -0.18), self._fg)

    def _on_release(self, event):
        if not self._enabled:
            return
        self._paint(self._fill, self._fg)
        if 0 <= event.x <= self._btn_w and 0 <= event.y <= self._btn_h and self._command:
            self._command()

    def _on_keyboard(self, _event):
        if self._enabled and self._command:
            self._command()

    def set_text(self, text):
        self.itemconfig(self._label, text=text)

    def apply_palette(self, color_map):
        self._fill = color_map.get(self._fill, self._fill)
        self._fg = color_map.get(self._fg, self._fg)
        self.configure(bg=color_map.get(self.cget("bg"), self.cget("bg")))
        self._paint(self._fill, self._fg)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        if self._enabled:
            self._paint(self._fill, self._fg)
        else:
            self._paint(THEME["raised"], THEME["text_faint"])


class StatusLamp(tk.Frame):
    """Lampu indikator: titik berwarna + label, seperti panel alat medis."""

    def __init__(self, parent, caption, font_key, font_value, surface):
        super().__init__(parent, bg=surface)
        self.dot = tk.Canvas(self, width=9, height=9, highlightthickness=0, bd=0, bg=surface)
        self._circle = self.dot.create_oval(1, 1, 8, 8, fill=THEME["text_faint"], outline="")
        self.dot.pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(
            self, text=caption, bg=surface, fg=THEME["text_faint"], font=font_key,
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.value = tk.Label(self, text="—", bg=surface, fg=THEME["text_dim"], font=font_value)
        self.value.pack(side=tk.LEFT)

    def set(self, text, color):
        self.dot.itemconfig(self._circle, fill=color)
        self.value.config(text=text, fg=color)


class MetricTile(tk.Frame):
    """Kartu satu metrik dengan pita warna kanal di sisi kiri."""

    def __init__(self, parent, caption, unit, accent, font_key, font_value, font_unit):
        super().__init__(parent, bg=THEME["panel"], highlightthickness=1,
                         highlightbackground=THEME["line"], highlightcolor=THEME["line"])
        self.accent = accent

        tk.Frame(self, bg=accent, width=3).pack(side=tk.LEFT, fill=tk.Y)

        body = tk.Frame(self, bg=THEME["panel"])
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=9, pady=3)

        self.caption_label = tk.Label(
            body, text=caption, bg=THEME["panel"], fg=THEME["text_faint"],
            font=font_key, anchor="w",
        )
        self.caption_label.pack(fill=tk.X)

        row = tk.Frame(body, bg=THEME["panel"])
        row.pack(fill=tk.X)

        self.value = tk.Label(
            row, text="—", bg=THEME["panel"], fg=THEME["text_faint"],
            font=font_value, anchor="w",
        )
        self.value.pack(side=tk.LEFT)

        self.unit_label = None
        if unit:
            self.unit_label = tk.Label(
                row, text=unit, bg=THEME["panel"], fg=THEME["text_faint"],
                font=font_unit, anchor="w",
            )
            self.unit_label.pack(side=tk.LEFT, padx=(4, 0), pady=(0, 1))

    def set_value(self, text, active=True):
        self.value.config(
            text=text,
            fg=self.accent if active else THEME["text_faint"],
        )


class MfccStrip(tk.Canvas):
    """Batang MFCC menyimpang dari garis nol: positif ke atas, negatif ke bawah."""

    def __init__(self, parent, height=52):
        super().__init__(parent, height=height, highlightthickness=0, bd=0, bg=THEME["panel"])
        self._values = None
        self._message = "menunggu koefisien"
        self._font = ("Helvetica", 8)
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_font(self, font):
        self._font = font

    def set_values(self, values):
        self._values = list(values)
        self.redraw()

    def set_message(self, message):
        self._values = None
        self._message = message
        self.redraw()

    def redraw(self):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            return

        middle = height / 2
        self.create_line(0, middle, width, middle, fill=THEME["line"])

        if not self._values:
            self.create_text(
                width / 2, middle, text=self._message,
                fill=THEME["text_faint"], font=self._font,
            )
            return

        count = len(self._values)
        peak = max((abs(float(value)) for value in self._values), default=1.0) or 1.0
        slot = width / count
        bar_width = max(3.0, slot * 0.62)
        limit = middle - 4

        for index, raw in enumerate(self._values):
            value = float(raw)
            magnitude = max(2.0, (abs(value) / peak) * limit)
            center = slot * (index + 0.5)
            x1 = center - bar_width / 2
            x2 = center + bar_width / 2
            if value >= 0:
                self.create_rectangle(
                    x1, middle - magnitude, x2, middle,
                    fill=THEME["ch_mfcc"], outline="",
                )
            else:
                self.create_rectangle(
                    x1, middle, x2, middle + magnitude,
                    fill=THEME["ch_mfcc_negative"], outline="",
                )


class AnimationPlot:
    def __init__(self, buffer_percentage=0.1, window_size=5, filter_window_size=40, min_distance=20):
        self.buffer_percentage = buffer_percentage
        self.window_size = window_size
        self.filter_window_size = filter_window_size
        self.min_distance = min_distance

        self.si_accumulator = []
        self.hrv_accumulator = []
        self.mfcc_accumulator = []
        self.vol_accumulator = []
        self.adc_accumulator = []
        self.lock = threading.Lock()

        self.sample_period_ms = 10.0

        self.ibi_raw_list = []
        self.last_hrv_value = 0.0
        self.last_si_value = 0.0

        self.mfcc_params = {
            "sr": 100,
            "frame_ms": 200.0,
            "hop_ms": 40.0,
            "n_mfcc": 13,
            "window": "hamming",
        }

        self.mfcc_mode = "standard"

    def reset_accumulators(self):
        with self.lock:
            self.si_accumulator = []
            self.hrv_accumulator = []
            self.mfcc_accumulator = []
            self.vol_accumulator = []
            self.adc_accumulator = []

    def set_mfcc_params(self, sr, frame_ms, hop_ms, n_mfcc, window):
        self.mfcc_params["sr"] = sr
        self.mfcc_params["frame_ms"] = frame_ms
        self.mfcc_params["hop_ms"] = hop_ms
        self.mfcc_params["n_mfcc"] = n_mfcc
        self.mfcc_params["window"] = window

    def set_mfcc_mode(self, mode):
        if mode in ("standard", "peak"):
            self.mfcc_mode = mode

    def compute_si_medical(self, signal, systolic_idx, app, rr_samples=None):
        sample_period_ms = self.sample_period_ms
        min_delay_ms = 80.0
        max_delay_ms = 400.0

        min_offset = int(min_delay_ms / sample_period_ms)
        max_offset = int(max_delay_ms / sample_period_ms)

        if rr_samples is not None:
            max_offset = min(max_offset, int(rr_samples * 0.7))

        start = systolic_idx + min_offset
        end = systolic_idx + max_offset

        if start >= len(signal):
            return None, None
        if end > len(signal):
            end = len(signal)
        if start >= end:
            return None, None

        segment = signal[start:end]
        second_peaks, _ = find_peaks(segment, prominence=5)
        if len(second_peaks) == 0:
            return None, None

        diastolic_idx = start + second_peaks[0]
        delta_samples = diastolic_idx - systolic_idx
        if delta_samples <= 0:
            return None, None

        delta_t_s = (delta_samples * sample_period_ms) / 1000.0
        if app.last_height is None or delta_t_s <= 0:
            return None, None

        height_m = app.last_height / 100.0
        si = height_m / delta_t_s
        return si, delta_t_s * 1000.0

    def compute_hrv_rmssd(self):
        if len(self.ibi_raw_list) < 3:
            return None

        recent = np.array(self.ibi_raw_list[-50:], dtype=float)
        median_ibi = np.median(recent)
        if median_ibi <= 0:
            return None

        tol = 0.25 * median_ibi
        mask = np.abs(recent - median_ibi) <= tol
        clean = recent[mask]
        if len(clean) < 3:
            return None

        diffs = np.diff(clean)
        rmssd = float(np.sqrt(np.mean(diffs ** 2)))
        return rmssd

    def calculate_mfccs(self, data):
        params = self.mfcc_params
        sr = params["sr"]
        frame_ms = params["frame_ms"]
        hop_ms = params["hop_ms"]
        n_mfcc = params["n_mfcc"]
        window = params["window"]

        data = np.array(data, dtype=float)
        if data.size == 0:
            return None

        if np.all(data == data[0]):
            data = data.astype(float) + 1e-6 * np.random.randn(*data.shape)

        frame_len = max(1, int(sr * frame_ms / 1000.0))
        hop_len = max(1, int(sr * hop_ms / 1000.0))

        if len(data) < frame_len:
            data = np.pad(data, (0, frame_len - len(data)), mode="edge")

        n_fft = 1
        while n_fft < frame_len:
            n_fft *= 2

        if n_fft > len(data):
            n_fft = len(data)
            n_fft = 2 ** int(np.floor(np.log2(n_fft)))
            if n_fft < 16:
                n_fft = 16

        win_length = min(frame_len, n_fft)

        try:
            S = librosa.feature.melspectrogram(
                y=data,
                sr=sr,
                n_fft=n_fft,
                hop_length=hop_len,
                win_length=win_length,
                window=window,
                power=2.0,
            )

            mfccs = librosa.feature.mfcc(
                S=librosa.power_to_db(S),
                n_mfcc=n_mfcc,
            )

            return np.mean(mfccs, axis=1)
        except Exception:
            return None

    def getPlotFormat(self, dataList, ax):
        """Mengatur sumbu Y agar statis dengan rentang positif dan negatif"""
        ax.set_ylim([-200.0, 200.0])
        ax.set_yticks([-200, -100, 0, 100, 200])

    def compute_overall_means(self):
        with self.lock:
            avg_si = float(np.mean(self.si_accumulator)) if self.si_accumulator else float("nan")
            avg_hrv = float(np.mean(self.hrv_accumulator)) if self.hrv_accumulator else float("nan")
            avg_vol = float(np.mean(self.vol_accumulator)) if self.vol_accumulator else float("nan")
            avg_adc = float(np.mean(self.adc_accumulator)) if self.adc_accumulator else float("nan")
            avg_mfcc = np.mean(self.mfcc_accumulator, axis=0) if self.mfcc_accumulator else None
        return avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc

    def animate(self, i, ax, app):
        with app.data_lock:
            dataList = list(app.dataList)

        if not dataList:
            return

        dataList = dataList[-1000:]
        data = np.array(dataList, dtype=float)

        last_adc = data[-1]
        voltage = last_adc * 5.0 / 1023.0

        app.update_adc_label(last_adc)
        app.update_vol_label(voltage)

        win_s = self.window_size
        if len(data) >= win_s:
            k = np.ones(win_s) / win_s
            smooth = np.convolve(data, k, mode="same")
        else:
            smooth = data

        win_b = self.filter_window_size
        if len(data) >= win_b:
            kb = np.ones(win_b) / win_b
            baseline = np.convolve(smooth, kb, mode="same")
        else:
            baseline = np.full_like(smooth, np.mean(smooth))

        signal = smooth - baseline
        max_abs = np.max(np.abs(signal)) if np.max(np.abs(signal)) > 0 else 1.0
        signal = signal / max_abs * 200.0

        ax.clear()
        app.style_axes(ax)
        self.getPlotFormat(None, ax)
        ax.set_xlim(0, 1000)
        ax.set_xticks([0, 200, 400, 600, 800, 1000])
        ax.plot(signal, color=THEME["ch_pleth"], linewidth=1.3, solid_joinstyle="round")

        min_rr_ms = 400.0
        min_distance_samples = int(min_rr_ms / self.sample_period_ms)

        try:
            peak_indices, _ = find_peaks(
                signal,
                distance=max(self.min_distance, min_distance_samples),
                prominence=20
            )
        except Exception:
            peak_indices = np.array([], dtype=int)

        # Titik pada puncak lebih tenang dibanding garis vertikal penuh.
        if len(peak_indices):
            ax.plot(
                peak_indices, signal[peak_indices],
                linestyle="none", marker="o", markersize=3.0,
                color=THEME["ch_si"], zorder=5,
            )

        # Penanda sampel terbaru, meniru kepala tulis monitor.
        ax.plot(
            [len(signal) - 1], [signal[-1]],
            linestyle="none", marker="o", markersize=4.5,
            color="#a5f3fc", zorder=6,
        )

        app.update_trace_meta(len(dataList), len(peak_indices))

        si_value = float(self.last_si_value)
        hrv_value = float(self.last_hrv_value)
        mfcc_value = None

        if len(peak_indices) >= 2:
            last_peak = peak_indices[-1]
            prev_peak = peak_indices[-2]
            ibi = (last_peak - prev_peak) * self.sample_period_ms

            if 300.0 <= ibi <= 2000.0:
                self.ibi_raw_list.append(ibi)
                if len(self.ibi_raw_list) > 200:
                    self.ibi_raw_list = self.ibi_raw_list[-200:]

                rmssd = self.compute_hrv_rmssd()
                if rmssd is not None:
                    hrv_value = rmssd
                    self.last_hrv_value = hrv_value
                    app.update_hrv_label(hrv_value)
                else:
                    app.update_hrv_label("Collecting...")
            else:
                app.update_hrv_label("IBI out of range")
        else:
            app.update_hrv_label("Waiting peaks")

        if len(peak_indices) >= 1:
            systolic_idx = peak_indices[-1]
            rr_samples = (systolic_idx - peak_indices[-2]) if len(peak_indices) >= 2 else None

            if app.last_height is None:
                app.update_si_label("Set height")
            else:
                si_med, _ = self.compute_si_medical(signal, systolic_idx, app, rr_samples=rr_samples)
                if si_med is not None:
                    si_value = float(si_med)
                    self.last_si_value = si_value
                    app.update_si_label(si_value)
                else:
                    if rr_samples is not None and rr_samples > 0:
                        height_m = app.last_height / 100.0
                        delta_t_s = (rr_samples * self.sample_period_ms) / 1000.0
                        if delta_t_s > 0:
                            si_value = float(height_m / delta_t_s)
                            self.last_si_value = si_value
                            app.update_si_label(si_value)
                        else:
                            app.update_si_label("Waiting SI")
                    else:
                        app.update_si_label("Waiting SI")
        else:
            app.update_si_label("Waiting peaks")

        try:
            segment_for_mfcc = None
            if self.mfcc_mode == "standard":
                segment_for_mfcc = signal
            elif self.mfcc_mode == "peak":
                if len(peak_indices) >= 2:
                    start = peak_indices[-2]
                    end = peak_indices[-1]
                    if end > start and (end - start) >= 5:
                        segment_for_mfcc = signal[start: end]
                    else:
                        app.update_mfcc_label("Beat too short")
                else:
                    app.update_mfcc_label("Waiting peaks (MFCC)")

            if segment_for_mfcc is not None:
                mfccs = self.calculate_mfccs(segment_for_mfcc)
                if mfccs is not None:
                    mfcc_value = mfccs
                    app.update_mfcc_label(mfccs)
                else:
                    app.update_mfcc_label("Calculating...")
            else:
                mfcc_value = None

        except Exception:
            mfcc_value = None
            app.update_mfcc_label("Err MFCC")

        if getattr(app, "logging_active", False):
            with self.lock:
                self.vol_accumulator.append(float(voltage))
                self.adc_accumulator.append(float(last_adc))

                if isinstance(si_value, (int, float)) and np.isfinite(si_value):
                    self.si_accumulator.append(float(si_value))
                if isinstance(hrv_value, (int, float)) and np.isfinite(hrv_value):
                    self.hrv_accumulator.append(float(hrv_value))
                if mfcc_value is not None and isinstance(mfcc_value, (list, np.ndarray)) and len(mfcc_value) == 13:
                    self.mfcc_accumulator.append(np.array(mfcc_value, dtype=float))


class ArduinoPlotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PPG Monitor")

        THEME.clear()
        THEME.update(DARK_THEME)
        self.theme_name = "dark"
        self.language = "id"
        self._text_bindings = []
        self._window_title_bindings = []

        self.bg_color = THEME["bg"]
        self.accent_color = THEME["ch_pleth"]
        self.root.configure(bg=self.bg_color)

        # ===== FONT =====
        family_ui = pick_font(
            ["IBM Plex Sans", "DejaVu Sans", "Helvetica Neue", "Helvetica", "Arial"]
        )
        family_display = pick_font(
            ["IBM Plex Sans Condensed", "DejaVu Sans Condensed", "Roboto Condensed",
             "Arial Narrow", "Helvetica Neue", "Helvetica"]
        )
        family_mono = pick_font(
            ["IBM Plex Mono", "DejaVu Sans Mono", "Menlo", "Consolas", "Courier New"]
        )

        self.font_key = (family_ui, 8, "bold")
        self.font_small = (family_ui, 9)
        self.font_mono = (family_mono, 9)
        # 18pt adalah batas agar enam tile tetap muat pada layar Pi 480 piksel.
        self.font_value = (family_display, 18, "bold")
        self.font_unit = (family_ui, 8)
        self.font_h2 = (family_ui, 11, "bold")
        self.font_countdown = (family_display, 44, "bold")

        # Nama lama dipertahankan karena dipakai popup dan handler lain.
        self.scale = 1.0
        self.btn_font = (family_ui, 9, "bold")
        self.lbl_font = (family_ui, 9)

        # ===== WINDOW =====
        # Target utama layar sentuh Raspberry Pi 7 inci (800x480), tetapi tetap
        # rapi bila dijalankan pada monitor yang lebih besar.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = min(1024, max(800, screen_width - 40))
        window_height = min(640, max(460, screen_height - 60))

        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)

        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.minsize(780, 450)
        self.root.resizable(True, True)

        # Serial & data
        self.running = False
        self.ser = None
        self.serial_thread = None
        self.mqtt_cleanup_thread = None
        self.start_after_stop = False
        self.dataList = []
        self.data_lock = threading.Lock()

        # Nilai terbaru yang dikirim ke topic ppg/{device_id}/metrics.
        self.latest_si = None
        self.latest_hrv = None
        self.latest_bmi = None
        self.latest_age = None
        self.latest_mfcc = None
        self.latest_voltage = None
        self.latest_adc = None
        self.trace_sample_count = 0
        self.trace_peak_count = 0
        self.metrics_after_id = None
        self.mqtt_connect_after_id = None

        # Antropometri
        self.last_age = None
        self.last_height = None
        self.last_weight = None
        self.last_bmi = None
        self.last_patient_name = ""
        self.active_entry = None

        # Logging
        self.logging_active = False
        self.logging_start_time = None

        # Flag untuk mencegah submit ganda
        self.measurement_in_progress = False

        # Countdown
        self.countdown_value = 300
        self.countdown_after_id = None

        # Window references
        self.averages_window = None
        self.numpad_window = None
        self.settings_window = None
        self.mfcc_detail_window = None
        self.mfcc_detail_text = None

        # Countdown label reference
        self.countdown_label = None
        self.countdown_bar = None
        self.countdown_bar_fill = None
        self.avg_si_label = None
        self.avg_hrv_label = None
        self.avg_mfcc_label = None
        self.avg_vol_label = None
        self.avg_adc_label = None

        self._serial_state = ("off", THEME["text_faint"])
        self._mqtt_state = ("disconnected", THEME["text_faint"])
        self._hint_after_id = None

        self._build_style()
        self._build_header()
        self._build_footer()
        self._build_body()

        try:
            self.mqtt = self.create_mqtt_flow()
        except (OSError, KeyError, TypeError, ValueError) as error:
            messagebox.showerror(
                self.t("mqtt_config_error_title"),
                f"Gagal membaca konfigurasi MQTT:\n{MQTT_CONFIG}\n\n{error}",
            )
            raise

        self.device_label.config(text=self.mqtt.device_id)

        self.realTimePlot = AnimationPlot(
            buffer_percentage=0.1,
            window_size=5,
            filter_window_size=40,
            min_distance=20
        )

        self.ani = animation.FuncAnimation(
            self.fig,
            self.realTimePlot.animate,
            fargs=(self.ax, self),
            interval=50,
            cache_frame_data=False,
            save_count=100
        )

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_ports()
        self.schedule_metrics_publish()

    # ==================== TATA LETAK ====================

    def t(self, key, **values):
        return translated(getattr(self, "language", "id"), key, **values)

    def _bind_text(self, widget, key):
        self._text_bindings.append((widget, key))
        if isinstance(widget, FlatButton):
            widget.set_text(self.t(key))
        else:
            widget.config(text=self.t(key))
        return widget

    def _bind_window_title(self, window, key):
        self._window_title_bindings.append((window, key))
        window.title(self.t(key))

    def toggle_language(self):
        self.language = "en" if self.language == "id" else "id"
        alive = []
        for widget, key in self._text_bindings:
            try:
                if not widget.winfo_exists():
                    continue
                if isinstance(widget, FlatButton):
                    widget.set_text(self.t(key))
                else:
                    widget.config(text=self.t(key))
                alive.append((widget, key))
            except tk.TclError:
                continue
        self._text_bindings = alive

        alive_titles = []
        for window, key in self._window_title_bindings:
            try:
                if not window.winfo_exists():
                    continue
                window.title(self.t(key))
                alive_titles.append((window, key))
            except tk.TclError:
                continue
        self._window_title_bindings = alive_titles

        self.language_button.set_text("EN" if self.language == "id" else "ID")
        self.theme_button.set_text(self.t(f"theme_{self.theme_name}"))
        self._render_lamps()
        self.update_trace_meta(
            self.trace_sample_count,
            self.trace_peak_count,
        )
        self.update_mfcc_label(
            self.latest_mfcc if self.latest_mfcc is not None else self.t("mfcc_waiting")
        )
        if self.logging_active:
            for label in (
                self.avg_si_label,
                self.avg_hrv_label,
                self.avg_vol_label,
                self.avg_adc_label,
                self.avg_mfcc_label,
            ):
                if label:
                    try:
                        label.config(text=self.t("measuring"))
                    except tk.TclError:
                        pass
        self.render_mfcc_details()

    def toggle_theme(self):
        self.apply_theme("light" if self.theme_name == "dark" else "dark")

    def apply_theme(self, theme_name):
        if theme_name == self.theme_name:
            return

        old_theme = dict(THEME)
        new_theme = THEMES[theme_name]
        color_map = {
            old_theme[key]: new_theme[key]
            for key in old_theme
            if key in new_theme
        }
        THEME.clear()
        THEME.update(new_theme)
        self.theme_name = theme_name
        self.bg_color = THEME["bg"]
        self.accent_color = THEME["ch_pleth"]

        self._serial_state = (
            self._serial_state[0],
            color_map.get(self._serial_state[1], self._serial_state[1]),
        )
        self._mqtt_state = (
            self._mqtt_state[0],
            color_map.get(self._mqtt_state[1], self._mqtt_state[1]),
        )
        self._recolor_widget(self.root, color_map)
        self._build_style()
        self.fig.set_facecolor(THEME["panel"])
        self.style_axes(self.ax)
        self.mfcc_strip.redraw()
        self.render_mfcc_details()
        self._render_lamps()
        self.theme_button.set_text(self.t(f"theme_{self.theme_name}"))
        try:
            self.canvas.draw_idle()
        except tk.TclError:
            pass

    def _recolor_widget(self, widget, color_map):
        if isinstance(widget, FlatButton):
            widget.apply_palette(color_map)

        for option in (
            "background",
            "foreground",
            "activebackground",
            "activeforeground",
            "highlightbackground",
            "highlightcolor",
            "insertbackground",
            "selectbackground",
            "selectforeground",
            "troughcolor",
        ):
            try:
                current = widget.cget(option)
                replacement = color_map.get(current)
                if replacement:
                    widget.configure(**{option: replacement})
            except (tk.TclError, TypeError):
                pass

        if isinstance(widget, tk.Canvas):
            for item in widget.find_all():
                for option in ("fill", "outline"):
                    try:
                        current = widget.itemcget(item, option)
                        replacement = color_map.get(current)
                        if replacement:
                            widget.itemconfigure(item, **{option: replacement})
                    except tk.TclError:
                        pass

        if isinstance(widget, MetricTile):
            widget.accent = color_map.get(widget.accent, widget.accent)

        for child in widget.winfo_children():
            self._recolor_widget(child, color_map)

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Dark.TCombobox",
            fieldbackground=THEME["input"],
            background=THEME["raised"],
            foreground=THEME["text"],
            bordercolor=THEME["line"],
            lightcolor=THEME["line"],
            darkcolor=THEME["line"],
            arrowcolor=THEME["text_dim"],
            padding=(6, 4),
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", THEME["input"])],
            foreground=[("readonly", THEME["text"])],
        )
        self.root.option_add("*TCombobox*Listbox.background", THEME["raised"])
        self.root.option_add("*TCombobox*Listbox.foreground", THEME["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", THEME["ch_pleth"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", THEME["bg"])

        style.configure("Dark.Horizontal.TSeparator", background=THEME["line"])

    def _build_header(self):
        header = tk.Frame(self.root, bg=self.bg_color)
        header.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(10, 6))

        tk.Frame(header, bg=THEME["ch_pleth"], width=4, height=20).pack(side=tk.LEFT)
        title_label = tk.Label(
            header, text="PPG MONITOR", bg=self.bg_color, fg=THEME["text"],
            font=(self.font_h2[0], 12, "bold"),
        )
        title_label.pack(side=tk.LEFT, padx=(9, 14))

        self.device_label = tk.Label(
            header, text="—", bg=self.bg_color, fg=THEME["text_dim"], font=self.font_mono,
        )
        self.device_label.pack(side=tk.LEFT)

        self.mqtt_lamp = StatusLamp(header, "MQTT", self.font_key, self.font_small, self.bg_color)
        self.mqtt_lamp.pack(side=tk.RIGHT, padx=(14, 0))

        self.serial_lamp = StatusLamp(header, "SERIAL", self.font_key, self.font_small, self.bg_color)
        self.serial_lamp.pack(side=tk.RIGHT)

        self.theme_button = FlatButton(
            header, self.t("theme_dark"), self.toggle_theme, fill=THEME["raised"],
            fg=THEME["text"], font=self.font_small, width=100, height=28,
            surface=self.bg_color,
        )
        self.theme_button.pack(side=tk.RIGHT, padx=(0, 8))

        self.language_button = FlatButton(
            header, "EN", self.toggle_language, fill=THEME["raised"],
            fg=THEME["text"], font=self.font_small, width=42, height=28,
            surface=self.bg_color,
        )
        self.language_button.pack(side=tk.RIGHT, padx=(0, 6))

        self._render_lamps()

        tk.Frame(self.root, bg=THEME["line"], height=1).pack(side=tk.TOP, fill=tk.X)

    def _build_footer(self):
        footer = tk.Frame(self.root, bg=self.bg_color)
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(4, 10))

        # Baris kendali koneksi.
        control = tk.Frame(footer, bg=self.bg_color)
        control.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        port_label = tk.Label(
            control, text="PORT", bg=self.bg_color, fg=THEME["text_faint"],
            font=self.font_key,
        )
        port_label.pack(side=tk.LEFT, padx=(0, 6))

        self.port_combo = ttk.Combobox(
            control, width=14, state="readonly", style="Dark.TCombobox", font=self.font_mono,
        )
        self.port_combo.pack(side=tk.LEFT, padx=(0, 8))

        self.refresh_button = FlatButton(
            control, self.t("refresh"), self.refresh_ports, fill=THEME["raised"],
            fg=THEME["text"], font=self.btn_font, width=82, surface=self.bg_color,
        )
        self._bind_text(self.refresh_button, "refresh")
        self.refresh_button.pack(side=tk.LEFT, padx=(0, 6))

        self.start_button = FlatButton(
            control, self.t("start"), self.start_serial, fill=THEME["ch_hrv"],
            fg=THEME["bg"], font=self.btn_font, width=82, surface=self.bg_color,
        )
        self._bind_text(self.start_button, "start")
        self.start_button.pack(side=tk.LEFT, padx=(0, 6))

        self.stop_button = FlatButton(
            control, self.t("stop"), self.stop_serial, fill=THEME["rec"],
            fg=THEME["bg"], font=self.btn_font, width=82, surface=self.bg_color,
        )
        self._bind_text(self.stop_button, "stop")
        self.stop_button.pack(side=tk.LEFT)

        self.hint_label = tk.Label(
            control, text="", bg=self.bg_color, fg=THEME["text_faint"], font=self.font_small,
        )
        self.hint_label.pack(side=tk.LEFT, padx=12)

        self.settings_button = FlatButton(
            control, self.t("settings"), self.open_settings, fill=THEME["raised"],
            fg=THEME["text"], font=self.btn_font, width=86, surface=self.bg_color,
        )
        self._bind_text(self.settings_button, "settings")
        self.settings_button.pack(side=tk.RIGHT)

        # Baris input pasien.
        info = tk.Frame(footer, bg=self.bg_color)
        info.pack(side=tk.TOP, fill=tk.X)

        def add_entry(caption_key, width):
            wrap = tk.Frame(info, bg=self.bg_color)
            wrap.pack(side=tk.LEFT, padx=(0, 10))
            caption = tk.Label(
                wrap, text=self.t(caption_key), bg=self.bg_color, fg=THEME["text_faint"],
                font=self.font_key, anchor="w",
            )
            self._bind_text(caption, caption_key)
            caption.pack(fill=tk.X)
            entry = tk.Entry(
                wrap, width=width, font=self.font_mono, bd=0, relief="flat",
                bg=THEME["input"], fg=THEME["text"], insertbackground=THEME["ch_pleth"],
                highlightthickness=1, highlightbackground=THEME["line"],
                highlightcolor=THEME["ch_pleth"], justify="left",
            )
            entry.pack(ipady=6)
            entry.bind("<FocusIn>", lambda _event, target=entry: setattr(self, "active_entry", target))
            return entry

        self.patient_name_entry = add_entry("patient_name", 16)
        self.age_entry = add_entry("age", 5)
        self.height_entry = add_entry("height", 7)
        self.weight_entry = add_entry("weight", 7)
        self.active_entry = self.age_entry

        actions = tk.Frame(info, bg=self.bg_color)
        actions.pack(side=tk.LEFT, padx=(2, 0), pady=(13, 0))

        self.numpad_button = FlatButton(
            actions, self.t("numpad"), self.open_numpad, fill=THEME["raised"],
            fg=THEME["text"], font=self.btn_font, width=82, surface=self.bg_color,
        )
        self._bind_text(self.numpad_button, "numpad")
        self.numpad_button.pack(side=tk.LEFT, padx=(0, 6))

        self.submit_button = FlatButton(
            actions, self.t("submit"), self.submit_height, fill=THEME["ch_pleth"],
            fg=THEME["bg"], font=self.btn_font, width=90, surface=self.bg_color,
        )
        self._bind_text(self.submit_button, "submit")
        self.submit_button.pack(side=tk.LEFT)

    def _build_body(self):
        body = tk.Frame(self.root, bg=self.bg_color)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=8)

        # Urutan pack menentukan pembagian ruang: widget berukuran tetap harus
        # di-pack lebih dulu, baru widget expand=True mengisi sisanya. Kalau
        # dibalik, rail dan strip MFCC hanya kebagian 1x1 piksel.
        left = tk.Frame(body, bg=self.bg_color)
        rail = tk.Frame(body, bg=self.bg_color, width=196)
        rail.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        rail.pack_propagate(False)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ----- Kolom kiri: waveform + MFCC -----
        trace_panel = tk.Frame(
            left, bg=THEME["panel"], highlightthickness=1,
            highlightbackground=THEME["line"], highlightcolor=THEME["line"],
        )
        mfcc_panel = tk.Frame(
            left, bg=THEME["panel"], highlightthickness=1,
            highlightbackground=THEME["line"], highlightcolor=THEME["line"],
        )
        mfcc_panel.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        trace_panel.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        trace_head = tk.Frame(trace_panel, bg=THEME["panel"])
        trace_head.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(9, 0))

        titles = tk.Frame(trace_head, bg=THEME["panel"])
        titles.pack(side=tk.LEFT)
        trace_eyebrow = tk.Label(
            titles, text="PLETH · RAW ADC", bg=THEME["panel"], fg=THEME["text_faint"],
            font=self.font_key, anchor="w",
        )
        trace_eyebrow.pack(fill=tk.X)
        waveform_label = tk.Label(
            titles, text=self.t("waveform"), bg=THEME["panel"], fg=THEME["text"],
            font=self.font_h2, anchor="w",
        )
        self._bind_text(waveform_label, "waveform")
        waveform_label.pack(fill=tk.X)

        self.trace_meta = tk.Label(
            trace_head, text="0 sampel", bg=THEME["panel"], fg=THEME["text_faint"],
            font=self.font_mono,
        )
        self.trace_meta.pack(side=tk.RIGHT, pady=(0, 2))

        self.fig = plt.Figure(figsize=(7, 2.6), dpi=100, facecolor=THEME["panel"])
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.05, right=0.99, top=0.97, bottom=0.10)
        self.style_axes(self.ax)

        self.canvas = FigureCanvasTkAgg(self.fig, master=trace_panel)
        self.canvas.get_tk_widget().configure(bg=THEME["panel"], highlightthickness=0, bd=0)
        self.canvas.get_tk_widget().pack(
            side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(4, 10)
        )

        mfcc_head = tk.Frame(mfcc_panel, bg=THEME["panel"])
        mfcc_head.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(7, 0))
        tk.Label(
            mfcc_head, text="MFCC", bg=THEME["panel"], fg=THEME["text_faint"],
            font=self.font_key,
        ).pack(side=tk.LEFT)
        self.mfcc_meta = tk.Label(
            mfcc_head, text=self.t("mfcc_waiting"), bg=THEME["panel"],
            fg=THEME["text_faint"],
            font=self.font_mono,
        )
        self.mfcc_detail_button = FlatButton(
            mfcc_head, self.t("mfcc_detail"), self.open_mfcc_details,
            fill=THEME["raised"], fg=THEME["text"], font=self.font_small,
            width=70, height=26, surface=THEME["panel"],
        )
        self._bind_text(self.mfcc_detail_button, "mfcc_detail")
        self.mfcc_detail_button.pack(side=tk.RIGHT)
        self.mfcc_meta.pack(side=tk.RIGHT, padx=(0, 10))

        self.mfcc_strip = MfccStrip(mfcc_panel, height=54)
        self.mfcc_strip.set_font(self.font_small)
        self.mfcc_strip.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(2, 9))

        # ----- Kolom kanan: rail metrik -----
        def add_tile(caption, unit, accent, caption_key=None, unit_key=None):
            tile = MetricTile(
                rail, caption, unit, accent,
                self.font_key, self.font_value, self.font_unit,
            )
            if caption_key:
                self._bind_text(tile.caption_label, caption_key)
            if unit_key and tile.unit_label:
                self._bind_text(tile.unit_label, unit_key)
            tile.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 5))
            return tile

        self.tile_si = add_tile("SI", "m/s", THEME["ch_si"])
        self.tile_hrv = add_tile("HRV", "ms", THEME["ch_hrv"])
        self.tile_bmi = add_tile("BMI", "kg/m²", THEME["ch_bmi"])
        self.tile_age = add_tile(
            self.t("age"), self.t("age_unit"), THEME["ch_age"], "age", "age_unit"
        )
        self.tile_volt = add_tile(
            self.t("voltage"), "V", THEME["ch_volt"], "voltage"
        )
        self.tile_adc = add_tile("ADC", "", THEME["ch_adc"])

    def style_axes(self, ax):
        """Gaya sumbu matplotlib; dipanggil ulang setiap frame setelah clear()."""
        ax.set_facecolor(THEME["plot_bg"])
        ax.grid(True, color=THEME["ch_pleth"], alpha=0.07, linewidth=0.7)
        ax.tick_params(axis="both", which="major", labelsize=6,
                       colors=THEME["text_faint"], length=2)
        for spine in ax.spines.values():
            spine.set_color(THEME["line_soft"])
            spine.set_linewidth(0.8)

    def update_trace_meta(self, sample_count, peak_count):
        self.trace_sample_count = sample_count
        self.trace_peak_count = peak_count
        try:
            self.trace_meta.config(
                text=self.t("samples", samples=sample_count, peaks=peak_count)
            )
        except tk.TclError:
            pass

    def show_hint(self, message):
        try:
            self.hint_label.config(text=message)
        except tk.TclError:
            return
        if self._hint_after_id is not None:
            try:
                self.root.after_cancel(self._hint_after_id)
            except tk.TclError:
                pass
        try:
            self._hint_after_id = self.root.after(
                4000, lambda: self.hint_label.config(text="")
            )
        except tk.TclError:
            self._hint_after_id = None

    def _render_lamps(self):
        serial_status, serial_color = self._serial_state
        mqtt_status, mqtt_color = self._mqtt_state
        self.serial_lamp.set(self.t(f"status_{serial_status}"), serial_color)
        self.mqtt_lamp.set(self.t(f"status_{mqtt_status}"), mqtt_color)

    def disable_submit_button(self):
        try:
            self.submit_button.set_enabled(False)
        except tk.TclError:
            pass

    def enable_submit_button(self):
        try:
            self.submit_button.set_enabled(True)
        except tk.TclError:
            pass

    def _is_window_valid(self, window):
        try:
            if window is None:
                return False
            return window.winfo_exists()
        except tk.TclError:
            return False

    def _create_popup(self, title, width=None, height=None, title_key=None):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.configure(bg=THEME["bg"])
        if title_key:
            self._bind_window_title(popup, title_key)

        popup.attributes("-topmost", True)

        if width and height:
            x = (self.root.winfo_screenwidth() // 2) - (width // 2)
            y = (self.root.winfo_screenheight() // 2) - (height // 2)
            popup.geometry(f"{width}x{height}+{x}+{y}")

        popup.resizable(True, True)
        popup.focus_force()
        popup.lift()

        return popup

    def open_mfcc_details(self):
        if self._is_window_valid(self.mfcc_detail_window):
            self.mfcc_detail_window.lift()
            self.mfcc_detail_window.focus_force()
            return

        self.mfcc_detail_window = self._create_popup(
            self.t("mfcc_detail_title"),
            360,
            430,
            title_key="mfcc_detail_title",
        )

        def on_close():
            try:
                if self.mfcc_detail_window:
                    self.mfcc_detail_window.destroy()
            except tk.TclError:
                pass
            self.mfcc_detail_window = None
            self.mfcc_detail_text = None

        self.mfcc_detail_window.protocol("WM_DELETE_WINDOW", on_close)
        frame = tk.Frame(self.mfcc_detail_window, bg=THEME["bg"])
        frame.pack(expand=True, fill=tk.BOTH, padx=18, pady=16)

        title = tk.Label(
            frame,
            text=self.t("mfcc_detail_title"),
            bg=THEME["bg"],
            fg=THEME["text"],
            font=self.font_h2,
            anchor="w",
        )
        self._bind_text(title, "mfcc_detail_title")
        title.pack(fill=tk.X, pady=(0, 10))

        self.mfcc_detail_text = tk.Text(
            frame,
            height=15,
            width=28,
            wrap="none",
            state="disabled",
            bd=0,
            relief="flat",
            bg=THEME["panel"],
            fg=THEME["text"],
            selectbackground=THEME["ch_pleth"],
            selectforeground=THEME["bg"],
            highlightthickness=1,
            highlightbackground=THEME["line"],
            font=self.font_mono,
            padx=14,
            pady=12,
        )
        self.mfcc_detail_text.pack(expand=True, fill=tk.BOTH)
        self.render_mfcc_details()

    def render_mfcc_details(self):
        if self.mfcc_detail_text is None:
            return
        try:
            if not self.mfcc_detail_text.winfo_exists():
                return
            lines = mfcc_detail_lines(self.latest_mfcc)
            content = "\n".join(lines) if lines else self.t("mfcc_detail_empty")
            self.mfcc_detail_text.config(state="normal")
            self.mfcc_detail_text.delete("1.0", tk.END)
            self.mfcc_detail_text.insert("1.0", content)
            self.mfcc_detail_text.config(state="disabled")
        except tk.TclError:
            pass

    # ==================== SERIAL ====================

    def create_mqtt_flow(self):
        mqtt_flow = PpgMqttFlow.from_config(
            load_config(MQTT_CONFIG),
            status_callback=None,
        )
        mqtt_flow.status_callback = lambda status: self.on_mqtt_status(
            status,
            mqtt_flow,
        )
        return mqtt_flow

    def on_mqtt_status(self, status, mqtt_flow=None):
        colors = {
            "connected": THEME["ok"],
            "connecting": THEME["warn"],
            "reconnecting": THEME["warn"],
            "rejected": THEME["rec"],
            "error": THEME["rec"],
            "disconnected": THEME["text_faint"],
        }

        def update():
            if mqtt_flow is not None and self.mqtt is not mqtt_flow:
                return
            self._mqtt_state = (status, colors.get(status, THEME["text_dim"]))
            if status == "connected" and self.mqtt_connect_after_id is not None:
                try:
                    self.root.after_cancel(self.mqtt_connect_after_id)
                except tk.TclError:
                    pass
                self.mqtt_connect_after_id = None
            self._render_lamps()

        try:
            self.root.after(0, update)
        except tk.TclError:
            pass

    def set_serial_state(self, text, color):
        self._serial_state = (text, color)
        try:
            self._render_lamps()
        except tk.TclError:
            pass

    @staticmethod
    def metric_number(value):
        if value is None or isinstance(value, str):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    def schedule_metrics_publish(self):
        try:
            self.metrics_after_id = self.root.after(
                self.mqtt.metrics_interval_ms,
                self.publish_metrics_tick,
            )
        except tk.TclError:
            self.metrics_after_id = None

    def publish_metrics_tick(self):
        self.metrics_after_id = None
        try:
            if self.running:
                recording = self.mqtt.measurement_id is not None
                self.mqtt.publish_metrics(
                    si_m_s=self.latest_si if recording else None,
                    hrv_ms=self.latest_hrv,
                    bmi=self.latest_bmi if recording else None,
                    age_years=self.latest_age if recording else None,
                    mfcc=self.latest_mfcc,
                    voltage_v=self.latest_voltage,
                    adc=self.latest_adc,
                )
        except Exception as error:
            print("MQTT metrics error:", error)
        finally:
            self.schedule_metrics_publish()

    def refresh_ports(self):
        ports = list_ports.comports()
        port_names = [p.device for p in ports]
        self.port_combo["values"] = port_names
        if port_names:
            self.port_combo.current(0)
        else:
            self.port_combo.set("")
        self.show_hint(
            self.t("ports_found", count=len(port_names))
            if port_names
            else self.t("no_serial_port")
        )

    def start_serial(self):
        if self.running:
            return
        if self.mqtt_cleanup_thread is not None:
            self.start_after_stop = True
            return

        port_name = self.port_combo.get()
        if not port_name:
            messagebox.showwarning(
                self.t("no_port_title"),
                self.t("no_port_message"),
            )
            return

        try:
            mqtt_flow = self.create_mqtt_flow()
            serial_connection = serial.Serial(port_name, SERIAL_BAUD, timeout=0.1)
            self.mqtt = mqtt_flow
            self.ser = serial_connection
            self.running = True
            self.mqtt.connect()
            self.serial_thread = threading.Thread(
                target=self.serial_reader,
                args=(serial_connection,),
                daemon=True,
            )
            self.serial_thread.start()
            self.mqtt_connect_after_id = self.root.after(
                10000,
                self.mqtt_connection_timeout,
            )
            self.set_serial_state("connected", THEME["ok"])
        except serial.SerialException as e:
            messagebox.showerror(
                self.t("serial_error_title"),
                self.t("serial_error", port=port_name, error=e),
            )
            self.set_serial_state("error", THEME["rec"])
            self.running = False
            self.ser = None
        except Exception as error:
            self.stop_serial()
            messagebox.showerror(
                self.t("mqtt_error_title"),
                self.t("mqtt_start_error", error=error),
            )
            self.set_serial_state("error", THEME["rec"])

    def mqtt_connection_timeout(self):
        self.mqtt_connect_after_id = None
        if not self.running or self.mqtt.connected:
            return
        self.stop_serial()
        messagebox.showerror(
            self.t("mqtt_timeout_title"),
            self.t("mqtt_timeout_message", config=MQTT_CONFIG),
        )

    def stop_serial(self):
        self.running = False
        self.start_after_stop = False
        if self.mqtt_connect_after_id is not None:
            try:
                self.root.after_cancel(self.mqtt_connect_after_id)
            except tk.TclError:
                pass
            self.mqtt_connect_after_id = None

        if self.countdown_after_id is not None:
            try:
                self.root.after_cancel(self.countdown_after_id)
            except tk.TclError:
                pass
            self.countdown_after_id = None
        self.logging_active = False
        self.measurement_in_progress = False
        self.enable_submit_button()
        if self._is_window_valid(self.averages_window):
            try:
                self.averages_window.destroy()
            except tk.TclError:
                pass
        self.averages_window = None
        self.countdown_label = None
        self.countdown_bar = None
        self.avg_si_label = None
        self.avg_hrv_label = None
        self.avg_mfcc_label = None
        self.avg_vol_label = None
        self.avg_adc_label = None

        serial_connection = self.ser
        self.ser = None
        try:
            if serial_connection:
                cancel_read = getattr(serial_connection, "cancel_read", None)
                if callable(cancel_read):
                    cancel_read()
                if serial_connection.is_open:
                    serial_connection.close()
        except Exception:
            pass

        serial_thread = self.serial_thread
        self.serial_thread = None

        self.set_serial_state("off", THEME["text_faint"])
        if self.mqtt_cleanup_thread is None:
            mqtt_flow = self.mqtt
            self.mqtt_cleanup_thread = threading.Thread(
                target=self.cleanup_stopped_session,
                args=(serial_thread, mqtt_flow),
                daemon=True,
            )
            self.mqtt_cleanup_thread.start()

    def cleanup_stopped_session(self, serial_thread, mqtt_flow):
        if serial_thread and serial_thread is not threading.current_thread():
            serial_thread.join(timeout=2)
        try:
            mqtt_flow.disconnect()
        except Exception as error:
            print("MQTT stop error:", error)
        try:
            self.root.after(0, self.finish_stopped_session)
        except (tk.TclError, RuntimeError):
            pass

    def finish_stopped_session(self):
        self.mqtt_cleanup_thread = None
        self.set_serial_state("off", THEME["text_faint"])
        if self.start_after_stop:
            self.start_after_stop = False
            self.start_serial()

    def serial_reader(self, serial_connection):
        while (
            self.running
            and self.ser is serial_connection
            and serial_connection.is_open
        ):
            try:
                line = serial_connection.readline().decode("ascii").strip()
                if not self.running or self.ser is not serial_connection:
                    break
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
            except serial.SerialException as e:
                if self.running and self.ser is serial_connection:
                    print("Serial error:", e)
                break
            except Exception as e:
                print("Unexpected error:", e)
                break

        # Thread lama tidak boleh membersihkan sesi baru yang sudah memakai
        # objek serial berbeda setelah Stop -> Start.
        if self.ser is not serial_connection:
            return

        self.running = False
        self.ser = None
        if self.serial_thread is threading.current_thread():
            self.serial_thread = None
        try:
            if serial_connection.is_open:
                serial_connection.close()
        except Exception:
            pass
        if self.mqtt_cleanup_thread is None:
            self.mqtt_cleanup_thread = threading.current_thread()
            self.cleanup_stopped_session(None, self.mqtt)

    # ==================== NUMPAD ====================

    def open_numpad(self):
        if self._is_window_valid(self.numpad_window):
            self.numpad_window.lift()
            self.numpad_window.focus_force()
            return

        self.numpad_window = self._create_popup(
            self.t("numpad"),
            250,
            330,
            title_key="numpad",
        )

        def on_numpad_close():
            try:
                if self.numpad_window:
                    self.numpad_window.destroy()
            except Exception:
                pass
            self.numpad_window = None

        self.numpad_window.protocol("WM_DELETE_WINDOW", on_numpad_close)

        btn_frame = tk.Frame(self.numpad_window, bg=THEME["bg"])
        btn_frame.pack(expand=True, fill=tk.BOTH, padx=12, pady=12)

        buttons = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            (".", 3, 0), ("0", 3, 1), ("C", 3, 2),
            ("Del", 4, 0), ("OK", 4, 1),
        ]

        key_font = (self.btn_font[0], 13, "bold")

        for (text, r, c) in buttons:
            colspan = 2 if text == "OK" else 1
            fill = THEME["raised"]
            fg = THEME["text"]
            if text == "OK":
                fill = THEME["ch_hrv"]
                fg = THEME["bg"]
            elif text == "C":
                fill = THEME["warn"]
                fg = THEME["bg"]
            elif text == "Del":
                fill = THEME["raised"]
                fg = THEME["warn"]

            button = FlatButton(
                btn_frame, text, lambda t=text: self.numpad_press(t),
                fill=fill, fg=fg, font=key_font,
                width=136 if colspan == 2 else 64, height=48,
                surface=THEME["bg"],
            )
            button.grid(row=r, column=c, columnspan=colspan, padx=4, pady=4, sticky="nsew")

        for i in range(3):
            btn_frame.columnconfigure(i, weight=1)
        for i in range(5):
            btn_frame.rowconfigure(i, weight=1)

    def numpad_press(self, char):
        target = self.active_entry if self.active_entry is not None else self.height_entry

        if char in "0123456789.":
            target.insert(tk.END, char)
        elif char == "C":
            target.delete(0, tk.END)
        elif char == "Del":
            current = target.get()
            target.delete(0, tk.END)
            target.insert(0, current[:-1])
        elif char == "OK":
            if self._is_window_valid(self.numpad_window):
                self.numpad_window.destroy()
                self.numpad_window = None

    # ==================== SETTINGS ====================

    def open_settings(self):
        if self._is_window_valid(self.settings_window):
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        self.settings_window = self._create_popup(
            self.t("settings_title"),
            360,
            320,
            title_key="settings_title",
        )

        def on_settings_close():
            try:
                if self.settings_window:
                    self.settings_window.destroy()
            except Exception:
                pass
            self.settings_window = None

        self.settings_window.protocol("WM_DELETE_WINDOW", on_settings_close)

        params = self.realTimePlot.mfcc_params

        main_frame = tk.Frame(self.settings_window, bg=THEME["bg"])
        main_frame.pack(expand=True, fill=tk.BOTH, padx=16, pady=14)

        parameter_label = tk.Label(
            main_frame, text=self.t("mfcc_parameters"), bg=THEME["bg"],
            fg=THEME["text_faint"],
            font=self.font_key,
        )
        self._bind_text(parameter_label, "mfcc_parameters")
        parameter_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        def add_row(row, caption, value, caption_key=None):
            label = tk.Label(
                main_frame,
                text=self.t(caption_key) if caption_key else caption,
                bg=THEME["bg"],
                fg=THEME["text_dim"],
                font=self.font_small,
            )
            if caption_key:
                self._bind_text(label, caption_key)
            label.grid(row=row, column=0, padx=(0, 10), pady=5, sticky="w")
            entry = tk.Entry(
                main_frame, font=self.font_mono, width=12, bd=0, relief="flat",
                bg=THEME["input"], fg=THEME["text"], insertbackground=THEME["ch_pleth"],
                highlightthickness=1, highlightbackground=THEME["line"],
                highlightcolor=THEME["ch_pleth"],
            )
            entry.grid(row=row, column=1, pady=5, sticky="ew", ipady=5)
            entry.insert(0, str(value))
            return entry

        sr_entry = add_row(
            1, self.t("sample_rate"), params["sr"], caption_key="sample_rate"
        )
        frame_entry = add_row(
            2,
            self.t("frame_length"),
            params["frame_ms"],
            caption_key="frame_length",
        )
        hop_entry = add_row(
            3,
            self.t("hop_length"),
            params["hop_ms"],
            caption_key="hop_length",
        )
        n_mfcc_entry = add_row(
            4,
            self.t("mfcc_count"),
            params["n_mfcc"],
            caption_key="mfcc_count",
        )

        window_label = tk.Label(
            main_frame, text=self.t("window"), bg=THEME["bg"],
            fg=THEME["text_dim"], font=self.font_small,
        )
        self._bind_text(window_label, "window")
        window_label.grid(row=5, column=0, padx=(0, 10), pady=5, sticky="w")
        window_var = tk.StringVar(value=params["window"])
        ttk.Combobox(
            main_frame, textvariable=window_var, style="Dark.TCombobox",
            values=["hann", "hamming", "blackman", "boxcar"], state="readonly", width=11,
        ).grid(row=5, column=1, pady=5, sticky="ew")

        mode_label = tk.Label(
            main_frame, text=self.t("mfcc_mode"), bg=THEME["bg"],
            fg=THEME["text_dim"], font=self.font_small,
        )
        self._bind_text(mode_label, "mfcc_mode")
        mode_label.grid(row=6, column=0, padx=(0, 10), pady=5, sticky="w")
        mode_var = tk.StringVar(value=self.realTimePlot.mfcc_mode)
        ttk.Combobox(
            main_frame, textvariable=mode_var, style="Dark.TCombobox",
            values=["standard", "peak"], state="readonly", width=11,
        ).grid(row=6, column=1, pady=5, sticky="ew")

        main_frame.columnconfigure(1, weight=1)

        def on_save():
            try:
                sr = int(clean_number_input(sr_entry.get()))
                frame_ms = float(clean_number_input(frame_entry.get()))
                hop_ms = float(clean_number_input(hop_entry.get()))
                n_mfcc = int(clean_number_input(n_mfcc_entry.get()))
                window = window_var.get()
                mode = mode_var.get()

                if sr <= 0 or frame_ms <= 0 or hop_ms <= 0 or n_mfcc <= 0:
                    raise ValueError

                self.realTimePlot.set_mfcc_params(sr, frame_ms, hop_ms, n_mfcc, window)
                self.realTimePlot.set_mfcc_mode(mode)
                on_settings_close()
            except ValueError:
                messagebox.showerror(
                    self.t("invalid_input_title"),
                    self.t("invalid_settings"),
                )

        btn_frame = tk.Frame(main_frame, bg=THEME["bg"])
        btn_frame.grid(row=7, column=0, columnspan=2, pady=(16, 0), sticky="e")

        cancel_button = FlatButton(
            btn_frame, self.t("cancel"), on_settings_close, fill=THEME["raised"],
            fg=THEME["text"], font=self.btn_font, width=84, surface=THEME["bg"],
        )
        self._bind_text(cancel_button, "cancel")
        cancel_button.pack(side=tk.LEFT, padx=(0, 8))

        save_button = FlatButton(
            btn_frame, self.t("save"), on_save, fill=THEME["ch_pleth"],
            fg=THEME["bg"], font=self.btn_font, width=90, surface=THEME["bg"],
        )
        self._bind_text(save_button, "save")
        save_button.pack(side=tk.LEFT)

    # ==================== MEASUREMENT 300s ====================

    def start_logging(self):
        self.logging_active = True
        self.logging_start_time = time.time()
        self.realTimePlot.reset_accumulators()

    def finish_logging(self):
        if not self.logging_active:
            return

        avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc = self.realTimePlot.compute_overall_means()
        self.mqtt.complete_measurement(
            si_mean=avg_si,
            hrv_mean=avg_hrv,
            mfcc_mean=avg_mfcc,
            voltage_mean=avg_vol,
            adc_mean=avg_adc,
        )

        self.logging_active = False
        self.measurement_in_progress = False
        self.enable_submit_button()

        if not np.isnan(avg_si):
            self.update_si_label(avg_si)
        if not np.isnan(avg_hrv):
            self.update_hrv_label(avg_hrv)
        if not np.isnan(avg_vol):
            self.update_vol_label(avg_vol)
        if avg_mfcc is not None:
            self.update_mfcc_label(avg_mfcc)

        self.update_averages_window(avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc)
        self.save_average_csv(avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc)

    def format_float(self, value):
        if value is None:
            return ""
        if isinstance(value, float):
            if np.isnan(value):
                return ""
            return f"{value:.6f}"
        return str(value)

    def save_average_csv(self, avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc):
        now = datetime.now().strftime("%Y%m%d_%H%M%S")

        patient_name = self.last_patient_name.strip()
        prefix = re.sub(r"\s+", "_", patient_name)
        prefix = "".join(c for c in prefix if c.isalnum() or c in ("_", "-"))

        if prefix:
            filename = f"{prefix}_{now}.csv"
        else:
            filename = f"hrm_avg_{now}.csv"

        header = [
            "Timestamp",
            "Patient_Name",
            "Age_yr",
            "Height_cm",
            "Weight_kg",
            "BMI",
            "SI_mean",
            "HRV_mean",
            "Voltage_mean",
            "ADC_mean"
        ]
        for i in range(13):
            header.append(f"MFCC{i+1}_mean")

        if avg_mfcc is None or not isinstance(avg_mfcc, (list, np.ndarray)) or len(avg_mfcc) != 13:
            mfcc_list = [""] * 13
        else:
            mfcc_list = [self.format_float(float(x)) for x in avg_mfcc]

        row = [
            datetime.now().isoformat(timespec="seconds"),
            patient_name if patient_name else "N/A",
            str(self.last_age) if self.last_age is not None else "-1",
            self.format_float(self.last_height) if self.last_height is not None else "",
            self.format_float(self.last_weight) if self.last_weight is not None else "",
            self.format_float(self.last_bmi) if self.last_bmi is not None else "",
            self.format_float(avg_si) if not np.isnan(avg_si) else "",
            self.format_float(avg_hrv) if not np.isnan(avg_hrv) else "",
            self.format_float(avg_vol) if not np.isnan(avg_vol) else "",
            str(int(round(avg_adc))) if not np.isnan(avg_adc) else "",
        ]
        row.extend(mfcc_list)

        try:
            with open(filename, mode="w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerow(row)
            print(f"CSV saved:  {filename}")
            self.show_hint(self.t("csv_saved", filename=filename))
        except Exception as e:
            messagebox.showerror(self.t("csv_error_title"), str(e))

    # ==================== SUBMIT ====================

    def submit_height(self):
        if self.measurement_in_progress:
            messagebox.showwarning(
                self.t("measurement_active_title"),
                self.t("measurement_active"),
            )
            return

        try:
            patient_name = self.patient_name_entry.get().strip()
            age_str = clean_number_input(self.age_entry.get())
            height_str = clean_number_input(self.height_entry.get())
            weight_str = clean_number_input(self.weight_entry.get())

            if not patient_name or not age_str or not height_str or not weight_str:
                raise ValueError("Empty input")

            age_yr = float(age_str)
            height_cm = float(height_str)
            weight_kg = float(weight_str)

            if age_yr <= 0 or height_cm <= 0 or weight_kg <= 0:
                raise ValueError("Negative or zero value")

            self.last_age = int(round(age_yr))
            self.last_height = height_cm
            self.last_weight = weight_kg
            self.last_patient_name = patient_name

            height_m = height_cm / 100.0
            self.last_bmi = weight_kg / (height_m ** 2)

            self.mqtt.begin_measurement(
                # Nama parameter MQTT dipertahankan untuk kompatibilitas storage lama.
                patient_code=self.last_patient_name,
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
            messagebox.showerror(self.t("mqtt_error_title"), str(error))
        except ValueError:
            messagebox.showerror(
                self.t("invalid_input_title"),
                self.t("invalid_measurement"),
            )

    # ==================== COUNTDOWN WINDOW ====================

    def start_countdown(self):
        if self.countdown_after_id is not None:
            try:
                self.root.after_cancel(self.countdown_after_id)
            except Exception:
                pass
            self.countdown_after_id = None

        self.countdown_value = 300

        if self._is_window_valid(self.averages_window):
            try:
                if self.countdown_label:
                    self.countdown_label.config(text="300", fg=THEME["rec"])
                for label, caption in (
                    (self.avg_si_label, "SI"),
                    (self.avg_hrv_label, "HRV"),
                    (self.avg_vol_label, "VOLTASE"),
                    (self.avg_adc_label, "ADC"),
                    (self.avg_mfcc_label, "MFCC"),
                ):
                    if label:
                        label.config(text=self.t("measuring"))
                self.averages_window.lift()
            except tk.TclError:
                self.averages_window = None

        if not self._is_window_valid(self.averages_window):
            self.averages_window = self._create_popup(
                self.t("measurement_title"),
                420,
                380,
                title_key="measurement_title",
            )

            def on_averages_close():
                if self.countdown_after_id is not None:
                    try:
                        self.root.after_cancel(self.countdown_after_id)
                    except Exception:
                        pass
                    self.countdown_after_id = None

                self.mqtt.cancel_measurement("measurement_window_closed")
                self.logging_active = False
                self.measurement_in_progress = False
                self.enable_submit_button()
                try:
                    if self.averages_window:
                        self.averages_window.destroy()
                except Exception:
                    pass
                self.averages_window = None
                self.countdown_label = None
                self.countdown_bar = None
                self.avg_si_label = None
                self.avg_hrv_label = None
                self.avg_mfcc_label = None
                self.avg_vol_label = None
                self.avg_adc_label = None

            self.averages_window.protocol("WM_DELETE_WINDOW", on_averages_close)

            main_frame = tk.Frame(self.averages_window, bg=THEME["bg"])
            main_frame.pack(expand=True, fill=tk.BOTH, padx=18, pady=16)

            recording_label = tk.Label(
                main_frame, text=self.t("recording"), bg=THEME["bg"],
                fg=THEME["rec"], font=self.font_key,
            )
            self._bind_text(recording_label, "recording")
            recording_label.pack(anchor="w")

            self.countdown_label = tk.Label(
                main_frame, text="300", font=self.font_countdown,
                bg=THEME["bg"], fg=THEME["rec"],
            )
            self.countdown_label.pack(anchor="w")

            seconds_label = tk.Label(
                main_frame, text=self.t("seconds_left"), font=self.font_small,
                bg=THEME["bg"], fg=THEME["text_faint"],
            )
            self._bind_text(seconds_label, "seconds_left")
            seconds_label.pack(anchor="w", pady=(0, 10))

            # Bar kemajuan sederhana; Tkinter tidak punya progress ringan bertema.
            self.countdown_bar = tk.Canvas(
                main_frame, height=4, bg=THEME["raised"], highlightthickness=0, bd=0,
            )
            self.countdown_bar.pack(fill=tk.X, pady=(0, 14))
            self.countdown_bar_fill = self.countdown_bar.create_rectangle(
                0, 0, 0, 4, fill=THEME["rec"], outline="",
            )

            def add_avg_row(caption, accent, caption_key=None):
                row = tk.Frame(main_frame, bg=THEME["bg"])
                row.pack(fill=tk.X, pady=2)
                tk.Frame(row, bg=accent, width=3, height=16).pack(side=tk.LEFT, padx=(0, 8))
                caption_label = tk.Label(
                    row,
                    text=self.t(caption_key) if caption_key else caption,
                    bg=THEME["bg"],
                    fg=THEME["text_faint"],
                    font=self.font_key, width=9, anchor="w",
                )
                if caption_key:
                    self._bind_text(caption_label, caption_key)
                caption_label.pack(side=tk.LEFT)
                value = tk.Label(
                    row, text=self.t("measuring"), bg=THEME["bg"],
                    fg=THEME["text_dim"],
                    font=self.font_mono, anchor="w", justify="left", wraplength=280,
                )
                value.pack(side=tk.LEFT, fill=tk.X, expand=True)
                return value

            self.avg_si_label = add_avg_row("SI", THEME["ch_si"])
            self.avg_hrv_label = add_avg_row("HRV", THEME["ch_hrv"])
            self.avg_vol_label = add_avg_row(
                self.t("voltage"),
                THEME["ch_volt"],
                caption_key="voltage",
            )
            self.avg_adc_label = add_avg_row("ADC", THEME["ch_adc"])
            self.avg_mfcc_label = add_avg_row("MFCC", THEME["ch_mfcc"])

            stop_close_button = FlatButton(
                main_frame, self.t("stop_close"), on_averages_close,
                fill=THEME["rec"],
                fg=THEME["bg"], font=self.btn_font, width=130, surface=THEME["bg"],
            )
            self._bind_text(stop_close_button, "stop_close")
            stop_close_button.pack(anchor="e", pady=(16, 0))

        self.countdown_tick()

    def countdown_tick(self):
        if not self.logging_active:
            return

        if self.countdown_label and self._is_window_valid(self.averages_window):
            try:
                if self.countdown_value > 0:
                    self.countdown_label.config(text=str(self.countdown_value), fg=THEME["rec"])
                    if self.countdown_bar is not None:
                        width = self.countdown_bar.winfo_width()
                        ratio = 1.0 - (self.countdown_value / 300.0)
                        self.countdown_bar.coords(
                            self.countdown_bar_fill, 0, 0, width * ratio, 4
                        )
                    self.countdown_value -= 1
                    self.countdown_after_id = self.root.after(1000, self.countdown_tick)
                else:
                    self.countdown_label.config(
                        text=self.t("completed"),
                        fg=THEME["ok"],
                    )
                    self.countdown_after_id = None
                    self.root.after(500, self.finish_logging)
            except tk.TclError:
                pass
        else:
            self.countdown_after_id = None

    def update_averages_window(self, avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc):
        try:
            if not self._is_window_valid(self.averages_window):
                return

            if self.avg_si_label:
                text = (
                    f"{avg_si:.4f} m/s"
                    if not np.isnan(avg_si)
                    else self.t("unavailable")
                )
                self.avg_si_label.config(text=text)

            if self.avg_hrv_label:
                text = (
                    f"{avg_hrv:.2f} ms"
                    if not np.isnan(avg_hrv)
                    else self.t("unavailable")
                )
                self.avg_hrv_label.config(text=text)

            if self.avg_vol_label:
                text = (
                    f"{avg_vol:.4f} V"
                    if not np.isnan(avg_vol)
                    else self.t("unavailable")
                )
                self.avg_vol_label.config(text=text)

            if self.avg_adc_label:
                text = (
                    f"{int(round(avg_adc))}"
                    if not np.isnan(avg_adc)
                    else self.t("unavailable")
                )
                self.avg_adc_label.config(text=text)

            if self.avg_mfcc_label:
                if avg_mfcc is not None and not isinstance(avg_mfcc, str):
                    mfccs_str = ", ".join(f"{m:.2f}" for m in avg_mfcc)
                    self.avg_mfcc_label.config(text=f"[{mfccs_str}]")
                else:
                    self.avg_mfcc_label.config(text=self.t("unavailable"))
        except tk.TclError:
            pass

    # ==================== LABEL UPDATES ====================

    def update_si_label(self, si):
        self.latest_si = self.metric_number(si)
        try:
            if isinstance(si, str):
                self.tile_si.set_value("—", active=False)
            else:
                self.tile_si.set_value(f"{si:.4f}")
        except tk.TclError:
            pass

    def update_hrv_label(self, hrv):
        self.latest_hrv = self.metric_number(hrv)
        try:
            if isinstance(hrv, str):
                self.tile_hrv.set_value("—", active=False)
            else:
                self.tile_hrv.set_value(f"{hrv:.2f}")
        except tk.TclError:
            pass

    def update_bmi_label(self, bmi):
        self.latest_bmi = self.metric_number(bmi)
        try:
            if isinstance(bmi, str):
                self.tile_bmi.set_value("—", active=False)
            else:
                self.tile_bmi.set_value(f"{bmi:.2f}")
        except tk.TclError:
            pass

    def update_age_value_label(self, age):
        number = self.metric_number(age)
        self.latest_age = int(round(number)) if number is not None else None
        try:
            if isinstance(age, str):
                self.tile_age.set_value("—", active=False)
            else:
                self.tile_age.set_value(f"{int(age)}")
        except (tk.TclError, TypeError, ValueError):
            pass

    def update_vol_label(self, vol):
        self.latest_voltage = self.metric_number(vol)
        try:
            if isinstance(vol, str):
                self.tile_volt.set_value("—", active=False)
            else:
                self.tile_volt.set_value(f"{vol:.2f}")
        except tk.TclError:
            pass

    def update_adc_label(self, adc):
        number = self.metric_number(adc)
        self.latest_adc = (
            float(max(0, min(1023, round(number))))
            if number is not None
            else None
        )
        try:
            adc_val = int(round(float(adc)))
            adc_val = max(0, min(1023, adc_val))
            self.tile_adc.set_value(str(adc_val))
        except Exception:
            pass

    def update_mfcc_label(self, mfccs):
        message_keys = {
            "Beat too short": "mfcc_beat_short",
            "Waiting peaks (MFCC)": "mfcc_waiting_peaks",
            "Calculating...": "mfcc_calculating",
            "Err MFCC": "mfcc_error",
        }
        if isinstance(mfccs, str):
            self.latest_mfcc = None
        else:
            try:
                values = [float(value) for value in mfccs]
                self.latest_mfcc = (
                    values
                    if values and all(np.isfinite(value) for value in values)
                    else None
                )
            except (TypeError, ValueError):
                self.latest_mfcc = None
        try:
            if isinstance(mfccs, str):
                message_key = message_keys.get(mfccs)
                self.mfcc_strip.set_message(
                    self.t(message_key) if message_key else mfccs
                )
                self.mfcc_meta.config(text=self.t("mfcc_waiting"))
            else:
                values = [float(value) for value in mfccs]
                self.mfcc_strip.set_values(values)
                peak = max((abs(value) for value in values), default=0.0)
                self.mfcc_meta.config(
                    text=self.t(
                        "mfcc_summary",
                        count=len(values),
                        peak=peak,
                    )
                )
            self.render_mfcc_details()
        except (tk.TclError, TypeError, ValueError):
            pass

    # ==================== CLOSE ====================

    def on_close(self):
        if self.metrics_after_id is not None:
            try:
                self.root.after_cancel(self.metrics_after_id)
            except tk.TclError:
                pass
            self.metrics_after_id = None

        if self.countdown_after_id is not None:
            try:
                self.root.after_cancel(self.countdown_after_id)
            except Exception:
                pass

        self.logging_active = False
        self.measurement_in_progress = False
        self.stop_serial()

        for window in [
            self.numpad_window,
            self.settings_window,
            self.averages_window,
            self.mfcc_detail_window,
        ]:
            if self._is_window_valid(window):
                try:
                    window.destroy()
                except Exception:
                    pass

        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    root = tk.Tk()
    app = ArduinoPlotApp(root)
    app.run()
