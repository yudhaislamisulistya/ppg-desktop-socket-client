# Frontend Integration Guide — PPG Realtime via MQTT

Dokumen ini adalah kontrak integrasi antara sistem alat PPG dan aplikasi frontend.

Tim frontend tidak perlu memahami serial Arduino, Raspberry Pi, pengolahan sinyal, Mosquitto internal, atau SQLite. Frontend cukup terhubung ke MQTT broker melalui WebSocket, subscribe ke topic perangkat, lalu memproses payload JSON.

Untuk implementasi pertama, fokus pada bagian berikut:

1. Informasi koneksi pada bagian 2.
2. Daftar topic pada bagian 4.
3. Kontrak payload pada bagian 6.
4. Contoh MQTT.js pada bagian 8.
5. Checklist pengujian pada bagian 17.

## 1. Gambaran sistem

```text
Arduino
   │ serial
   ▼
Raspberry Pi / aplikasi PPG
   │ MQTT
   ▼
Mosquitto Broker
   ├── MQTT over WebSocket ──► Frontend realtime
   └── MQTT subscriber ──────► SQLite storage
```

Pada versi saat ini:

- Frontend menerima data realtime langsung dari MQTT broker.
- Frontend tidak membutuhkan backend REST untuk realtime.
- Frontend menggunakan akun MQTT read-only.
- Frontend tidak boleh publish atau mengirim command ke alat.
- Histori SQLite belum tersedia melalui API frontend.

## 2. Informasi yang diberikan tim IoT

Tim frontend akan menerima data berikut dari tim IoT:

| Nama | Contoh development | Keterangan |
|---|---|---|
| MQTT WebSocket URL | `ws://202.141.15.3:9001` | Browser wajib menggunakan `ws://` atau `wss://` |
| MQTT username | `dashboard` | Akun read-only |
| MQTT password | Diberikan terpisah | Jangan disimpan di repository |
| Device ID | `PPG-ABC12345` | Case-sensitive |
| MQTT version | `3.1.1` | `protocolVersion: 4` pada MQTT.js |

Template handoff environment:

```text
Environment       : development / staging / production
MQTT WebSocket URL: ______________________________
MQTT Username     : ______________________________
MQTT Password     : diberikan melalui channel aman
Device IDs        :
- PPG-________________
- PPG-________________
- PPG-________________
- PPG-________________
```

Catatan:

- Halaman HTTP dapat menggunakan `ws://`.
- Halaman HTTPS harus menggunakan `wss://`.
- Browser akan memblokir `ws://` dari halaman HTTPS karena mixed content.
- Browser tidak dapat menggunakan port MQTT TCP `1883` secara langsung.

## 3. Package frontend

Gunakan MQTT.js:

```bash
npm install mqtt@5.15.2
```

MQTT.js dapat digunakan pada React, Vue, Svelte, Next.js client component, atau JavaScript biasa.

## 4. Topic yang tersedia

Untuk satu perangkat:

| Topic | Kegunaan |
|---|---|
| `ppg/{device_id}/status` | Status online/offline alat |
| `ppg/{device_id}/raw` | Batch waveform ADC realtime |
| `ppg/{device_id}/metrics` | Snapshot SI, HRV, BMI, Age, MFCC, Voltage, dan ADC realtime |
| `ppg/{device_id}/measurement/start` | Event saat Submit memulai pengukuran |
| `ppg/{device_id}/measurement/result` | Event hasil selesai atau pembatalan |

Contoh untuk `PPG-ABC12345`:

```text
ppg/PPG-ABC12345/status
ppg/PPG-ABC12345/raw
ppg/PPG-ABC12345/metrics
ppg/PPG-ABC12345/measurement/start
ppg/PPG-ABC12345/measurement/result
```

Wildcard untuk dashboard internal yang melihat semua alat:

```text
ppg/+/status
ppg/+/raw
ppg/+/metrics
ppg/+/measurement/start
ppg/+/measurement/result
```

Untuk halaman detail alat, utamakan subscribe ke satu `device_id`. Jangan subscribe `ppg/+/raw` jika halaman hanya menampilkan satu alat.

## 5. Flow aplikasi

```text
ALAT OFFLINE
    │
    │ status = online
    ▼
ALAT ONLINE
    │
    │ tombol Start pada aplikasi alat
    ▼
LIVE PREVIEW
    │ raw.mode = "live"
    │ metrics.mode = "live"
    │ measurement_id = null
    │ HRV/MFCC/Voltage/ADC dapat tampil realtime
    │
    │ tombol Submit pada aplikasi alat
    ▼
RECORDING
    │ measurement/start
    │ raw.mode = "recording"
    │ metrics.mode = "recording"
    │ measurement_id = ID sesi
    │ SI/HRV/BMI/Age/MFCC/Voltage/ADC tampil realtime
    │
    ├── selesai ──► measurement/result status = "completed"
    │
    └── dibatalkan ──► measurement/result status = "cancelled"
                           │
                           ▼
                       LIVE PREVIEW
```

Tiga state harus dipisahkan pada frontend:

1. **Broker connection state**
   - Browser tersambung atau terputus dari MQTT broker.
2. **Device state**
   - Alat `online` atau `offline`.
3. **Measurement state**
   - `idle`, `live`, `recording`, `completed`, atau `cancelled`.

Browser dapat tersambung ke broker walaupun alat sedang offline.

## 6. Kontrak payload

Semua payload menggunakan JSON UTF-8.

Semua timestamp menggunakan ISO 8601 UTC, misalnya:

```text
2026-07-16T01:00:00.100+00:00
```

### 6.1 Device status

Topic:

```text
ppg/{device_id}/status
```

Alat online:

```json
{
  "device_id": "PPG-ABC12345",
  "state": "online",
  "timestamp": "2026-07-16T01:00:00.000+00:00"
}
```

Alat offline normal:

```json
{
  "device_id": "PPG-ABC12345",
  "state": "offline",
  "timestamp": "2026-07-16T02:00:00.000+00:00",
  "reason": "graceful_disconnect"
}
```

Alat kehilangan koneksi:

```json
{
  "device_id": "PPG-ABC12345",
  "state": "offline",
  "reason": "connection_lost"
}
```

Field:

| Field | Type | Wajib | Keterangan |
|---|---|---:|---|
| `device_id` | `string` | Ya | ID alat |
| `state` | `"online" \| "offline"` | Ya | Status alat |
| `timestamp` | `string` | Tidak | Tidak selalu tersedia pada unexpected disconnect |
| `reason` | `string` | Tidak | Penyebab offline |

Topic status menggunakan retained message. Setelah subscribe, frontend biasanya langsung menerima status terakhir alat.

### 6.2 Raw live preview

Topic:

```text
ppg/{device_id}/raw
```

Payload:

```json
{
  "device_id": "PPG-ABC12345",
  "measurement_id": null,
  "mode": "live",
  "sequence": 52,
  "captured_at": "2026-07-16T01:00:01.100+00:00",
  "sample_period_ms": 10.0,
  "samples": [512.0, 518.0, 525.0, 531.0, 527.0]
}
```

Data ini hanya untuk tampilan realtime dan tidak disimpan oleh storage.

### 6.3 Metrik realtime

Topic:

```text
ppg/{device_id}/metrics
```

Payload recording:

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
  "mfcc": [
    1.0,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    8.0,
    9.0,
    10.0,
    11.0,
    12.0,
    13.0
  ],
  "voltage_v": 2.53,
  "adc": 518.0
}
```

Field:

| Field | Type | Unit | Keterangan |
|---|---|---|---|
| `device_id` | `string` | - | ID alat |
| `measurement_id` | `string \| null` | - | `null` sebelum Submit |
| `mode` | `"live" \| "recording"` | - | State pengukuran saat snapshot dibuat |
| `sequence` | `number` | - | Nomor urut snapshot metrik |
| `captured_at` | `string` | UTC | Waktu snapshot |
| `si_m_s` | `number \| null` | m/s | Stiffness Index |
| `hrv_ms` | `number \| null` | ms | HRV RMSSD |
| `bmi` | `number \| null` | kg/m² | BMI dari input pasien |
| `age_years` | `number \| null` | tahun | Umur dari input pasien |
| `mfcc` | `number[] \| null` | - | Koefisien MFCC, biasanya 13 nilai |
| `voltage_v` | `number \| null` | V | Tegangan hasil konversi ADC |
| `adc` | `number \| null` | - | Nilai ADC terakhir |

Aturan frontend:

- Topic ini adalah sumber utama kartu angka realtime.
- Default publish interval `200 ms`, sekitar 5 pesan/detik per alat.
- QoS 0 dan tidak retained; message lama tidak dikirim ulang saat baru subscribe.
- Field dapat `null` ketika algoritma belum memperoleh nilai yang valid.
- Sebelum Submit, BMI, Age, dan SI bernilai `null`.
- Setelah Submit, semua field mengikuti hasil terbaru yang tersedia dari alat.
- Snapshot ini tidak disimpan satu per satu ke SQLite.

### 6.4 Measurement start

Topic:

```text
ppg/{device_id}/measurement/start
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

`patient_code` adalah kode pasien, bukan nama lengkap pasien.

### 6.5 Raw recording

Topic tetap sama:

```text
ppg/{device_id}/raw
```

Payload:

```json
{
  "device_id": "PPG-ABC12345",
  "measurement_id": "83e6f363d30e4cbab507d2db3e628de8",
  "mode": "recording",
  "sequence": 0,
  "captured_at": "2026-07-16T01:01:00.100+00:00",
  "sample_period_ms": 10.0,
  "samples": [512.0, 518.0, 525.0, 531.0, 527.0]
}
```

Perbedaan live dan recording:

| Field | Live | Recording |
|---|---|---|
| `mode` | `"live"` | `"recording"` |
| `measurement_id` | `null` | ID sesi |
| `sequence` | Sequence live | Dimulai kembali dari `0` per measurement |
| Penyimpanan server | Tidak | Ya |

### 6.6 Measurement result

Topic:

```text
ppg/{device_id}/measurement/result
```

Selesai:

```json
{
  "measurement_id": "83e6f363d30e4cbab507d2db3e628de8",
  "device_id": "PPG-ABC12345",
  "finished_at": "2026-07-16T01:06:00.000+00:00",
  "status": "completed",
  "si_mean": 5.42,
  "hrv_mean": 42.51,
  "voltage_mean": 2.53,
  "adc_mean": 518.0,
  "mfcc_mean": [
    1.0,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    8.0,
    9.0,
    10.0,
    11.0,
    12.0,
    13.0
  ]
}
```

Dibatalkan:

```json
{
  "measurement_id": "83e6f363d30e4cbab507d2db3e628de8",
  "device_id": "PPG-ABC12345",
  "finished_at": "2026-07-16T01:03:00.000+00:00",
  "status": "cancelled",
  "reason": "device_stopped"
}
```

Nilai metrik dapat bernilai `null` jika alat belum dapat menghitung nilai yang valid.

## 7. TypeScript types

```typescript
export type DeviceState = "online" | "offline";
export type RawMode = "live" | "recording";
export type MeasurementResultStatus =
  | "completed"
  | "cancelled"
  | "interrupted";

export interface DeviceStatusPayload {
  device_id: string;
  state: DeviceState;
  timestamp?: string;
  reason?: string;
}

export interface RawPayload {
  device_id: string;
  measurement_id: string | null;
  mode: RawMode;
  sequence: number;
  captured_at: string;
  sample_period_ms: number;
  samples: number[];
}

export interface RealtimeMetricsPayload {
  device_id: string;
  measurement_id: string | null;
  mode: RawMode;
  sequence: number;
  captured_at: string;
  si_m_s: number | null;
  hrv_ms: number | null;
  bmi: number | null;
  age_years: number | null;
  mfcc: number[] | null;
  voltage_v: number | null;
  adc: number | null;
}

export interface MeasurementStartPayload {
  measurement_id: string;
  device_id: string;
  patient_code: string;
  started_at: string;
  age: number;
  height_cm: number;
  weight_kg: number;
  bmi: number;
  duration_seconds: number;
  status: "recording";
}

export interface MeasurementResultPayload {
  measurement_id: string;
  device_id: string;
  finished_at: string;
  status: MeasurementResultStatus;
  reason?: string;
  si_mean?: number | null;
  hrv_mean?: number | null;
  voltage_mean?: number | null;
  adc_mean?: number | null;
  mfcc_mean?: number[] | null;
}
```

## 8. Contoh koneksi MQTT.js

```typescript
import mqtt, { type MqttClient } from "mqtt";

type PpgHandlers = {
  onBrokerState?: (
    state: "connecting" | "connected" | "reconnecting" | "offline" | "error",
  ) => void;
  onDeviceStatus?: (payload: DeviceStatusPayload) => void;
  onRaw?: (payload: RawPayload) => void;
  onMetrics?: (payload: RealtimeMetricsPayload) => void;
  onMeasurementStart?: (payload: MeasurementStartPayload) => void;
  onMeasurementResult?: (payload: MeasurementResultPayload) => void;
  onInvalidMessage?: (topic: string, error: unknown) => void;
};

type PpgConnectionOptions = {
  url: string;
  username: string;
  password: string;
  deviceId: string;
};

export function connectPpgDevice(
  options: PpgConnectionOptions,
  handlers: PpgHandlers,
): MqttClient {
  const fallbackId = Math.random().toString(16).slice(2);
  const randomId = globalThis.crypto?.randomUUID?.() ?? fallbackId;

  handlers.onBrokerState?.("connecting");

  const client = mqtt.connect(options.url, {
    username: options.username,
    password: options.password,
    clientId: `frontend-${randomId}`,
    protocolVersion: 4,
    clean: true,
    keepalive: 30,
    reconnectPeriod: 1000,
    connectTimeout: 10000,
    resubscribe: true,
  });

  const topics = [
    `ppg/${options.deviceId}/status`,
    `ppg/${options.deviceId}/raw`,
    `ppg/${options.deviceId}/metrics`,
    `ppg/${options.deviceId}/measurement/start`,
    `ppg/${options.deviceId}/measurement/result`,
  ];

  client.on("connect", () => {
    handlers.onBrokerState?.("connected");

    client.subscribe(topics, { qos: 1 }, (error) => {
      if (error) {
        handlers.onBrokerState?.("error");
        console.error("MQTT subscribe failed", error);
      }
    });
  });

  client.on("reconnect", () => {
    handlers.onBrokerState?.("reconnecting");
  });

  client.on("offline", () => {
    handlers.onBrokerState?.("offline");
  });

  client.on("error", (error) => {
    handlers.onBrokerState?.("error");
    console.error("MQTT error", error);
  });

  client.on("message", (topic, buffer) => {
    try {
      const payload = JSON.parse(buffer.toString());
      const parts = topic.split("/");
      const topicDeviceId = parts[1];
      const event = parts.slice(2).join("/");

      if (payload.device_id !== topicDeviceId) {
        throw new Error("device_id payload does not match topic");
      }

      if (event === "status") {
        handlers.onDeviceStatus?.(payload as DeviceStatusPayload);
      } else if (event === "raw") {
        handlers.onRaw?.(payload as RawPayload);
      } else if (event === "metrics") {
        handlers.onMetrics?.(payload as RealtimeMetricsPayload);
      } else if (event === "measurement/start") {
        handlers.onMeasurementStart?.(
          payload as MeasurementStartPayload,
        );
      } else if (event === "measurement/result") {
        handlers.onMeasurementResult?.(
          payload as MeasurementResultPayload,
        );
      }
    } catch (error) {
      handlers.onInvalidMessage?.(topic, error);
    }
  });

  return client;
}
```

Penggunaan:

```typescript
const client = connectPpgDevice(
  {
    url: "ws://202.141.15.3:9001",
    username: "dashboard",
    password: runtimeConfig.mqttPassword,
    deviceId: "PPG-ABC12345",
  },
  {
    onBrokerState: setBrokerState,
    onDeviceStatus: (message) => setDeviceState(message.state),
    onRaw: (message) => appendChartSamples(message.samples),
    onMetrics: (message) => {
      setRealtimeMetrics(message);
      setMeasurementId(message.measurement_id);
      setMeasurementState(message.mode);
    },
    onMeasurementStart: (message) => {
      setMeasurementId(message.measurement_id);
      setMeasurementState("recording");
    },
    onMeasurementResult: (message) => {
      setMeasurementState(message.status);
      setLastResult(message);
    },
  },
);

// Saat component unmount atau pindah device:
client.end(true);
```

## 9. Cara menangani waveform

`samples` adalah batch data, bukan satu nilai tunggal.

Contoh:

```typescript
function appendChartSamples(incoming: number[]) {
  chartBuffer.push(...incoming);

  const maxSamples = 1000;
  if (chartBuffer.length > maxSamples) {
    chartBuffer.splice(0, chartBuffer.length - maxSamples);
  }
}
```

Rekomendasi:

- Simpan 500–1.000 sampel terakhir untuk grafik.
- Jangan render ulang komponen React/Vue untuk setiap nilai individual.
- Tambahkan seluruh batch ke buffer, lalu redraw grafik.
- Gunakan `requestAnimationFrame` atau interval render 30–60 FPS.
- Jangan mengasumsikan jumlah item `samples` selalu tetap.
- Jangan menyimpan seluruh raw stream di state global browser.

Dengan konfigurasi default:

```text
sample_period_ms = 10 ms
sample rate       = sekitar 100 Hz
batch_size        = 10 sampel
message rate      = sekitar 10 message/detik per alat
```

`captured_at` adalah waktu ketika batch selesai dikumpulkan. Perkiraan timestamp tiap sampel:

```typescript
function getSampleTimes(message: RawPayload): number[] {
  const lastSampleTime = new Date(message.captured_at).getTime();
  const lastIndex = message.samples.length - 1;

  return message.samples.map(
    (_, index) =>
      lastSampleTime -
      (lastIndex - index) * message.sample_period_ms,
  );
}
```

## 10. Sequence, pesan hilang, dan duplikat

`sequence` digunakan untuk mendeteksi gap atau duplikat.

Aturan:

- Sequence live dan recording adalah stream berbeda.
- Sequence recording dimulai dari `0` untuk setiap `measurement_id`.
- Raw live memakai QoS 0 sehingga paket dapat terlewat.
- Raw recording memakai QoS 1 sehingga paket dapat diterima lebih dari sekali.

Gunakan key stream:

```typescript
const streamKey =
  message.measurement_id === null
    ? `${message.device_id}:live`
    : `${message.device_id}:${message.measurement_id}`;
```

Contoh deduplikasi:

```typescript
const lastSequence = new Map<string, number>();

function acceptRawMessage(message: RawPayload): boolean {
  const key =
    message.measurement_id === null
      ? `${message.device_id}:live`
      : `${message.device_id}:${message.measurement_id}`;

  const previous = lastSequence.get(key);

  if (previous !== undefined && message.sequence <= previous) {
    return false;
  }

  if (
    previous !== undefined &&
    message.sequence > previous + 1
  ) {
    console.warn("PPG sequence gap", {
      deviceId: message.device_id,
      expected: previous + 1,
      received: message.sequence,
    });
  }

  lastSequence.set(key, message.sequence);
  return true;
}
```

Gap pada live preview tidak perlu diminta ulang. Frontend cukup melanjutkan grafik.

Sequence `metrics` berdiri sendiri dari sequence `raw`. Karena QoS 0, gap pada
`metrics` cukup diabaikan dan UI menampilkan snapshot terbaru.

## 11. Kondisi masuk terlambat dan reconnect

Topic `status` bersifat retained, tetapi event berikut tidak retained:

```text
measurement/start
measurement/result
```

Akibatnya, frontend dapat melewatkan event `measurement/start` jika halaman dibuka setelah recording dimulai.

Frontend wajib menggunakan payload `raw` atau `metrics` sebagai sumber state tambahan:

```typescript
function deriveStateFromRaw(message: RawPayload) {
  if (
    message.mode === "recording" &&
    message.measurement_id !== null
  ) {
    setMeasurementState("recording");
    setMeasurementId(message.measurement_id);
  }

  if (
    message.mode === "live" &&
    message.measurement_id === null
  ) {
    setMeasurementState("live");
    setMeasurementId(null);
  }
}
```

Logika yang sama dapat diterapkan pada `RealtimeMetricsPayload` karena field
`mode` dan `measurement_id` memiliki arti yang sama.

Jika frontend terputus lalu tersambung kembali:

1. MQTT.js mencoba reconnect otomatis.
2. Subscription dibuat kembali.
3. Frontend menerima status retained.
4. Payload raw atau metrics berikutnya menentukan apakah alat live atau recording.

Hasil pengukuran yang sudah lewat tidak dapat diminta melalui MQTT realtime. Jika frontend membutuhkan histori, diperlukan REST API tambahan di atas SQLite.

## 12. Rekomendasi state UI

Contoh state minimal:

```typescript
type BrokerState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "offline"
  | "error";

type DeviceUiState = "unknown" | "online" | "offline";

type MeasurementUiState =
  | "idle"
  | "live"
  | "recording"
  | "completed"
  | "cancelled"
  | "interrupted";
```

Rekomendasi tampilan:

| Kondisi | Tampilan |
|---|---|
| Broker reconnecting | Banner “Menghubungkan kembali…” |
| Broker connected, device offline | “Alat offline” |
| Raw `mode=live` | Grafik realtime + label “Live Preview” |
| Metrics `mode=live` | Tampilkan HRV/MFCC/Voltage/ADC yang sudah valid |
| `measurement/start` | Countdown/label “Recording” |
| Raw `mode=recording` | Grafik realtime + measurement ID |
| Metrics `mode=recording` | Perbarui SI/HRV/BMI/Age/MFCC/Voltage/ADC |
| Result `completed` | Tampilkan metrik hasil |
| Result `cancelled` | Tampilkan pengukuran dibatalkan |

Broker `connected` tidak berarti alat `online`.

## 13. Berpindah perangkat

Saat user memilih perangkat lain:

1. Unsubscribe topic perangkat lama, atau tutup client lama.
2. Kosongkan chart buffer.
3. Kosongkan `measurement_id`.
4. Reset sequence tracker.
5. Subscribe topic perangkat baru.

Jangan mencampurkan sampel dari dua `device_id` pada satu chart buffer.

## 14. Error handling

Frontend harus menangani:

- Payload bukan JSON.
- `device_id` payload berbeda dari topic.
- `samples` kosong atau bukan array.
- Nilai metrik `null`.
- Sequence gap.
- Pesan QoS 1 duplikat.
- Broker reconnect.
- Device offline.
- Device ID tidak ditemukan atau salah kapitalisasi.

Validasi minimum raw:

```typescript
function isRawPayload(value: unknown): value is RawPayload {
  if (!value || typeof value !== "object") return false;

  const data = value as Partial<RawPayload>;

  return (
    typeof data.device_id === "string" &&
    (data.measurement_id === null ||
      typeof data.measurement_id === "string") &&
    (data.mode === "live" || data.mode === "recording") &&
    Number.isInteger(data.sequence) &&
    typeof data.captured_at === "string" &&
    typeof data.sample_period_ms === "number" &&
    Array.isArray(data.samples) &&
    data.samples.every((sample) => typeof sample === "number")
  );
}
```

## 15. Keamanan

Kredensial yang digunakan browser pada dasarnya dapat dilihat melalui browser developer tools. Karena itu:

- Gunakan hanya akun `dashboard` read-only.
- Jangan pernah memberikan username/password Raspberry Pi kepada frontend.
- Jangan pernah memberikan akun `storage` kepada frontend.
- Jangan commit password MQTT ke Git.
- Gunakan runtime configuration atau deployment secret injection.
- Gunakan `wss://` untuk production.
- Jangan menggunakan nama pasien lengkap pada topic.
- Jangan menggunakan nama pasien lengkap sebagai `patient_code`.

ACL akun dashboard saat ini hanya mengizinkan read:

```text
ppg/+/status
ppg/+/raw
ppg/+/metrics
ppg/+/measurement/start
ppg/+/measurement/result
```

## 16. Troubleshooting

### Browser tidak dapat connect

Periksa:

- URL memakai `ws://` atau `wss://`.
- Port WebSocket adalah `9001`, bukan `1883`.
- Container Mosquitto berjalan.
- Firewall membuka port WebSocket.
- Username/password dashboard benar.

### Muncul `Not authorized`

Kemungkinan:

- Username/password salah.
- Akun dashboard belum dibuat.
- File ACL belum dimuat ulang.

### MQTT client bisa connect, tetapi tidak ada data

Periksa:

- Device ID benar dan case-sensitive.
- Alat sudah online.
- Tombol Start pada aplikasi alat sudah ditekan.
- Frontend subscribe topic yang benar.
- Untuk kartu metrik, pastikan subscribe `ppg/{device_id}/metrics`.

### HTTPS frontend gagal menggunakan `ws://`

Gunakan `wss://`. Browser memblokir mixed content. Compose saat ini hanya
menyediakan `ws://`; production memerlukan TLS pada Mosquitto atau reverse proxy
WebSocket yang menyediakan `wss://`.

### Salah satu tab memutus tab lain

Pastikan setiap koneksi memiliki `clientId` unik. Jangan menggunakan client ID statis seperti `dashboard`.

### Raw message diterima dua kali

Hal ini dapat terjadi pada QoS 1 ketika recording. Gunakan `(measurement_id, sequence)` untuk deduplikasi.

## 17. Checklist acceptance test

Sebelum integrasi dianggap selesai, uji skenario berikut:

- [ ] Frontend berhasil connect ke WebSocket MQTT.
- [ ] Frontend menerima status retained saat halaman dibuka.
- [ ] Device offline tampil berbeda dari broker disconnected.
- [ ] Tombol Start pada alat menghasilkan raw `mode=live`.
- [ ] Live raw memiliki `measurement_id=null`.
- [ ] Start menghasilkan metrics `mode=live` sekitar 5 pesan/detik.
- [ ] HRV, MFCC, Voltage, dan ADC tampil ketika nilainya valid.
- [ ] BMI, Age, dan SI masih `null` sebelum Submit.
- [ ] Tombol Submit menghasilkan event `measurement/start`.
- [ ] Setelah Submit, SI, HRV, BMI, Age, MFCC, Voltage, dan ADC tampil realtime.
- [ ] Metrics recording memiliki `measurement_id` yang sama dengan event start.
- [ ] Recording raw memiliki `measurement_id` yang sama dengan event start.
- [ ] Recording sequence dimulai dari `0`.
- [ ] Grafik menerima batch `samples`.
- [ ] Hasil selesai menghasilkan status `completed`.
- [ ] Stop saat recording menghasilkan status `cancelled`.
- [ ] Frontend reconnect otomatis setelah jaringan diputus sementara.
- [ ] Frontend dapat masuk ketika recording sudah berjalan.
- [ ] Pindah device tidak mencampur chart buffer.
- [ ] Duplicate sequence tidak ditampilkan dua kali.
- [ ] Frontend tidak dapat publish menggunakan akun dashboard.

## 18. Batas integrasi saat ini

Sudah tersedia:

- Realtime waveform.
- Realtime SI, HRV, BMI, Age, MFCC, Voltage, dan ADC.
- MQTT over WebSocket pada port `9001`.
- Status online/offline.
- Event mulai measurement.
- Event hasil measurement.
- Monitoring empat alat.
- Penyimpanan server-side melalui subscriber SQLite.

Belum tersedia untuk frontend:

- REST API histori.
- Login pengguna aplikasi.
- Otorisasi per user/per device.
- Pengiriman command dari frontend ke alat.
- Token MQTT sementara.

Jika salah satu kebutuhan tersebut ditambahkan, integrasi perlu menggunakan backend gateway atau API tambahan.

## 19. Referensi implementasi

Contoh frontend sederhana:

```text
frontend/index.html
frontend/app.js
frontend/styles.css
```

Kontrak publisher alat:

```text
device/mqtt_flow.py
```

Konfigurasi akses MQTT:

```text
mosquitto/config/acl
mosquitto/config/mosquitto.conf
```
