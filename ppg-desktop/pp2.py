import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import time
import serial
import serial.tools.list_ports as list_ports
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
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


def clean_number_input(text):
    """Membersihkan input angka dari karakter tidak valid"""
    if text is None: 
        return ""
    cleaned = re.sub(r'[^\d.\-]', '', str(text).strip())
    parts = cleaned.split('.')
    if len(parts) > 2:
        cleaned = parts[0] + '.' + ''.join(parts[1:])
    return cleaned


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
        self. lock = threading.Lock()

        self.sample_period_ms = 10.0

        self.ibi_raw_list = []
        self.last_hrv_value = 0.0
        self.last_si_value = 0.0

        self.mfcc_params = {
            "sr": 100,
            "frame_ms": 200.0,
            "hop_ms": 40.0,
            "n_mfcc": 13,
            "window":  "hamming",
        }

        self.mfcc_mode = "standard"

    def reset_accumulators(self):
        with self.lock:
            self. si_accumulator = []
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
        if app. last_height is None or delta_t_s <= 0:
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
            data = data. astype(float) + 1e-6 * np.random.randn(*data.shape)

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
        y_min = -250.0
        y_max = 250.0
        ax.set_ylim([y_min, y_max])

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
        self.getPlotFormat(None, ax)
        ax.axhline(0, color='black', linewidth=0.5, linestyle='--')
        ax.plot(signal, label="PPG AC (filtered)", color="#111111", linewidth=1.2)
        ax.set_xlabel("Samples", fontsize=8)
        ax.set_ylabel("Amplitude", fontsize=8)
        ax.set_title("PPG AC - HRM Arduino", fontsize=9, pad=3)
        ax.legend(loc="upper right", frameon=False, fontsize=7)
        ax.tick_params(axis='both', which='major', labelsize=7)

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

        for idx_order, idx_peak in enumerate(peak_indices):
            ax.axvline(idx_peak, color=("red" if idx_order % 2 == 0 else "blue"),
                       linestyle="--", linewidth=0.8)

        si_value = float(self.last_si_value)
        hrv_value = float(self. last_hrv_value)
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
                            self. last_si_value = si_value
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
                    self.si_accumulator. append(float(si_value))
                if isinstance(hrv_value, (int, float)) and np.isfinite(hrv_value):
                    self.hrv_accumulator.append(float(hrv_value))
                if mfcc_value is not None and isinstance(mfcc_value, (list, np.ndarray)) and len(mfcc_value) == 13:
                    self. mfcc_accumulator.append(np.array(mfcc_value, dtype=float))


class ArduinoPlotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HRM Arduino Monitor")

        self.bg_color = "#f5f5f7"
        self.accent_color = "#007aff"
        self.root.configure(bg=self.bg_color)

        # ===== WINDOW SETUP =====
        window_width = 768
        window_height = 420

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)

        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.minsize(768, 420)
        self.root.resizable(True, True)

        # Font settings
        self.scale = 1.0
        base_btn_size = 9
        base_lbl_size = 9

        self.btn_font = ("Helvetica", base_btn_size, "bold")
        self.lbl_font = ("Helvetica", base_lbl_size)

        # Serial & data
        self.running = False
        self.ser = None
        self.serial_thread = None
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
        self.metrics_after_id = None

        # Antropometri
        self.last_age = None
        self.last_height = None
        self.last_weight = None
        self.last_bmi = None
        self.last_filename = ""
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
        self. settings_window = None

        # Countdown label reference
        self.countdown_label = None
        self.avg_si_label = None
        self. avg_hrv_label = None
        self.avg_mfcc_label = None
        self.avg_vol_label = None
        self.avg_adc_label = None

        # Layout frames
        self.top_frame = tk.Frame(root, bg=self.bg_color)
        self.top_frame.pack(side=tk.TOP, fill=tk. BOTH, expand=True, padx=5, pady=5)

        self.bottom_frame = tk.Frame(root, bg=self.bg_color)
        self.bottom_frame.pack(side=tk. BOTTOM, fill=tk.X, padx=5, pady=3)

        # ===== PLOT AREA =====
        self.fig = plt.Figure(figsize=(8, 2.5), dpi=100)
        self.fig.patch.set_facecolor(self.bg_color)

        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("#ffffff")

        self.fig.subplots_adjust(left=0.06, right=0.98, top=0.90, bottom=0.18)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.top_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # ttk style combobox
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except:
            pass

        style.configure(
            "Big.TCombobox",
            fieldbackground="#ffffff",
            background="#ffffff",
            foreground="#000000",
            bordercolor="#dddddd",
            padding=(2, 1, 2, 1),
            arrowcolor="#555555"
        )

        # Baris 1: port + tombol
        control_frame = tk.Frame(self.bottom_frame, bg=self.bg_color)
        control_frame.pack(side=tk.TOP, fill=tk.X, pady=2)

        tk.Label(control_frame, text="Port:", font=self.lbl_font, bg=self.bg_color).pack(side=tk.LEFT, padx=3)

        self.port_combo = ttk.Combobox(control_frame, width=10, state="readonly", style="Big.TCombobox")
        self.port_combo. pack(side=tk.LEFT, padx=3)

        def make_btn(parent, text, bg_color, fg_color, cmd):
            return tk.Button(
                parent, text=text, command=cmd,
                font=self.btn_font, bg=bg_color, fg=fg_color,
                activebackground=bg_color, activeforeground=fg_color,
                bd=0, relief="flat", width=8, height=1
            )

        self.refresh_button = make_btn(control_frame, "Refresh", "#e5e5ea", "#111111", self.refresh_ports)
        self.refresh_button.pack(side=tk.LEFT, padx=3, pady=1)

        self.start_button = make_btn(control_frame, "Start", "#34c759", "#ffffff", self.start_serial)
        self.start_button.pack(side=tk.LEFT, padx=3, pady=1)

        self.stop_button = make_btn(control_frame, "Stop", "#ff3b30", "#ffffff", self.stop_serial)
        self.stop_button.pack(side=tk.LEFT, padx=3, pady=1)

        self.status_label = tk.Label(control_frame, text="Disconnected",
                                     fg=self.accent_color, font=self.lbl_font, bg=self.bg_color)
        self.status_label.pack(side=tk.LEFT, padx=8)

        try:
            self.mqtt = PpgMqttFlow.from_config(
                load_config(MQTT_CONFIG),
                status_callback=self.on_mqtt_status,
            )
        except (OSError, KeyError, TypeError, ValueError) as error:
            messagebox.showerror(
                "MQTT Configuration Error",
                f"Gagal membaca konfigurasi MQTT:\n{MQTT_CONFIG}\n\n{error}",
            )
            raise

        # Baris 2: input (dengan Filename)
        info_frame = tk.Frame(self.bottom_frame, bg=self.bg_color)
        info_frame.pack(side=tk.TOP, fill=tk.X, pady=2)

        # Field Filename
        tk.Label(info_frame, text="Name:", font=self.lbl_font, bg=self.bg_color).pack(side=tk.LEFT, padx=3)
        self.filename_entry = tk.Entry(info_frame, width=10, font=self.lbl_font, bd=1, relief="solid")
        self.filename_entry.pack(side=tk.LEFT, padx=3)
        self.filename_entry.bind("<FocusIn>", lambda e: setattr(self, "active_entry", self.filename_entry))

        tk.Label(info_frame, text="Age:", font=self.lbl_font, bg=self.bg_color).pack(side=tk.LEFT, padx=3)
        self.age_entry = tk.Entry(info_frame, width=4, font=self.lbl_font, bd=1, relief="solid")
        self.age_entry.pack(side=tk. LEFT, padx=3)
        self.age_entry.bind("<FocusIn>", lambda e: setattr(self, "active_entry", self.age_entry))
        self.active_entry = self.age_entry

        tk.Label(info_frame, text="Height:", font=self.lbl_font, bg=self. bg_color).pack(side=tk.LEFT, padx=3)
        self.height_entry = tk.Entry(info_frame, width=5, font=self.lbl_font, bd=1, relief="solid")
        self.height_entry.pack(side=tk. LEFT, padx=3)
        self.height_entry.bind("<FocusIn>", lambda e: setattr(self, "active_entry", self.height_entry))

        tk.Label(info_frame, text="Weight:", font=self.lbl_font, bg=self.bg_color).pack(side=tk.LEFT, padx=3)
        self.weight_entry = tk.Entry(info_frame, width=5, font=self.lbl_font, bd=1, relief="solid")
        self.weight_entry. pack(side=tk.LEFT, padx=3)
        self.weight_entry.bind("<FocusIn>", lambda e:  setattr(self, "active_entry", self.weight_entry))

        def make_small_btn(parent, text, cmd, bg_color="#e5e5ea", fg_color="#111111"):
            return tk.Button(
                parent, text=text, command=cmd,
                font=self.btn_font,
                bg=bg_color, fg=fg_color,
                activebackground="#d1d1d6", activeforeground="#111111",
                bd=0, relief="flat", width=7, height=1,
                disabledforeground="#999999"
            )

        self.numpad_button = make_small_btn(info_frame, "Numpad", self.open_numpad)
        self.numpad_button.pack(side=tk.LEFT, padx=3, pady=1)

        self.submit_button = make_small_btn(info_frame, "Submit", self.submit_height, "#007aff", "#ffffff")
        self.submit_button.pack(side=tk.LEFT, padx=3, pady=1)

        self.settings_button = make_small_btn(info_frame, "Settings", self.open_settings)
        self.settings_button.pack(side=tk.LEFT, padx=3, pady=1)

        # Baris 3 & 4: metrik
        metrics_frame1 = tk.Frame(self. bottom_frame, bg=self. bg_color)
        metrics_frame1.pack(side=tk.TOP, fill=tk.X, pady=1)

        metrics_frame2 = tk.Frame(self.bottom_frame, bg=self.bg_color)
        metrics_frame2.pack(side=tk.TOP, fill=tk.X, pady=1)

        self.si_label = tk.Label(metrics_frame1, text="SI:  0", font=self.lbl_font, bg=self. bg_color)
        self.si_label.pack(side=tk.LEFT, padx=8)

        self.hrv_label = tk.Label(metrics_frame1, text="HRV: 0", font=self. lbl_font, bg=self.bg_color)
        self.hrv_label.pack(side=tk.LEFT, padx=8)

        self.bmi_label = tk.Label(metrics_frame1, text="BMI: 0.00", font=self.lbl_font, bg=self.bg_color)
        self.bmi_label.pack(side=tk.LEFT, padx=8)

        self.age_value_label = tk.Label(metrics_frame1, text="Age: -", font=self.lbl_font, bg=self.bg_color)
        self.age_value_label.pack(side=tk.LEFT, padx=8)

        self.mfcc_label = tk.Label(metrics_frame2, text="MFCC:  0", font=self.lbl_font, bg=self. bg_color)
        self.mfcc_label.pack(side=tk.LEFT, padx=8)

        self.vol_label = tk.Label(metrics_frame2, text="Vol:  0.00 V", font=self.lbl_font, bg=self.bg_color)
        self.vol_label.pack(side=tk. LEFT, padx=8)

        self.adc_label = tk.Label(metrics_frame2, text="ADC: 0", font=self.lbl_font, bg=self.bg_color)
        self.adc_label.pack(side=tk.LEFT, padx=8)

        # Plot handler
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

    def disable_submit_button(self):
        try:
            self.submit_button.config(state=tk.DISABLED, bg="#cccccc")
        except tk.TclError:
            pass

    def enable_submit_button(self):
        try:
            self.submit_button.config(state=tk.NORMAL, bg="#007aff")
        except tk.TclError:
            pass

    def _is_window_valid(self, window):
        try:
            if window is None:
                return False
            return window.winfo_exists()
        except tk.TclError:
            return False

    def _create_popup(self, title, width=None, height=None):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.configure(bg=self.bg_color)

        popup.attributes("-topmost", True)

        if width and height:
            x = (self.root.winfo_screenwidth() // 2) - (width // 2)
            y = (self.root. winfo_screenheight() // 2) - (height // 2)
            popup.geometry(f"{width}x{height}+{x}+{y}")

        popup.resizable(True, True)
        popup.focus_force()
        popup.lift()

        return popup

    # ==================== SERIAL ====================

    def on_mqtt_status(self, status):
        colors = {
            "connected": "#34c759",
            "connecting": "#ff9500",
            "reconnecting": "#ff9500",
            "rejected": "#ff3b30",
            "error": "#ff3b30",
            "disconnected": "#ff3b30",
        }

        def update():
            serial_status = "connected" if self.running else "off"
            self.status_label.config(
                text=f"Serial: {serial_status} | MQTT: {status}",
                fg=colors.get(status, self.accent_color),
            )

        try:
            self.root.after(0, update)
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
        self.status_label.config(text="Ports refreshed", fg=self.accent_color)

    def start_serial(self):
        if self.running:
            return

        port_name = self.port_combo. get()
        if not port_name:
            messagebox.showwarning("No Port", "Silakan pilih port terlebih dahulu.")
            return

        try:
            self. ser = serial.Serial(port_name, SERIAL_BAUD, timeout=0.1)
            self.running = True
            self.mqtt.connect()
            self.serial_thread = threading.Thread(target=self.serial_reader, daemon=True)
            self.serial_thread.start()
            self.status_label.config(
                text="Serial: connected | MQTT: connecting",
                fg="#ff9500",
            )
        except serial.SerialException as e:
            messagebox.showerror("Serial Error", f"Gagal membuka port {port_name}:\n{e}")
            self.status_label.config(text="Disconnected", fg="#ff3b30")
            self.running = False
            self.ser = None
        except Exception as error:
            self.running = False
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
            messagebox.showerror("MQTT Error", f"Gagal memulai MQTT:\n{error}")
            self.status_label.config(text="Disconnected", fg="#ff3b30")

    def stop_serial(self):
        self.running = False
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception: 
            pass
        self.ser = None
        self.mqtt.disconnect()
        self.status_label.config(
            text="Serial: off | MQTT: disconnected",
            fg="#ff3b30",
        )

    def serial_reader(self):
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
            except serial.SerialException as e:
                print("Serial error:", e)
                break
            except Exception as e:
                print("Unexpected error:", e)
                break
        self.running = False
        self.mqtt.disconnect()
        try:
            self.root.after(
                0,
                lambda: self.status_label.config(
                    text="Serial: off | MQTT: disconnected",
                    fg="#ff3b30",
                ),
            )
        except tk.TclError:
            pass

    # ==================== NUMPAD ====================

    def open_numpad(self):
        if self._is_window_valid(self. numpad_window):
            self.numpad_window.lift()
            self.numpad_window.focus_force()
            return

        self.numpad_window = self._create_popup("Numpad", 180, 250)

        def on_numpad_close():
            try:
                if self.numpad_window:
                    self.numpad_window.destroy()
            except Exception:
                pass
            self.numpad_window = None

        self.numpad_window.protocol("WM_DELETE_WINDOW", on_numpad_close)

        btn_frame = tk.Frame(self.numpad_window, bg=self.bg_color)
        btn_frame.pack(expand=True, fill=tk. BOTH, padx=8, pady=8)

        buttons = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            (".", 3, 0), ("0", 3, 1), ("C", 3, 2),
            ("Del", 4, 0), ("OK", 4, 1),
        ]

        for (text, r, c) in buttons:
            colspan = 2 if text == "OK" else 1
            bg_clr = "#e5e5ea"
            fg_clr = "#111111"
            if text == "OK":
                bg_clr = "#34c759"
                fg_clr = "#ffffff"
            elif text == "C":
                bg_clr = "#ff9500"

            b = tk.Button(
                btn_frame,
                text=text,
                width=4 if colspan == 1 else 9,
                height=1,
                font=self.btn_font,
                bg=bg_clr,
                fg=fg_clr,
                activebackground="#d1d1d6",
                bd=0,
                relief="flat",
                command=lambda t=text: self.numpad_press(t),
            )
            b.grid(row=r, column=c, columnspan=colspan, padx=2, pady=2, sticky="ew")

        for i in range(3):
            btn_frame.columnconfigure(i, weight=1)

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
            if self._is_window_valid(self. numpad_window):
                self.numpad_window.destroy()
                self.numpad_window = None

    # ==================== SETTINGS ====================

    def open_settings(self):
        if self._is_window_valid(self.settings_window):
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        self.settings_window = self._create_popup("MFCC Settings", 320, 280)

        def on_settings_close():
            try:
                if self.settings_window:
                    self.settings_window. destroy()
            except Exception: 
                pass
            self.settings_window = None

        self.settings_window.protocol("WM_DELETE_WINDOW", on_settings_close)

        params = self.realTimePlot.mfcc_params

        main_frame = tk.Frame(self.settings_window, bg=self.bg_color)
        main_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        tk.Label(main_frame, text="Sample Rate (Hz):", bg=self.bg_color, font=self.lbl_font).grid(row=0, column=0, padx=4, pady=4, sticky="e")
        sr_entry = tk.Entry(main_frame, font=self.lbl_font, width=10)
        sr_entry.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        sr_entry.insert(0, str(params["sr"]))

        tk.Label(main_frame, text="Frame length (ms):", bg=self.bg_color, font=self.lbl_font).grid(row=1, column=0, padx=4, pady=4, sticky="e")
        frame_entry = tk.Entry(main_frame, font=self.lbl_font, width=10)
        frame_entry.grid(row=1, column=1, padx=4, pady=4, sticky="w")
        frame_entry.insert(0, str(params["frame_ms"]))

        tk.Label(main_frame, text="Hop length (ms):", bg=self.bg_color, font=self.lbl_font).grid(row=2, column=0, padx=4, pady=4, sticky="e")
        hop_entry = tk.Entry(main_frame, font=self.lbl_font, width=10)
        hop_entry.grid(row=2, column=1, padx=4, pady=4, sticky="w")
        hop_entry.insert(0, str(params["hop_ms"]))

        tk.Label(main_frame, text="Number of MFCC:", bg=self. bg_color, font=self. lbl_font).grid(row=3, column=0, padx=4, pady=4, sticky="e")
        n_mfcc_entry = tk.Entry(main_frame, font=self.lbl_font, width=10)
        n_mfcc_entry.grid(row=3, column=1, padx=4, pady=4, sticky="w")
        n_mfcc_entry.insert(0, str(params["n_mfcc"]))

        tk.Label(main_frame, text="Window type:", bg=self.bg_color, font=self.lbl_font).grid(row=4, column=0, padx=4, pady=4, sticky="e")
        window_var = tk.StringVar(value=params["window"])
        window_menu = ttk.Combobox(main_frame, textvariable=window_var,
                                   values=["hann", "hamming", "blackman", "boxcar"], state="readonly", width=10)
        window_menu.grid(row=4, column=1, padx=4, pady=4, sticky="w")

        tk.Label(main_frame, text="MFCC mode:", bg=self.bg_color, font=self.lbl_font).grid(row=5, column=0, padx=4, pady=4, sticky="e")
        mode_var = tk.StringVar(value=self.realTimePlot.mfcc_mode)
        mode_menu = ttk.Combobox(main_frame, textvariable=mode_var,
                                 values=["standard", "peak"], state="readonly", width=10)
        mode_menu.grid(row=5, column=1, padx=4, pady=4, sticky="w")

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
                messagebox.showerror("Invalid Input", "Pastikan semua parameter diisi dengan benar.")

        btn_frame = tk.Frame(main_frame, bg=self.bg_color)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=10)

        tk.Button(btn_frame, text="Save", command=on_save, font=self.btn_font,
                  bg="#34c759", fg="#ffffff", bd=0, relief="flat", width=7).pack(side=tk.LEFT, padx=8)

        tk.Button(btn_frame, text="Cancel", command=on_settings_close, font=self.btn_font,
                  bg="#ff3b30", fg="#ffffff", bd=0, relief="flat", width=7).pack(side=tk.LEFT, padx=8)

    # ==================== MEASUREMENT 300s ====================

    def start_logging(self):
        self.logging_active = True
        self.logging_start_time = time.time()
        self.realTimePlot.reset_accumulators()

    def finish_logging(self):
        if not self.logging_active:
            return

        avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc = self. realTimePlot.compute_overall_means()
        self.mqtt.complete_measurement(
            si_mean=avg_si,
            hrv_mean=avg_hrv,
            mfcc_mean=avg_mfcc,
            voltage_mean=avg_vol,
            adc_mean=avg_adc,
        )

        self.logging_active = False
        self.measurement_in_progress = False
        self. enable_submit_button()

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

        prefix = self.last_filename.strip() if self.last_filename else ""
        prefix = "". join(c for c in prefix if c.isalnum() or c in ('_', '-'))

        if prefix:
            filename = f"{prefix}_{now}.csv"
        else:
            filename = f"hrm_avg_{now}.csv"

        header = [
            "Timestamp",
            "Filename",
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
            prefix if prefix else "N/A",
            str(self.last_age) if self.last_age is not None else "-1",
            self.format_float(self.last_height) if self.last_height is not None else "",
            self.format_float(self.last_weight) if self.last_weight is not None else "",
            self.format_float(self.last_bmi) if self.last_bmi is not None else "",
            self. format_float(avg_si) if not np.isnan(avg_si) else "",
            self.format_float(avg_hrv) if not np.isnan(avg_hrv) else "",
            self.format_float(avg_vol) if not np.isnan(avg_vol) else "",
            str(int(round(avg_adc))) if not np.isnan(avg_adc) else "",
        ]
        row.extend(mfcc_list)

        try:
            with open(filename, mode="w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer. writerow(row)
            print(f"CSV saved:  {filename}")
        except Exception as e:
            messagebox.showerror("CSV Error", str(e))

    # ==================== SUBMIT ====================

    def submit_height(self):
        if self.measurement_in_progress:
            messagebox.showwarning("Measurement Active",
                                   "Measurement sedang berjalan!\nTunggu hingga selesai atau stop terlebih dahulu.")
            return

        try:
            age_str = clean_number_input(self.age_entry.get())
            height_str = clean_number_input(self.height_entry.get())
            weight_str = clean_number_input(self.weight_entry.get())

            print(f"DEBUG - Age: '{age_str}', Height: '{height_str}', Weight: '{weight_str}'")

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

            height_m = height_cm / 100.0
            self.last_bmi = weight_kg / (height_m ** 2)

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
        except ValueError as e: 
            print(f"DEBUG - ValueError: {e}")
            messagebox.showerror("Invalid Input", "Masukkan umur, tinggi, berat yang valid.\n\nPastikan:\n- Semua field terisi\n- Hanya angka dan titik desimal\n- Nilai lebih dari 0")

    # ==================== COUNTDOWN WINDOW ====================

    def start_countdown(self):
        if self.countdown_after_id is not None:
            try:
                self.root.after_cancel(self.countdown_after_id)
            except: 
                pass
            self.countdown_after_id = None

        self.countdown_value = 300

        if self._is_window_valid(self. averages_window):
            try:
                if self.countdown_label:
                    self.countdown_label.config(text="300", fg="#007aff")
                if self.avg_si_label:
                    self.avg_si_label. config(text="Average SI:  Measuring...")
                if self.avg_hrv_label:
                    self.avg_hrv_label.config(text="Average HRV: Measuring...")
                if self.avg_mfcc_label:
                    self.avg_mfcc_label.config(text="Average MFCC: Measuring...")
                if self.avg_vol_label:
                    self.avg_vol_label.config(text="Average Voltage: Measuring...")
                if self.avg_adc_label:
                    self.avg_adc_label.config(text="Average ADC: Measuring...")
                self.averages_window.lift()
            except tk.TclError:
                self.averages_window = None

        if not self._is_window_valid(self. averages_window):
            self.averages_window = self._create_popup("Measurement - 300 Seconds", 400, 320)

            def on_averages_close():
                if self.countdown_after_id is not None:
                    try:
                        self.root. after_cancel(self.countdown_after_id)
                    except:
                        pass
                    self.countdown_after_id = None

                self.mqtt.cancel_measurement("measurement_window_closed")
                self.logging_active = False
                self. measurement_in_progress = False
                self.enable_submit_button()
                try:
                    if self.averages_window:
                        self.averages_window.destroy()
                except Exception:
                    pass
                self.averages_window = None
                self.countdown_label = None
                self. avg_si_label = None
                self.avg_hrv_label = None
                self.avg_mfcc_label = None
                self.avg_vol_label = None
                self.avg_adc_label = None

            self.averages_window.protocol("WM_DELETE_WINDOW", on_averages_close)

            main_frame = tk.Frame(self.averages_window, bg=self.bg_color)
            main_frame.pack(expand=True, fill=tk.BOTH, padx=15, pady=10)

            self.countdown_label = tk.Label(
                main_frame, text="300",
                font=("Helvetica", 32, "bold"),
                bg=self.bg_color, fg="#007aff"
            )
            self.countdown_label.pack(pady=8)

            tk.Label(main_frame, text="seconds remaining",
                     font=self.lbl_font, bg=self.bg_color, fg="#666666").pack()

            ttk.Separator(main_frame, orient="horizontal").pack(fill=tk.X, pady=8)

            self.avg_si_label = tk.Label(main_frame, text="Average SI:  Measuring...",
                                         font=self. lbl_font, bg=self.bg_color)
            self.avg_si_label.pack(pady=1, anchor="w")

            self.avg_hrv_label = tk. Label(main_frame, text="Average HRV: Measuring.. .",
                                          font=self.lbl_font, bg=self.bg_color)
            self.avg_hrv_label.pack(pady=1, anchor="w")

            self.avg_vol_label = tk.Label(main_frame, text="Average Voltage: Measuring...",
                                          font=self.lbl_font, bg=self.bg_color)
            self.avg_vol_label.pack(pady=1, anchor="w")

            self.avg_adc_label = tk.Label(main_frame, text="Average ADC:  Measuring...",
                                          font=self.lbl_font, bg=self.bg_color)
            self.avg_adc_label.pack(pady=1, anchor="w")

            self.avg_mfcc_label = tk.Label(main_frame, text="Average MFCC:  Measuring...",
                                           font=self.lbl_font, bg=self.bg_color, wraplength=360, justify="left")
            self.avg_mfcc_label. pack(pady=1, anchor="w")

            tk.Button(
                main_frame, text="Stop & Close",
                command=on_averages_close, font=self.btn_font,
                bg="#ff3b30", fg="#ffffff", bd=0, relief="flat", width=10
            ).pack(pady=10)

        self.countdown_tick()

    def countdown_tick(self):
        if not self.logging_active:
            return

        if self.countdown_label and self._is_window_valid(self. averages_window):
            try:
                if self.countdown_value > 0:
                    self.countdown_label.config(text=str(self.countdown_value), fg="#007aff")
                    self.countdown_value -= 1
                    self.countdown_after_id = self.root. after(1000, self.countdown_tick)
                else:
                    self.countdown_label.config(text="Done!", fg="#34c759")
                    self. countdown_after_id = None
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
                text = f"Average SI: {avg_si:.4f} m/s" if not np.isnan(avg_si) else "Average SI: N/A"
                self.avg_si_label. config(text=text)

            if self.avg_hrv_label:
                text = f"Average HRV: {avg_hrv:.2f} ms" if not np.isnan(avg_hrv) else "Average HRV: N/A"
                self.avg_hrv_label.config(text=text)

            if self.avg_vol_label:
                text = f"Average Voltage: {avg_vol:.4f} V" if not np. isnan(avg_vol) else "Average Voltage: N/A"
                self.avg_vol_label.config(text=text)

            if self.avg_adc_label:
                text = f"Average ADC: {int(round(avg_adc))}" if not np.isnan(avg_adc) else "Average ADC: N/A"
                self.avg_adc_label.config(text=text)

            if self.avg_mfcc_label:
                if avg_mfcc is not None and not isinstance(avg_mfcc, str):
                    mfccs_str = ", ".join(f"{m:.2f}" for m in avg_mfcc)
                    self.avg_mfcc_label.config(text=f"Average MFCC: [{mfccs_str}]")
                else:
                    self.avg_mfcc_label.config(text="Average MFCC: N/A")
        except tk.TclError:
            pass

    # ==================== LABEL UPDATES ====================

    def update_si_label(self, si):
        self.latest_si = self.metric_number(si)
        try:
            self.si_label.config(text=f"SI: {si}" if isinstance(si, str) else f"SI: {si:.4f} m/s")
        except tk.TclError:
            pass

    def update_hrv_label(self, hrv):
        self.latest_hrv = self.metric_number(hrv)
        try:
            self.hrv_label. config(text=f"HRV: {hrv}" if isinstance(hrv, str) else f"HRV: {hrv:.2f} ms")
        except tk.TclError:
            pass

    def update_bmi_label(self, bmi):
        self.latest_bmi = self.metric_number(bmi)
        try:
            self.bmi_label.config(text=f"BMI: {bmi}" if isinstance(bmi, str) else f"BMI: {bmi:.2f}")
        except tk.TclError:
            pass

    def update_age_value_label(self, age):
        number = self.metric_number(age)
        self.latest_age = int(round(number)) if number is not None else None
        try:
            self.age_value_label.config(text=f"Age: {age}" if isinstance(age, str) else f"Age: {int(age)}")
        except tk.TclError:
            pass

    def update_vol_label(self, vol):
        self.latest_voltage = self.metric_number(vol)
        try:
            self.vol_label.config(text=f"Vol: {vol}" if isinstance(vol, str) else f"Vol: {vol:.2f} V")
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
            self.adc_label.config(text=f"ADC:  {adc_val}")
        except Exception:
            pass

    def update_mfcc_label(self, mfccs):
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
                self.mfcc_label.config(text=f"MFCC: {mfccs}")
            else:
                mfccs_str = ", ". join(f"{m:.2f}" for m in mfccs)
                self.mfcc_label.config(text=f"MFCC: {mfccs_str}")
        except tk.TclError:
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
            except:
                pass

        self.logging_active = False
        self. measurement_in_progress = False
        self.stop_serial()

        for window in [self.numpad_window, self.settings_window, self.averages_window]:
            if self._is_window_valid(window):
                try:
                    window.destroy()
                except Exception:
                    pass

        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    root = tk. Tk()
    app = ArduinoPlotApp(root)
    app.run()
