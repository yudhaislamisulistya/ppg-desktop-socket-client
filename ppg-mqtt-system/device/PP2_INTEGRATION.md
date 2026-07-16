# Integrasi ke `pp2.py`

Dokumen ini mempertahankan perilaku aplikasi lama:

- `Start`: membuka serial dan mulai live MQTT.
- Saat Start: mengirim waveform dan snapshot HRV/MFCC/Voltage/ADC realtime.
- `Submit`: memvalidasi pasien, membuat `measurement_id`, lalu mulai menyimpan.
- Setelah Submit: snapshot SI/HRV/BMI/Age/MFCC/Voltage/ADC dikirim realtime.
- Selesai 300 detik: mengirim hasil akhir dan kembali ke live preview.
- `Stop`: membatalkan sesi aktif jika ada, kemudian memutus serial dan MQTT.

## 1. Siapkan file pada Raspberry Pi

Salin ke folder yang sama dengan `pp2.py`:

```text
pp2.py
mqtt_flow.py
mqtt_config.json
```

Gunakan `config.example.json` sebagai dasar `mqtt_config.json`.

Instal client MQTT:

```bash
python3 -m pip install paho-mqtt==2.1.0
```

## 2. Tambahkan import

Di bagian import `pp2.py`:

```python
from pathlib import Path
from mqtt_flow import PpgMqttFlow, load_config
```

## 3. Buat client MQTT

Setelah `self.status_label` selesai dibuat di `__init__`, tambahkan:

```python
mqtt_config = load_config(Path(__file__).with_name("mqtt_config.json"))
self.mqtt = PpgMqttFlow.from_config(
    mqtt_config,
    status_callback=self.on_mqtt_status,
)
```

Tambahkan method berikut ke `ArduinoPlotApp`:

```python
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
        self.status_label.config(
            text=f"Serial: {'connected' if self.running else 'off'} | MQTT: {status}",
            fg=colors.get(status, self.accent_color),
        )

    try:
        self.root.after(0, update)
    except tk.TclError:
        pass
```

`root.after()` diperlukan karena callback MQTT berjalan pada thread berbeda dari Tkinter.

## 4. Hubungkan MQTT pada tombol Start

Pada `start_serial()`, setelah thread serial berhasil dimulai:

```python
self.mqtt.connect()
```

Bagian akhirnya menjadi:

```python
self.ser = serial.Serial(port_name, SERIAL_BAUD, timeout=0.1)
self.running = True
self.mqtt.connect()
self.serial_thread = threading.Thread(target=self.serial_reader, daemon=True)
self.serial_thread.start()
self.status_label.config(text=f"Connected: {port_name}", fg="#34c759")
```

## 5. Kirim setiap nilai ADC

Pada `serial_reader()`, setelah `value = float(line)`:

```python
self.mqtt.add_sample(value)
```

Contoh:

```python
value = float(line)

with self.data_lock:
    self.dataList.append(value)
    if len(self.dataList) > 5000:
        self.dataList = self.dataList[-5000:]

self.mqtt.add_sample(value)
```

`mqtt_flow.py` otomatis mengelompokkan 10 sampel menjadi satu pesan. Pembacaan serial tidak perlu membuat batch sendiri.

## 6. Kirim metrik realtime

Implementasi yang paling aman sudah tersedia pada `pp2_mqtt_app.py`. Launcher
tersebut mewarisi callback label dari `pp2.py`, menyimpan nilai terbaru, lalu
memanggil:

```python
self.mqtt.publish_metrics(
    si_m_s=latest_si,
    hrv_ms=latest_hrv,
    bmi=latest_bmi,
    age_years=latest_age,
    mfcc=latest_mfcc,
    voltage_v=latest_voltage,
    adc=latest_adc,
)
```

Pemanggilan dijadwalkan dengan `root.after()` sesuai `metrics_interval_ms`
(default `200 ms`). Jangan publish langsung pada setiap callback animasi karena
callback berjalan sekitar setiap 50 ms dan dapat menghasilkan trafik yang tidak
perlu.

Topic yang dihasilkan:

```text
ppg/{device_id}/metrics
```

Callback sumber nilainya:

| Callback `pp2.py` | Field MQTT |
|---|---|
| `update_si_label()` | `si_m_s` |
| `update_hrv_label()` | `hrv_ms` |
| `update_bmi_label()` | `bmi` |
| `update_age_value_label()` | `age_years` |
| `update_mfcc_label()` | `mfcc` |
| `update_vol_label()` | `voltage_v` |
| `update_adc_label()` | `adc` |

String seperti `Waiting peaks`, `Collecting...`, atau `Set height` tidak dikirim
sebagai angka; field terkait dikirim sebagai `null`.

BMI dan Age berasal dari input pasien. SI membutuhkan tinggi pasien. Karena itu,
ketiganya dikirim `null` sebelum Submit dan mulai tersedia selama recording.

## 7. Mulai penyimpanan pada Submit

Pada `submit_height()`, setelah nilai umur, tinggi, berat, BMI, dan nama pasien berhasil disimpan, tetapi sebelum `self.start_logging()`, tambahkan:

```python
try:
    self.mqtt.begin_measurement(
        patient_code=self.last_filename or "N/A",
        age=self.last_age,
        height_cm=self.last_height,
        weight_kg=self.last_weight,
        bmi=self.last_bmi,
        duration_seconds=300,
    )
except RuntimeError as error:
    messagebox.showerror("MQTT Error", str(error))
    return
```

Urutan yang disarankan:

```python
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

self.measurement_in_progress = True
self.disable_submit_button()
self.start_logging()
self.start_countdown()
```

## 8. Kirim hasil akhir

Pada `finish_logging()`, setelah `compute_overall_means()`:

```python
self.mqtt.complete_measurement(
    si_mean=avg_si,
    hrv_mean=avg_hrv,
    mfcc_mean=avg_mfcc,
    voltage_mean=avg_vol,
    adc_mean=avg_adc,
)
```

Modul MQTT otomatis mengubah `NaN` menjadi `null` dan array NumPy menjadi array JSON.

CSV lokal lama tetap dapat disimpan:

```python
self.save_average_csv(avg_si, avg_hrv, avg_mfcc, avg_vol, avg_adc)
```

## 9. Tangani pembatalan

Pada callback tombol `Stop & Close` di window measurement, sebelum mengubah `logging_active`:

```python
self.mqtt.cancel_measurement("measurement_window_closed")
```

Pada `stop_serial()`:

```python
self.mqtt.disconnect()
```

Pada `on_close()`, sebelum `self.root.destroy()`:

```python
self.mqtt.disconnect()
```

Method `disconnect()` aman dipanggil lebih dari sekali.

## 10. Hasil flow

Sebelum Submit:

```json
{
  "measurement_id": null,
  "mode": "live",
  "samples": [512, 518, 525]
}
```

Sesudah Submit:

```json
{
  "measurement_id": "measurement-unik",
  "mode": "recording",
  "samples": [512, 518, 525]
}
```

Service storage hanya menyimpan payload kedua.

Topic `metrics` tetap realtime-only. Storage tidak menyimpan setiap snapshot;
nilai rata-rata disimpan saat `measurement/result`.
