/* global mqtt, normalizeWaveform */

/* ==========================================================================
   PPG Monitor — dashboard realtime.

   Nilai default diambil dari ppg-desktop/mqtt_config.example.json sehingga
   isian form langsung cocok dengan konfigurasi yang dipakai alat. Sejak
   scripts/register-device.sh memberi ACL "readwrite" pada hierarchy alat,
   kredensial alat pada mqtt_config.json bisa dipakai untuk login di sini dan
   memantau alat itu sendiri.
   ========================================================================== */

// Sesuai ppg-desktop/mqtt_config.example.json.
const CONFIG_EXAMPLE = {
  device_id: "PPG-ABC12345",
  mqtt_host: "mqtt-glucometer.sivia.id",
  mqtt_port: "443",
  mqtt_username: "PPG-ABC12345",
};

const TOPIC_SUFFIXES = [
  "status",
  "raw",
  "metrics",
  "measurement/start",
  "measurement/result",
];

// Simpan 1000 sampel terakhir, sama seperti jendela grafik desktop.
const TRACE_CAPACITY = 1000;
const TRACE_X_MIN = 0;
const TRACE_X_MAX = 1000;
const TRACE_Y_MIN = -200;
const TRACE_Y_MAX = 200;
const TRACE_X_TICKS = [0, 200, 400, 600, 800, 1000];
const TRACE_Y_TICKS = [-200, -100, 0, 100, 200];
const trace = [];

const VITALS = [
  { id: "si", key: "SI", unit: "m/s", channel: "--ch-si", digits: 4 },
  { id: "hrv", key: "HRV", unit: "ms", channel: "--ch-hrv", digits: 2 },
  { id: "bmi", key: "BMI", unit: "kg/m²", channel: "--ch-bmi", digits: 2 },
  { id: "age", key: "Umur", unit: "th", channel: "--ch-age", digits: 0 },
  { id: "volt", key: "Voltase", unit: "V", channel: "--ch-volt", digits: 2 },
  { id: "adc", key: "ADC", unit: "", channel: "--ch-adc", digits: 0 },
];

const RESULT_FIELDS = [
  { key: "si_mean", label: "SI rata-rata", unit: " m/s", digits: 4 },
  { key: "hrv_mean", label: "HRV rata-rata", unit: " ms", digits: 2 },
  { key: "voltage_mean", label: "Voltase rata-rata", unit: " V", digits: 3 },
  { key: "adc_mean", label: "ADC rata-rata", unit: "", digits: 0 },
];

const el = (id) => document.getElementById(id);

const ui = {
  form: el("conn-form"),
  username: el("username"),
  password: el("password"),
  deviceId: el("device-id"),
  connectButton: el("connect-button"),
  connection: el("connection"),
  panelToggle: el("panel-toggle"),
  themeToggle: el("theme-toggle"),
  chipDevice: el("chip-device"),
  chipMode: el("chip-mode"),
  chipModeWrap: el("chip-mode-wrap"),
  lampBroker: el("lamp-broker"),
  lampBrokerText: el("lamp-broker-text"),
  lampDevice: el("lamp-device"),
  lampDeviceText: el("lamp-device-text"),
  alert: el("alert"),
  alertTitle: el("alert-title"),
  alertBody: el("alert-body"),
  session: el("session"),
  sessionLabel: el("session-label"),
  sessionId: el("session-id"),
  sessionTimer: el("session-timer"),
  sessionBar: el("session-bar"),
  chart: el("chart"),
  traceRate: el("trace-rate"),
  traceSeq: el("trace-seq"),
  sampleCount: el("sample-count"),
  mfccBars: el("mfcc-bars"),
  mfccMeta: el("mfcc-meta"),
  mfccValues: el("mfcc-values"),
  linkRows: el("link-rows"),
  linkMeta: el("link-meta"),
  resultStatus: el("result-status"),
  resultGrid: el("result-grid"),
  vitals: el("vitals"),
};

const state = {
  client: null,
  totalSamples: 0,
  totalMessages: 0,
  connectedAt: 0,
  links: new Map(),
  mode: "idle",
  measurementId: null,
  startedAt: null,
  durationSeconds: null,
  deviceState: "unknown",
  alertKey: "",
};

const THEME_STORAGE_KEY = "ppg-monitor-theme";

/* ---------- Bantuan ------------------------------------------------------ */

function formatNumber(value, digits, suffix = "") {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number.toFixed(digits)}${suffix}`;
}

function formatAge(timestamp) {
  if (!timestamp) return "—";
  const seconds = (Date.now() - timestamp) / 1000;
  if (seconds < 1) return "baru saja";
  if (seconds < 60) return `${seconds.toFixed(0)} dtk lalu`;
  return `${Math.floor(seconds / 60)} mnt lalu`;
}

function formatClock(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = String(Math.floor(whole / 60)).padStart(2, "0");
  return `${minutes}:${String(whole % 60).padStart(2, "0")}`;
}

function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function initialTheme() {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch (_error) {
    // Penyimpanan bisa diblokir dalam private mode; preferensi sistem tetap cukup.
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme, persist = true) {
  const selected = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = selected;
  ui.themeToggle.textContent = selected === "light" ? "Tema: Terang" : "Tema: Gelap";
  ui.themeToggle.setAttribute("aria-pressed", String(selected === "light"));
  ui.themeToggle.setAttribute(
    "aria-label",
    selected === "light" ? "Gunakan tema gelap" : "Gunakan tema terang",
  );
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, selected);
    } catch (_error) {
      // Tema tetap berfungsi untuk sesi aktif walaupun storage tidak tersedia.
    }
  }
  drawChart();
}

/* ---------- Form koneksi ------------------------------------------------- */

function resolveWsProtocol(port) {
  // 443/8883 hanya masuk akal lewat TLS (WSS di balik reverse proxy).
  // Selain itu ikuti protokol halaman ini sendiri, mis. ws:// untuk uji LAN
  // langsung ke listener 9001 tanpa TLS.
  if (port === "443" || port === "8883") return "wss";
  return window.location.protocol === "https:" ? "wss" : "ws";
}

/* ---------- Indikator ---------------------------------------------------- */

function setBroker(text, level) {
  ui.lampBrokerText.textContent = text;
  ui.lampBroker.dataset.state = level;
}

function setDeviceLamp(deviceState) {
  state.deviceState = deviceState;
  const map = {
    online: ["daring", "on"],
    offline: ["luring", "bad"],
    waiting: ["menunggu data", "wait"],
    unknown: ["belum diketahui", "unknown"],
  };
  const [text, level] = map[deviceState] || map.unknown;
  ui.lampDeviceText.textContent = text;
  ui.lampDevice.dataset.state = level;
}

function showAlert(key, level, title, body) {
  if (state.alertKey === key) return;
  state.alertKey = key;
  ui.alert.hidden = false;
  ui.alert.dataset.level = level;
  ui.alertTitle.textContent = title;
  ui.alertBody.textContent = body;
}

function hideAlert() {
  state.alertKey = "";
  ui.alert.hidden = true;
}

function setMode(mode, measurementId) {
  state.mode = mode;
  state.measurementId = measurementId || null;
  ui.chipMode.textContent = mode;
  ui.chipModeWrap.dataset.mode = mode;
  ui.session.dataset.state = mode;
  ui.sessionId.textContent = measurementId || "—";

  const labels = {
    idle: "Menunggu data",
    live: "Live preview",
    recording: "Merekam",
    completed: "Selesai",
    cancelled: "Dibatalkan",
  };
  ui.sessionLabel.textContent = labels[mode] || mode;

  if (mode !== "recording") {
    ui.sessionBar.style.width = "0";
    if (mode !== "live") ui.sessionTimer.textContent = "";
  }
}

/* ---------- Rail vital --------------------------------------------------- */

function buildVitals() {
  ui.vitals.innerHTML = "";
  for (const vital of VITALS) {
    const card = document.createElement("article");
    card.className = "vital";
    card.dataset.stale = "true";
    card.style.setProperty("--ch", `var(${vital.channel})`);
    card.innerHTML =
      `<div class="vital-key">${vital.key}</div>` +
      `<div class="vital-row">` +
      `<span class="vital-val" id="vital-${vital.id}">—</span>` +
      (vital.unit ? `<span class="vital-unit">${vital.unit}</span>` : "") +
      `</div>`;
    ui.vitals.append(card);
  }
}

function updateVital(id, value, digits) {
  const node = el(`vital-${id}`);
  if (!node) return;
  const text = formatNumber(value, digits);
  node.textContent = text;
  node.closest(".vital").dataset.stale = String(text === "—");
}

/* ---------- MFCC --------------------------------------------------------- */

function renderMfccDetails(values) {
  ui.mfccValues.replaceChildren();
  if (!Array.isArray(values) || values.length === 0) {
    const empty = document.createElement("div");
    empty.className = "mfcc-values-empty";
    empty.textContent = "Belum ada nilai koefisien.";
    ui.mfccValues.append(empty);
    return;
  }

  values.forEach((raw, index) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    const value = Number(raw);
    term.textContent = `C${String(index + 1).padStart(2, "0")}`;
    detail.textContent = Number.isFinite(value) ? value.toFixed(6) : "—";
    row.append(term, detail);
    ui.mfccValues.append(row);
  });
}

function renderMfcc(values) {
  renderMfccDetails(values);
  if (!Array.isArray(values) || values.length === 0) {
    ui.mfccBars.className = "mfcc-empty";
    ui.mfccBars.textContent = "Menunggu koefisien dari alat";
    ui.mfccMeta.textContent = "menunggu data";
    return;
  }

  const peak = Math.max(...values.map((value) => Math.abs(Number(value) || 0)), 1);
  ui.mfccMeta.textContent = `${values.length} koefisien · puncak ${peak.toFixed(1)}`;

  if (ui.mfccBars.className !== "mfcc") {
    ui.mfccBars.className = "mfcc";
    ui.mfccBars.innerHTML = "";
  }

  while (ui.mfccBars.children.length < values.length) {
    const bar = document.createElement("div");
    bar.className = "mfcc-bar";
    bar.innerHTML = "<i></i><span></span>";
    ui.mfccBars.append(bar);
  }
  while (ui.mfccBars.children.length > values.length) {
    ui.mfccBars.lastElementChild.remove();
  }

  values.forEach((raw, index) => {
    const value = Number(raw) || 0;
    const bar = ui.mfccBars.children[index];
    bar.dataset.sign = value < 0 ? "down" : "up";
    bar.style.setProperty("--h", `${Math.max(2, (Math.abs(value) / peak) * 45)}px`);
    bar.title = `MFCC ${index + 1}: ${value.toFixed(3)}`;
    bar.setAttribute("aria-label", `Koefisien MFCC ${index + 1}: ${value.toFixed(6)}`);
    bar.lastElementChild.textContent = index + 1;
  });
}

/* ---------- Diagnostik langganan ----------------------------------------- */

function resetLinks(deviceId) {
  state.links.clear();
  for (const suffix of TOPIC_SUFFIXES) {
    state.links.set(suffix, {
      topic: `ppg/${deviceId}/${suffix}`,
      grant: "menunggu",
      granted: null,
      count: 0,
      last: 0,
    });
  }
  renderLinks();
}

// Dibangun sebagai node, bukan string HTML: sebagian isinya berasal dari
// broker/alat dan tidak boleh diperlakukan sebagai markup.
function cell(text, className) {
  const node = document.createElement("td");
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function renderLinks() {
  ui.linkRows.replaceChildren();

  if (state.links.size === 0) {
    const row = document.createElement("tr");
    const empty = cell("Belum terhubung ke broker.", "idle");
    empty.colSpan = 4;
    row.append(empty);
    ui.linkRows.append(row);
    return;
  }

  for (const [suffix, link] of state.links) {
    const grantClass =
      link.granted === true ? "grant-ok" : link.granted === false ? "grant-bad" : "idle";
    const row = document.createElement("tr");
    row.append(
      cell(suffix),
      cell(link.grant, grantClass),
      cell(String(link.count)),
      cell(link.count ? formatAge(link.last) : "—"),
    );
    ui.linkRows.append(row);
  }
}

function noteMessage(suffix) {
  const link = state.links.get(suffix);
  if (!link) return;
  link.count += 1;
  link.last = Date.now();
  state.totalMessages += 1;
}

/* ---------- Trace -------------------------------------------------------- */

function resetTrace() {
  trace.length = 0;
  state.totalSamples = 0;
  drawChart();
}

function pushSamples(list) {
  for (const raw of list) {
    const value = Number(raw);
    if (!Number.isFinite(value)) continue;
    trace.push(value);
    state.totalSamples += 1;
  }
  if (trace.length > TRACE_CAPACITY) {
    trace.splice(0, trace.length - TRACE_CAPACITY);
  }
}

function drawChart() {
  const canvas = ui.chart;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width === 0 || height === 0) return;

  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);

  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const plotLeft = width < 520 ? 36 : 42;
  const plotRight = width - 12;
  const plotTop = 12;
  const plotBottom = height - 24;
  const plotWidth = Math.max(1, plotRight - plotLeft);
  const plotHeight = Math.max(1, plotBottom - plotTop);
  const toX = (sample) =>
    plotLeft + ((sample - TRACE_X_MIN) / (TRACE_X_MAX - TRACE_X_MIN)) * plotWidth;
  const toY = (amplitude) =>
    plotBottom -
    ((amplitude - TRACE_Y_MIN) / (TRACE_Y_MAX - TRACE_Y_MIN)) * plotHeight;

  // Graticule dan angka sumbu tetap, sama dengan tampilan desktop.
  ctx.strokeStyle = themeColor("--chart-grid");
  ctx.fillStyle = themeColor("--text-faint");
  ctx.lineWidth = 1;
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textBaseline = "middle";

  for (const amplitude of TRACE_Y_TICKS) {
    const y = Math.round(toY(amplitude)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(plotLeft, y);
    ctx.lineTo(plotRight, y);
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.fillText(String(amplitude), plotLeft - 6, y);
  }

  ctx.textBaseline = "top";
  for (const sample of TRACE_X_TICKS) {
    const x = Math.round(toX(sample)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(x, plotTop);
    ctx.lineTo(x, plotBottom);
    ctx.stroke();

    ctx.textAlign =
      sample === TRACE_X_MIN ? "left" : sample === TRACE_X_MAX ? "right" : "center";
    ctx.fillText(String(sample), x, plotBottom + 5);
  }

  const signal = normalizeWaveform(trace);
  if (signal.length === 0) {
    ctx.fillStyle = themeColor("--chart-empty");
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(
      "menunggu sampel dari alat",
      plotLeft + plotWidth / 2,
      plotTop + plotHeight / 2,
    );
    return;
  }

  ctx.strokeStyle = themeColor("--ch-pleth");
  ctx.lineWidth = 1.6;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.shadowColor = themeColor("--chart-glow");
  ctx.shadowBlur = 7;

  ctx.beginPath();
  for (let i = 0; i < signal.length; i += 1) {
    const x = toX(i);
    const y = toY(signal[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.shadowBlur = 0;

  // Kepala tulis, penanda sampel terbaru.
  const headIndex = signal.length - 1;
  const x = toX(headIndex);
  const y = toY(signal[headIndex]);
  ctx.fillStyle = themeColor("--chart-head");
  ctx.shadowColor = themeColor("--chart-glow");
  ctx.shadowBlur = 11;
  ctx.beginPath();
  ctx.arc(x, y, 2.6, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
}

/* ---------- Hasil -------------------------------------------------------- */

function renderResult(payload) {
  const status = payload.status || "completed";
  ui.resultStatus.textContent = status;
  ui.resultStatus.dataset.status = status;

  // payload.reason berasal dari alat, jadi seluruh sel dirakit lewat
  // textContent agar tidak pernah diparsing sebagai HTML.
  const cells = [];
  for (const field of RESULT_FIELDS) {
    if (payload[field.key] === undefined) continue;
    cells.push([field.label, formatNumber(payload[field.key], field.digits, field.unit)]);
  }
  if (payload.reason) {
    cells.push(["Alasan", String(payload.reason)]);
  }
  if (Array.isArray(payload.mfcc_mean)) {
    cells.push(["MFCC rata-rata", `${payload.mfcc_mean.length} koefisien`]);
  }

  if (cells.length === 0) {
    ui.resultGrid.className = "result-empty";
    ui.resultGrid.textContent = "Sesi ditutup tanpa nilai rata-rata.";
    return;
  }

  ui.resultGrid.className = "result";
  ui.resultGrid.replaceChildren();
  for (const [label, value] of cells) {
    const wrap = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    wrap.append(term, detail);
    ui.resultGrid.append(wrap);
  }
}

/* ---------- Pesan MQTT --------------------------------------------------- */

function handleMessage(topic, buffer) {
  let payload;
  try {
    payload = JSON.parse(buffer.toString());
  } catch (error) {
    console.error("Payload bukan JSON", topic, error);
    return;
  }

  const parts = topic.split("/");
  const deviceId = parts[1];
  const suffix = parts.slice(2).join("/");

  noteMessage(suffix);
  ui.chipDevice.textContent = deviceId;
  hideAlert();

  if (suffix === "status") {
    setDeviceLamp(payload.state === "online" ? "online" : "offline");
    if (payload.state !== "online") setMode("idle", null);
    return;
  }

  if (suffix === "raw") {
    setDeviceLamp("online");
    setMode(payload.mode || "live", payload.measurement_id);
    const samples = Array.isArray(payload.samples) ? payload.samples : [];
    pushSamples(samples);
    if (payload.sample_period_ms > 0) {
      ui.traceRate.textContent = `${Math.round(1000 / payload.sample_period_ms)} Hz`;
    }
    ui.traceSeq.textContent = `seq ${payload.sequence ?? "—"}`;
    ui.sampleCount.textContent = `${state.totalSamples.toLocaleString("id-ID")} sampel`;
    drawChart();
    return;
  }

  if (suffix === "metrics") {
    setDeviceLamp("online");
    setMode(payload.mode || "live", payload.measurement_id);
    updateVital("si", payload.si_m_s, 4);
    updateVital("hrv", payload.hrv_ms, 2);
    updateVital("bmi", payload.bmi, 2);
    updateVital("age", payload.age_years, 0);
    updateVital("volt", payload.voltage_v, 2);
    updateVital("adc", payload.adc, 0);
    renderMfcc(payload.mfcc);
    return;
  }

  if (suffix === "measurement/start") {
    setDeviceLamp("online");
    setMode("recording", payload.measurement_id);
    state.startedAt = Date.parse(payload.started_at) || Date.now();
    state.durationSeconds = Number(payload.duration_seconds) || null;
    ui.resultStatus.textContent = "berjalan";
    ui.resultStatus.dataset.status = "recording";
    return;
  }

  if (suffix === "measurement/result") {
    setMode(payload.status === "cancelled" ? "cancelled" : "completed", null);
    state.startedAt = null;
    state.durationSeconds = null;
    renderResult(payload);
  }
}

/* ---------- Sambung / putus ---------------------------------------------- */

function disconnect() {
  if (state.client) {
    state.client.end(true);
    state.client = null;
  }
  setBroker("terputus", "off");
  setDeviceLamp("unknown");
  setMode("idle", null);
  state.links.clear();
  state.totalMessages = 0;
  renderLinks();
  ui.linkMeta.textContent = "belum terhubung";
  ui.chipDevice.textContent = "—";
  ui.connectButton.textContent = "Hubungkan";
  ui.connectButton.dataset.active = "false";
  ui.connection.hidden = false;
  ui.panelToggle.setAttribute("aria-expanded", "true");
  hideAlert();
}

function connect() {
  const port = CONFIG_EXAMPLE.mqtt_port;
  const host = CONFIG_EXAMPLE.mqtt_host;
  const deviceId = ui.deviceId.value.trim();
  const username = ui.username.value.trim();

  if (!deviceId || !username) {
    showAlert(
      "form",
      "bad",
      "Data koneksi belum lengkap",
      "Device ID dan username wajib diisi.",
    );
    return;
  }
  if (!ui.password.value) {
    showAlert(
      "nopass",
      "bad",
      "Password belum diisi",
      "Gunakan password MQTT yang sesuai dengan username.",
    );
    return;
  }

  const url = `${resolveWsProtocol(port)}://${host}:${port}`;
  const fallbackId = Math.random().toString(16).slice(2);
  const randomId = globalThis.crypto?.randomUUID?.() ?? fallbackId;

  resetTrace();
  resetLinks(deviceId);
  ui.chipDevice.textContent = deviceId;
  setDeviceLamp("waiting");
  setBroker("menghubungkan…", "wait");
  ui.connectButton.textContent = "Putuskan";
  ui.connectButton.dataset.active = "true";

  // clientId wajib unik: clientId yang sama akan saling memutus di broker,
  // dan alat memakai device_id sebagai clientId-nya.
  const client = mqtt.connect(url, {
    username,
    password: ui.password.value,
    clientId: `dashboard-${randomId}`,
    protocolVersion: 4,
    clean: true,
    keepalive: 30,
    reconnectPeriod: 2000,
    connectTimeout: 10000,
    resubscribe: false,
  });
  state.client = client;

  client.on("connect", () => {
    setBroker("terhubung", "on");
    setDeviceLamp("waiting");
    state.connectedAt = Date.now();
    ui.connection.hidden = true;
    ui.panelToggle.setAttribute("aria-expanded", "false");

    const topics = TOPIC_SUFFIXES.map((suffix) => `ppg/${deviceId}/${suffix}`);
    client.subscribe(topics, { qos: 1 }, (error, granted) => {
      if (error) {
        ui.linkMeta.textContent = "subscribe gagal";
        showAlert("suberr", "bad", "Gagal subscribe", String(error.message || error));
        return;
      }

      // qos 128 berarti broker menolak topic tersebut lewat ACL.
      let denied = 0;
      for (const entry of granted || []) {
        const suffix = entry.topic.split("/").slice(2).join("/");
        const link = state.links.get(suffix);
        if (!link) continue;
        const ok = entry.qos !== 128;
        link.granted = ok;
        link.grant = ok ? `qos ${entry.qos}` : "DITOLAK";
        if (!ok) denied += 1;
      }
      ui.linkMeta.textContent = denied
        ? `${denied} dari ${topics.length} topic ditolak`
        : `${topics.length} topic aktif`;
      renderLinks();

      if (denied) {
        showAlert(
          "acl",
          "bad",
          "Broker menolak sebagian langganan",
          "Akun ini tidak punya hak baca. Jalankan " +
            "scripts/upgrade-device-acl.sh " +
            ui.username.value.trim() +
            " lalu docker compose restart mosquitto, atau pakai akun dashboard.",
        );
      }
    });
  });

  client.on("reconnect", () => setBroker("menyambung ulang…", "wait"));
  client.on("offline", () => setBroker("luring", "bad"));
  client.on("close", () => {
    if (state.client) setBroker("terputus", "bad");
  });
  client.on("error", (error) => {
    console.error(error);
    const message = String(error?.message || error);
    setBroker("gagal", "bad");
    showAlert(
      "connerr",
      "bad",
      "Koneksi broker gagal",
      /not authorized|bad user|credentials/i.test(message)
        ? "Username atau password ditolak broker. Periksa mqtt_config.json alat."
        : message,
    );
  });
  client.on("message", handleMessage);
}

/* ---------- Ticker ------------------------------------------------------- */

function tick() {
  renderLinks();

  if (state.mode === "recording" && state.startedAt) {
    const elapsed = (Date.now() - state.startedAt) / 1000;
    if (state.durationSeconds) {
      ui.sessionTimer.textContent = `${formatClock(elapsed)} / ${formatClock(state.durationSeconds)}`;
      const ratio = Math.min(1, elapsed / state.durationSeconds);
      ui.sessionBar.style.width = `${(ratio * 100).toFixed(1)}%`;
    } else {
      ui.sessionTimer.textContent = formatClock(elapsed);
    }
  }

  // Inti keluhan "sudah konek tapi tidak jelas": jelaskan diamnya broker.
  const connected = state.client?.connected;
  if (connected && state.totalMessages === 0 && Date.now() - state.connectedAt > 6000) {
    const denied = [...state.links.values()].some((link) => link.granted === false);
    if (!denied) {
      showAlert(
        "nodata",
        "warn",
        "Terhubung, tetapi alat belum mengirim data",
        `Frontend siap memantau "${ui.deviceId.value.trim()}", tetapi belum ada publish. Pastikan lampu MQTT pada pp2.py berstatus terhubung (bukan menghubungkan/ditolak), lalu periksa Device ID dan mqtt_config.json pada alat.`,
      );
    }
  }
}

/* ---------- Inisialisasi ------------------------------------------------- */

ui.deviceId.value = CONFIG_EXAMPLE.device_id;
ui.username.value = CONFIG_EXAMPLE.mqtt_username;
applyTheme(initialTheme(), false);
buildVitals();
renderMfcc(null);
renderLinks();
setMode("idle", null);
ui.resultGrid.className = "result-empty";
ui.resultGrid.textContent = "Belum ada sesi yang selesai.";

ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.client) disconnect();
  else connect();
});
ui.panelToggle.addEventListener("click", () => {
  const open = ui.connection.hidden;
  ui.connection.hidden = !open;
  ui.panelToggle.setAttribute("aria-expanded", String(open));
});
ui.themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});
window.addEventListener("resize", drawChart);

drawChart();
setInterval(tick, 250);
