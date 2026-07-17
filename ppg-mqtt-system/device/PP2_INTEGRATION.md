# Integrasi MQTT langsung pada `pp2.py`

MQTT sekarang sudah terintegrasi langsung pada:

```text
ppg-desktop/pp2.py
```

Launcher subclass tidak diperlukan lagi.

## File yang digunakan

```text
ppg-desktop/pp2.py
ppg-desktop/mqtt_config.json
ppg-mqtt-system/device/mqtt_flow.py
```

Salin konfigurasi contoh:

```bash
python3 -m pip install -r ppg-desktop/requirements.txt
cp ppg-desktop/mqtt_config.example.json ppg-desktop/mqtt_config.json
```

Contoh:

```json
{
  "device_id": "PPG-ABC12345",
  "mqtt_host": "202.141.15.3",
  "mqtt_port": 1883,
  "mqtt_username": "PPG-ABC12345",
  "mqtt_password": "password-alat",
  "sample_period_ms": 10.0,
  "batch_size": 10,
  "metrics_interval_ms": 200,
  "tls": false,
  "ca_file": null
}
```

`device_id`, username, dan password harus sama dengan perangkat yang dibuat
melalui `scripts/register-device.sh`.

## Flow tombol

### Start

`start_serial()` membuka serial lalu memanggil:

```python
self.mqtt.connect()
```

Setiap pembacaan ADC pada `serial_reader()` diteruskan ke:

```python
self.mqtt.add_sample(value)
```

Batch raw dikirim ke:

```text
ppg/{device_id}/raw
```

Sebelum Submit, payload memakai `mode="live"` dan `measurement_id=null`.

### Metrik realtime

Callback label menyimpan nilai terakhir:

| Callback | Field MQTT |
|---|---|
| `update_si_label()` | `si_m_s` |
| `update_hrv_label()` | `hrv_ms` |
| `update_bmi_label()` | `bmi` |
| `update_age_value_label()` | `age_years` |
| `update_mfcc_label()` | `mfcc` |
| `update_vol_label()` | `voltage_v` |
| `update_adc_label()` | `adc` |

Scheduler Tkinter mengirim snapshot setiap `metrics_interval_ms` ke:

```text
ppg/{device_id}/metrics
```

String status seperti `Waiting peaks`, `Set height`, atau `Calculating...`
diubah menjadi `null`.

Sebelum Submit:

- HRV, MFCC, Voltage, dan ADC dapat tersedia.
- SI, BMI, dan Age dikirim `null`.

Setelah Submit, semua nilai terbaru dapat dikirim dalam mode recording.

### Submit

Setelah input pasien valid, `submit_height()` memanggil:

```python
self.mqtt.begin_measurement(
    patient_code=self.last_filename or "N/A",
    age=self.last_age,
    height_cm=self.last_height,
    weight_kg=self.last_weight,
    bmi=self.last_bmi,
    duration_seconds=300,
)
```

Broker menerima:

```text
ppg/{device_id}/measurement/start
```

Submit ditolak jika MQTT belum terhubung. Ini mencegah recording dimulai tanpa
`measurement_id` pada server.

### Selesai

Setelah 300 detik, nilai rata-rata dikirim ke:

```text
ppg/{device_id}/measurement/result
```

Status yang dikirim adalah `completed`.

### Stop atau tutup popup

- Tombol Stop memanggil `mqtt.disconnect()`.
- Measurement aktif ditutup sebagai `cancelled`.
- Menutup popup measurement memakai alasan `measurement_window_closed`.
- Menutup aplikasi membatalkan scheduler Tkinter dan memutus MQTT.

## Menjalankan

```bash
python ppg-desktop/pp2.py
```

Jika helper atau config berada di lokasi lain:

```bash
MQTT_DEVICE_DIR=/path/ke/device \
MQTT_CONFIG=/path/ke/mqtt_config.json \
python /path/ke/pp2.py
```

Status aplikasi akan menampilkan status serial dan MQTT secara terpisah:

```text
Serial: connected | MQTT: connected
```

## Penyimpanan

- Raw live dan snapshot `metrics` tidak disimpan.
- Setelah Submit, raw dengan `measurement_id` disimpan ke SQLite.
- Hasil rata-rata disimpan saat event `measurement/result`.
