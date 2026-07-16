# PPG MQTT Realtime System

Implementasi minimal untuk empat alat PPG berbasis Raspberry Pi:

```text
Raspberry Pi / pp2.py
        │
        │ MQTT port 1883
        ▼
Eclipse Mosquitto
        ├── WebSocket port 9001 ──► Frontend realtime
        └── MQTT subscribe ───────► Storage SQLite
```

Tidak ada backend REST pada versi ini. Frontend menerima waveform dan snapshot SI, HRV, BMI, Age, MFCC, Voltage, serta ADC langsung dari broker. Service `storage` hanya menyimpan raw recording dan hasil akhir setelah tombol `Submit` membuat `measurement_id`.

MQTT over WebSocket sudah tersedia pada listener `9001` di `mosquitto/config/mosquitto.conf`. Konfigurasi development memakai `ws://`; TLS untuk `wss://` belum dikonfigurasi di proyek ini.

Dokumentasi handoff untuk tim frontend tersedia di [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md).

## Perilaku tombol

| Kondisi | MQTT realtime | Disimpan SQLite |
|---|---:|---:|
| Belum menekan Start | Tidak | Tidak |
| Start ditekan | Ya, `mode=live` | Tidak |
| Submit ditekan | Ya, `mode=recording` | Ya |
| Pengukuran selesai | Tetap live | Hasil ditutup sebagai `completed` |
| Stop saat merekam | Berhenti | Sesi ditutup sebagai `cancelled` |

Preview dan recording memakai topic `raw` serta `metrics` yang sama; pembeda utamanya adalah `mode` dan `measurement_id`.

## Struktur folder

```text
ppg-mqtt-system/
├── compose.yaml
├── .env.example
├── FRONTEND_INTEGRATION.md       # Handoff untuk tim frontend
├── data/                         # ppg.sqlite3 dibuat di sini
├── mosquitto/config/
│   ├── mosquitto.conf
│   ├── acl
│   └── passwords                # dibuat oleh script, tidak masuk Git
├── scripts/
│   ├── init-broker-users.sh
│   ├── register-device.sh
│   └── remove-device.sh
├── device/
│   ├── mqtt_flow.py
│   ├── pp2_mqtt_app.py
│   ├── simulator.py
│   ├── config.example.json
│   └── PP2_INTEGRATION.md
├── storage/
│   ├── app.py
│   ├── database.py
│   └── Dockerfile
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── tools/
│   ├── list_measurements.py
│   └── export_measurement.py
└── tests/
    └── test_database.py
```

## 1. Persyaratan server

- Linux/VPS atau komputer yang memiliki Docker.
- Docker Compose v2 (`docker compose`).
- Port `1883`, `9001`, dan `8090` tersedia.

Untuk uji LAN:

- `1883`: MQTT Raspberry Pi.
- `9001`: MQTT over WebSocket untuk browser.
- `8090`: halaman frontend.

Jangan membuka port `1883` dan `9001` tanpa TLS ke internet publik untuk penggunaan produksi.

## 2. Siapkan environment

Masuk ke folder proyek:

```bash
cd /path/ke/ppg-mqtt-system
cp .env.example .env
```

Edit `.env`:

```dotenv
COMPOSE_PROJECT_NAME=ppg-mqtt-system
FRONTEND_PORT=8090
STORAGE_PASSWORD=password-storage-yang-kuat
SQLITE_PATH=/data/ppg.sqlite3
TZ=Asia/Jakarta
PUID=1000
PGID=1000
```

Password storage harus sama dengan akun `storage` pada broker. Script berikut akan membuatnya dari `.env`.

Pada Linux, isi `PUID` dan `PGID` dengan:

```bash
id -u
id -g
```

Nilai ini membuat container Mosquitto dapat membaca file password milik user host tanpa membuka permission file tersebut ke semua user.

`COMPOSE_PROJECT_NAME` menjadi prefix container. Dengan nilai default, nama
container akan terlihat seperti:

```text
ppg-mqtt-system-mosquitto-1
ppg-mqtt-system-storage-1
ppg-mqtt-system-frontend-1
```

`FRONTEND_PORT` adalah port pada host dan dapat diganti jika `8090` juga sudah
digunakan. Port di dalam container tetap `80`.

## 3. Buat akun storage dan dashboard

```bash
chmod +x scripts/*.sh
./scripts/init-broker-users.sh
```

Script akan:

1. Membuat akun `storage` menggunakan `STORAGE_PASSWORD`.
2. Meminta password interaktif untuk akun `dashboard`.
3. Membuat `mosquitto/config/passwords`.

Akun `storage` hanya membaca data untuk database. Akun `dashboard` hanya dipakai frontend prototipe.

## 4. Daftarkan Raspberry Pi

Tentukan device ID, misalnya:

```text
PPG-ABC12345
PPG-DEF67890
PPG-12345678
PPG-87654321
```

Daftarkan satu per satu:

```bash
./scripts/register-device.sh PPG-ABC12345
./scripts/register-device.sh PPG-DEF67890
./scripts/register-device.sh PPG-12345678
./scripts/register-device.sh PPG-87654321
```

Setiap perintah meminta password unik. Password tersebut dimasukkan ke `mqtt_config.json` pada Raspberry Pi yang sesuai.

Perangkat yang tidak ada dalam file password akan ditolak broker. Script juga menambahkan ACL khusus sehingga username `PPG-ABC12345` hanya dapat menulis ke hierarchy:

```text
ppg/PPG-ABC12345/...
```

ACL dibuat eksplisit per perangkat. Akun browser `dashboard` tetap read-only dan tidak ikut mendapat hak tulis dari pola wildcard perangkat.

Untuk mencabut alat:

```bash
./scripts/remove-device.sh PPG-ABC12345
docker compose restart mosquitto
```

## 5. Jalankan server

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f mosquitto storage
```

Halaman dashboard:

```text
http://IP_SERVER:8090
```

Jika `FRONTEND_PORT` diubah pada `.env`, gunakan port tersebut pada URL.

Isi:

- Broker host: IP/domain server.
- WebSocket port: `9001`.
- Username: `dashboard`.
- Password: password dashboard.
- Device ID: satu ID tertentu atau `+` untuk melihat semua.

Password dashboard tidak disimpan oleh halaman.

## 6. Konfigurasi Raspberry Pi

Pada Raspberry Pi:

```bash
cd device
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
```

Jalankan launcher dari environment Python yang sudah dapat menjalankan `pp2.py`. Untuk Raspberry Pi OS Desktop, Tkinter biasanya dapat dipasang dengan:

```bash
sudo apt install python3-tk
```

Dependency pengolahan sinyal (`pyserial`, `matplotlib`, `numpy`, `scipy`, dan `librosa`) tetap mengikuti instalasi aplikasi `pp2.py` lama.

Edit `config.json`:

```json
{
  "device_id": "PPG-ABC12345",
  "mqtt_host": "192.168.1.10",
  "mqtt_port": 1883,
  "mqtt_username": "PPG-ABC12345",
  "mqtt_password": "password-alat-ini",
  "sample_period_ms": 10.0,
  "batch_size": 10,
  "metrics_interval_ms": 200,
  "tls": false,
  "ca_file": null
}
```

`device_id` dan `mqtt_username` harus sama dengan akun yang didaftarkan pada broker.

`metrics_interval_ms=200` berarti snapshot metrik dikirim maksimal sekitar 5 kali per detik per alat.

## 7. Uji tanpa Arduino

Simulator menjalankan:

1. Live preview selama 5 detik.
2. Recording selama 10 detik.
3. Mengirim waveform dan metrik realtime.
4. Mengirim result.
5. Disconnect.

```bash
cd device
. .venv/bin/activate
python simulator.py --config config.json
```

Saat simulator berjalan:

- Frontend menampilkan waveform.
- Lima detik pertama tidak masuk SQLite.
- Data setelah sesi dimulai masuk SQLite.
- Hasil akhir tersimpan sebagai `completed`.

## 8. Jalankan `pp2.py` dengan integrasi MQTT

Launcher siap pakai berada di:

```text
device/pp2_mqtt_app.py
```

Launcher mewarisi class dari `pp2.py` asli, sehingga perhitungan sinyal, UI, CSV, dan countdown tetap memakai sumber lama. Hanya method alur MQTT yang dioverride.

Dengan struktur folder saat ini:

```bash
cd device
. .venv/bin/activate
python pp2_mqtt_app.py
```

Jika lokasi `pp2.py` berbeda:

```bash
PP2_SOURCE=/path/ke/pp2.py python pp2_mqtt_app.py
```

Jika lokasi konfigurasi berbeda:

```bash
MQTT_CONFIG=/path/ke/config.json python pp2_mqtt_app.py
```

## 9. Integrasi manual ke `pp2.py`

Panduan perubahan per method tersedia di:

```text
device/PP2_INTEGRATION.md
```

Titik integrasi:

```text
start_serial()     -> mqtt.connect()
serial_reader()    -> mqtt.add_sample(value)
update_*_label()   -> cache nilai SI/HRV/BMI/Age/MFCC/Vol/ADC
root.after()       -> mqtt.publish_metrics(...) tiap 200 ms
submit_height()    -> mqtt.begin_measurement(...)
finish_logging()   -> mqtt.complete_measurement(...)
stop_serial()      -> mqtt.disconnect()
```

File `pp2.py` lama tidak diubah oleh proyek ini.

## 10. Kontrak pesan

### Live preview

Topic:

```text
ppg/PPG-ABC12345/raw
```

Payload:

```json
{
  "device_id": "PPG-ABC12345",
  "measurement_id": null,
  "mode": "live",
  "sequence": 52,
  "captured_at": "2026-07-16T01:00:00.100+00:00",
  "sample_period_ms": 10.0,
  "samples": [512, 518, 525, 531]
}
```

Storage mengabaikan payload ini karena `measurement_id` kosong.

### Metrik realtime

Topic:

```text
ppg/PPG-ABC12345/metrics
```

Payload:

```json
{
  "device_id": "PPG-ABC12345",
  "measurement_id": "83e6f363d30e4cbab507d2db3e628de8",
  "mode": "recording",
  "sequence": 102,
  "captured_at": "2026-07-16T01:01:02.400+00:00",
  "si_m_s": 5.4213,
  "hrv_ms": 42.51,
  "bmi": 22.49,
  "age_years": 30,
  "mfcc": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0],
  "voltage_v": 2.53,
  "adc": 518.0
}
```

Aturan:

- Topic ini QoS 0, tidak retained, dan default maksimal sekitar 5 pesan/detik.
- Nilai yang belum dapat dihitung dikirim sebagai `null`.
- Saat Start sebelum Submit, `mode="live"` dan `measurement_id=null`.
- BMI dan Age tersedia setelah Submit karena berasal dari input pasien.
- SI juga baru dikirim setelah Submit karena perhitungannya membutuhkan tinggi pasien.
- HRV, MFCC, Voltage, dan ADC dapat tersedia pada live preview jika perhitungan alat sudah valid.
- Storage tidak menyimpan setiap snapshot `metrics`; nilai rata-rata akhirnya disimpan melalui `measurement/result`.

### Submit / mulai pengukuran

Topic:

```text
ppg/PPG-ABC12345/measurement/start
```

Payload:

```json
{
  "measurement_id": "83e6f363d30e4cbab507d2db3e628de8",
  "device_id": "PPG-ABC12345",
  "patient_code": "P-001",
  "started_at": "2026-07-16T01:01:00.000+00:00",
  "age": 30,
  "height_cm": 170.0,
  "weight_kg": 65.0,
  "bmi": 22.49,
  "duration_seconds": 300,
  "status": "recording"
}
```

### Raw saat recording

Payload `raw` tetap sama, tetapi:

```json
{
  "measurement_id": "83e6f363d30e4cbab507d2db3e628de8",
  "mode": "recording"
}
```

Storage menyimpan satu baris per batch. Dengan `batch_size=10` dan sample rate 100 Hz, database menerima sekitar 10 batch per detik, bukan 100 baris per detik.

### Hasil akhir

Topic:

```text
ppg/PPG-ABC12345/measurement/result
```

Payload:

```json
{
  "measurement_id": "83e6f363d30e4cbab507d2db3e628de8",
  "device_id": "PPG-ABC12345",
  "finished_at": "2026-07-16T01:06:00.000+00:00",
  "status": "completed",
  "si_mean": 5.42,
  "hrv_mean": 42.51,
  "voltage_mean": 2.53,
  "adc_mean": 518,
  "mfcc_mean": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0]
}
```

## 11. Struktur SQLite

Database berada di:

```text
data/ppg.sqlite3
```

Tabel:

- `devices`: status online/offline terakhir.
- `measurements`: satu baris untuk satu kali Submit.
- `raw_batches`: batch ADC milik measurement.

Kunci utama `raw_batches` adalah `(measurement_id, sequence)`. Jika pesan QoS 1 diterima dua kali, duplikat tidak disimpan.

## 12. Lihat dan ekspor data

Daftar measurement:

```bash
python3 tools/list_measurements.py
```

Contoh output:

```text
ID    DEVICE          PATIENT  STARTED                    STATUS     SAMPLES
...   PPG-ABC12345    P-001    2026-07-16T01:01:00Z       completed  30000
```

Ekspor raw satu measurement menjadi CSV:

```bash
python3 tools/export_measurement.py MEASUREMENT_ID --output hasil.csv
```

## 13. Test lokal

Test database:

```bash
python3 -m unittest discover -s tests -v
```

Pemeriksaan syntax:

```bash
python3 -m compileall device storage tools tests
node --check frontend/app.js
```

## 14. Batas versi minimal ini

- Frontend langsung masuk broker, sehingga cocok untuk prototipe/LAN.
- Belum ada login pengguna aplikasi atau pembatasan pasien per user.
- Belum ada REST API untuk histori.
- Broker belum memakai TLS.

Sebelum penggunaan melalui internet atau untuk data pasien nyata:

1. Gunakan MQTT TLS/WSS.
2. Pasang HTTPS pada frontend.
3. Tambahkan autentikasi pengguna/backend.
4. Terapkan backup dan retensi database.
5. Jangan gunakan nama pasien lengkap sebagai `patient_code`.
