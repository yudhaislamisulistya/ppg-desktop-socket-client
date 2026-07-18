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

Contoh (broker di belakang domain + reverse proxy TLS, lihat bagian
"Koneksi lewat domain/HTTPS" di bawah):

```json
{
  "device_id": "PPG-ABC12345",
  "mqtt_host": "mqtt-glucometer.sivia.id",
  "mqtt_port": 443,
  "mqtt_username": "PPG-ABC12345",
  "mqtt_password": "password-alat",
  "sample_period_ms": 10.0,
  "batch_size": 10,
  "metrics_interval_ms": 200,
  "tls": true,
  "ca_file": null,
  "transport": "websockets",
  "ws_path": "/mqtt"
}
```

`device_id`, username, dan password harus sama dengan perangkat yang dibuat
melalui `scripts/register-device.sh`.

### Koneksi lewat domain/HTTPS (reverse proxy)

Jika broker tidak lagi diakses lewat IP + port MQTT mentah (1883/8883),
melainkan lewat domain yang hanya membuka port 443 (mis. di belakang Caddy
atau nginx dengan sertifikat Let's Encrypt), `pp2.py` **tidak bisa** connect
dengan TCP biasa — port MQTT mentahnya memang tidak reachable dari luar.
Gunakan MQTT over WebSocket (WSS) lewat proxy yang sama dengan field berikut:

| Field | Nilai | Keterangan |
|---|---|---|
| `mqtt_host` | domain saja, tanpa `https://` dan tanpa trailing slash | contoh: `mqtt-glucometer.sivia.id` |
| `mqtt_port` | `443` | port HTTPS yang dibuka reverse proxy |
| `tls` | `true` | wajib, karena WSS berjalan di atas TLS |
| `transport` | `"websockets"` | default sebelumnya `"tcp"`; field baru, opsional |
| `ws_path` | path WebSocket yang dikirim client, mis. `"/mqtt"` | hanya perlu cocok dengan reverse proxy kalau proxy melakukan *path-based routing*; kalau proxy me-route berdasarkan `Host` saja (lihat contoh Traefik di bawah), path apapun diteruskan apa adanya dan tidak perlu dikoordinasikan |

**Verified 2026-07-18**: setup produksi memakai Traefik (dikelola Coolify) di
server terpisah (`202.141.15.5`), bukan di server yang sama dengan Mosquitto.
Contoh konfigurasi dinamis Traefik untuk domain ini:

```yaml
http:
  routers:
    mqtt-glucometer-wss:
      rule: Host(`mqtt-glucometer.sivia.id`)
      entryPoints: [https]
      service: mqtt-glucometer-ws-service
      tls:
        certResolver: letsencrypt
  services:
    mqtt-glucometer-ws-service:
      loadBalancer:
        servers:
          - url: 'http://202.141.15.3:9001'
```

Router-nya hanya mencocokkan `Host`, tanpa `PathPrefix`, sehingga field
`ws_path` di `mqtt_config.json` bebas diisi apa saja (default `/mqtt` sudah
cukup). TLS berhenti di Traefik; koneksi Traefik → Mosquitto memakai `http://`
biasa ke port `9001` di dalam jaringan internal.

Endpoint ini sudah diverifikasi jalan end-to-end memakai `PpgMqttFlow` asli
dengan kredensial device produksi — connect-disconnect bersih dalam <1 detik.
Kalau `curl https://mqtt-glucometer.sivia.id/` biasa menghasilkan `502 Bad
Gateway`, itu **normal dan bukan bug**: GET biasa tidak mengirim header
`Connection: Upgrade` + `Sec-WebSocket-Protocol: mqtt`, jadi Mosquitto memang
menolaknya. Yang menentukan adalah client MQTT-over-WS asli seperti `pp2.py`,
bukan browser/curl polos.

- Port MQTT mentah (`1883`/`8883`) tidak perlu dibuka ke internet lagi kalau
  semua client (termasuk `pp2.py`) sudah memakai WSS lewat 443. (Traefik juga
  punya router TCP terpisah untuk MQTTS langsung via SNI ke port `1883`, pada
  entrypoint custom `mqtts` — ini opsional, port eksternalnya belum
  dikonfirmasi terbuka, dan tidak dibutuhkan karena jalur WSS sudah berfungsi
  penuh.)
- Field `transport`/`ws_path` bersifat opsional dan backward compatible:
  kalau tidak diisi, `PpgMqttFlow` tetap default ke `transport="tcp"` seperti
  sebelumnya (koneksi MQTT mentah di `mqtt_port`).

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
