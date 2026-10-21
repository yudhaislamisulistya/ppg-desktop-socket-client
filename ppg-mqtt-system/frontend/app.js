/* global mqtt, normalizeWaveform, PREVIEW_MFCC, previewSamples */

const BROKER = {
  host: "mqtt-glucometer.sivia.id",
  port: "443",
};

const MAX_DASHBOARDS = 6;
const PRESET_DEVICE_IDS = ["PPG-001", "PPG-002"];
const DEVICE_ID_PATTERN = /^PPG-[A-Za-z0-9_-]+$/;
const TOPIC_SUFFIXES = [
  "status",
  "raw",
  "metrics",
  "measurement/start",
  "measurement/result",
  "history/response",
];

const TRACE_CAPACITY = 1000;
const TRACE_X_MIN = 0;
const TRACE_X_MAX = 1000;
const TRACE_Y_MIN = -200;
const TRACE_Y_MAX = 200;
const TRACE_X_TICKS = [0, 200, 400, 600, 800, 1000];
const TRACE_Y_TICKS = [-200, -100, 0, 100, 200];

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

const THEME_STORAGE_KEY = "ppg-monitor-theme";
const dashboards = new Map();
let previewDashboard = null;
let previewTimer = null;

const el = (id) => document.getElementById(id);
const page = {
  form: el("conn-form"),
  connection: el("connection"),
  previewConnect: el("preview-connect"),
  previewButton: el("preview-button"),
  previewNotice: el("preview-notice"),
  username: el("username"),
  password: el("password"),
  deviceId: el("device-id"),
  connectButton: el("connect-button"),
  themeToggle: el("theme-toggle"),
  chipDevice: el("chip-device"),
  chipMode: el("chip-mode"),
  chipModeWrap: el("chip-mode-wrap"),
  lampBroker: el("lamp-broker"),
  lampBrokerText: el("lamp-broker-text"),
  alert: el("alert"),
  alertTitle: el("alert-title"),
  alertBody: el("alert-body"),
  grid: el("dashboard-grid"),
  empty: el("dashboard-empty"),
  template: el("device-dashboard-template"),
  historyPanel: el("history-panel"),
  historyButton: el("history-button"),
  dashboardButton: el("dashboard-button"),
  completion: el("recording-complete"),
  completionMessage: el("recording-complete-message"),
  completionOpen: el("recording-complete-open"),
  presets: el("device-presets"),
};
let lastCompletedDevice = null;

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

function resolveWsProtocol(port) {
  if (port === "443" || port === "8883") return "wss";
  return window.location.protocol === "https:" ? "wss" : "ws";
}

function initialTheme() {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch (_error) {
    // Preferensi sistem masih cukup ketika storage browser diblokir.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme, persist = true) {
  const selected = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = selected;
  page.themeToggle.textContent = selected === "light" ? "Tema: Terang" : "Tema: Gelap";
  page.themeToggle.setAttribute("aria-pressed", String(selected === "light"));
  page.themeToggle.setAttribute(
    "aria-label",
    selected === "light" ? "Gunakan tema gelap" : "Gunakan tema terang",
  );
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, selected);
    } catch (_error) {
      // Tema tetap diterapkan pada sesi aktif.
    }
  }
  dashboards.forEach((dashboard) => dashboard.drawChart());
  previewDashboard?.drawChart();
}

function showPageAlert(level, title, body) {
  page.alert.hidden = false;
  page.alert.dataset.level = level;
  page.alertTitle.textContent = title;
  page.alertBody.textContent = body;
}

function hidePageAlert() {
  page.alert.hidden = true;
}

function showView(view) {
  const isHistory = view === "history";
  page.grid.hidden = isHistory;
  page.historyPanel.hidden = !isHistory;
  page.previewButton.hidden = isHistory;
  page.dashboardButton.setAttribute("aria-pressed", String(!isHistory));
  page.historyButton.setAttribute("aria-pressed", String(isHistory));
  if (isHistory) {
    stopPreview();
    updateSummary();
  } else {
    dashboards.forEach((dashboard) => dashboard.drawChart());
  }
}

function stopPreview() {
  clearInterval(previewTimer);
  previewTimer = null;
  previewDashboard?.destroy();
  previewDashboard = null;
}

function togglePreview() {
  if (dashboards.size > 0) return;
  if (previewDashboard) {
    stopPreview();
  } else {
    previewDashboard = new DeviceDashboard({ deviceId: "PPG-DEMO", preview: true });
    previewTimer = setInterval(() => {
      if (!document.hidden) previewDashboard?.advancePreview();
    }, 100);
  }
  updateSummary();
}

function updateSummary() {
  const connected = [...dashboards.values()].filter(
    (dashboard) => dashboard.client?.connected,
  ).length;
  page.chipDevice.textContent = `${dashboards.size} / ${MAX_DASHBOARDS}`;
  page.chipMode.textContent = String(connected);
  page.chipModeWrap.dataset.mode = connected ? "live" : "idle";

  if (connected) {
    page.lampBroker.dataset.state = "on";
    page.lampBrokerText.textContent = `${connected} perangkat`;
  } else if (dashboards.size) {
    page.lampBroker.dataset.state = "wait";
    page.lampBrokerText.textContent = "menghubungkan…";
  } else {
    page.lampBroker.dataset.state = "off";
    page.lampBrokerText.textContent = "belum ada koneksi";
  }

  if (dashboards.size > 0 && previewDashboard) stopPreview();
  const previewVisible = Boolean(previewDashboard);
  page.empty.hidden = dashboards.size !== 0 || previewVisible;
  page.previewNotice.hidden = !previewVisible;
  page.previewButton.textContent = previewVisible ? "Tutup preview" : "Preview";
  page.previewButton.setAttribute("aria-expanded", String(previewVisible));
  page.previewButton.disabled = dashboards.size > 0;
  page.previewButton.title = dashboards.size > 0
    ? "Putuskan seluruh panel perangkat untuk membuka preview."
    : "Tampilkan atau tutup dashboard dengan data simulasi.";
  page.connectButton.disabled = dashboards.size >= MAX_DASHBOARDS;
  page.presets?.querySelectorAll("[data-preset]").forEach((button) => {
    const dashboard = dashboards.get(button.dataset.preset);
    const connected = Boolean(dashboard?.client?.connected);
    const connecting = dashboard?.node.dataset.state === "wait";
    button.dataset.state = connected ? "connected" : connecting ? "connecting" : "idle";
    button.querySelector("span").textContent = connected ? "Broker terhubung" : connecting ? "Menghubungkan…" : "Belum terhubung";
    button.setAttribute("aria-label", `${dashboard ? "Buka" : "Hubungkan"} ${button.dataset.preset}`);
  });
}

function drawWaveform(canvas, trace) {
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
  signal.forEach((value, index) => {
    const x = toX(index);
    const y = toY(value);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.shadowBlur = 0;

  const headIndex = signal.length - 1;
  ctx.fillStyle = themeColor("--chart-head");
  ctx.shadowColor = themeColor("--chart-glow");
  ctx.shadowBlur = 11;
  ctx.beginPath();
  ctx.arc(toX(headIndex), toY(signal[headIndex]), 2.6, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
}

function tableCell(text, className) {
  const node = document.createElement("td");
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

class DeviceDashboard {
  constructor({ deviceId, username, password, preview = false }) {
    this.deviceId = deviceId;
    this.username = username;
    this.preview = preview;
    this.historyRequests = new Map();
    this.client = null;
    this.closed = false;
    this.trace = [];
    this.totalSamples = 0;
    this.totalMessages = 0;
    this.connectedAt = 0;
    this.links = new Map();
    this.mode = "idle";
    this.startedAt = null;
    this.durationSeconds = null;
    this.alertKey = "";

    this.node = page.template.content.firstElementChild.cloneNode(true);
    this.node.dataset.deviceId = deviceId;
    this.ui = {};
    this.node.querySelectorAll("[data-role]").forEach((node) => {
      this.ui[node.dataset.role] = node;
    });
    this.ui["device-name"].textContent = deviceId;
    this.ui.remove.addEventListener("click", () => removeDashboard(deviceId));
    this.ui["result-history"].addEventListener("click", () => history.open(deviceId));

    page.grid.append(this.node);
    this.buildVitals();
    this.resetLinks();
    this.renderMfcc(null);
    this.renderResult(null);
    this.setMode("idle", null);
    this.drawChart();
    if (preview) this.startPreview();
    else this.connect(password);
  }

  startPreview() {
    this.node.dataset.preview = "true";
    this.node.dataset.state = "preview";
    this.node.setAttribute("aria-label", "Pratinjau perangkat dengan data simulasi");
    this.ui["device-caption"].textContent = "Pratinjau perangkat";
    this.ui["broker-lamp"].hidden = true;
    this.ui.remove.hidden = true;
    this.ui["device-more"].hidden = true;
    this.ui["device-text"].textContent = "Data simulasi";
    this.ui["device-lamp"].dataset.state = "preview";
    this.ui.chart.setAttribute("aria-label", "Pratinjau waveform PPG menggunakan data simulasi");
    this.setMode("preview", "Tidak direkam atau disimpan");
    this.ui["trace-rate"].textContent = "100 Hz";
    this.renderMfcc(PREVIEW_MFCC);
    const values = [6.2841, 42.6, 22.49, 28, 1.65, 2048];
    VITALS.forEach((vital, index) => this.updateVital(vital.id, values[index], vital.digits));
    this.pushSamples(previewSamples(0, TRACE_CAPACITY));
    this.renderPreviewTrace();
    this.previewPaused = Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
    this.ui["preview-toggle"].hidden = false;
    this.ui["preview-toggle"].addEventListener("click", () => {
      this.previewPaused = !this.previewPaused;
      this.renderPreviewControl();
    });
    this.renderPreviewControl();
  }

  renderPreviewControl() {
    this.ui["preview-toggle"].textContent = this.previewPaused ? "Lanjutkan pratinjau" : "Jeda pratinjau";
    this.ui["preview-toggle"].setAttribute("aria-pressed", String(this.previewPaused));
  }

  renderPreviewTrace() {
    this.ui["trace-seq"].textContent = `seq ${Math.floor(this.totalSamples / 10)}`;
    this.ui["sample-count"].textContent = `${this.trace.length.toLocaleString("id-ID")} sampel`;
    this.drawChart();
  }

  advancePreview() {
    if (this.previewPaused || this.closed) return;
    this.pushSamples(previewSamples(this.totalSamples, 10));
    this.renderPreviewTrace();
  }

  setBroker(text, level) {
    this.ui["broker-text"].textContent = text;
    this.ui["broker-lamp"].dataset.state = level;
    this.node.dataset.state = level === "on" ? "connected" : level;
    updateSummary();
  }

  setDeviceLamp(deviceState) {
    const map = {
      online: ["daring", "on"],
      offline: ["luring", "bad"],
      waiting: ["menunggu data", "wait"],
      unknown: ["belum diketahui", "unknown"],
    };
    const [text, level] = map[deviceState] || map.unknown;
    this.ui["device-text"].textContent = text;
    this.ui["device-lamp"].dataset.state = level;
  }

  showAlert(key, level, title, body) {
    if (this.alertKey === key) return;
    this.alertKey = key;
    this.ui.alert.hidden = false;
    this.ui.alert.dataset.level = level;
    this.ui["alert-title"].textContent = title;
    this.ui["alert-body"].textContent = body;
  }

  hideAlert() {
    this.alertKey = "";
    this.ui.alert.hidden = true;
  }

  setMode(mode, measurementId) {
    this.mode = mode;
    this.ui.session.dataset.state = mode;
    this.ui["session-id"].textContent = measurementId || "—";
    const labels = {
      idle: "Menunggu data",
      live: "Data langsung",
      preview: "Simulasi sinyal PPG",
      recording: "Merekam",
      completed: "Selesai",
      cancelled: "Dibatalkan",
    };
    this.ui["session-label"].textContent = labels[mode] || mode;
    if (mode !== "recording") {
      this.ui["session-bar"].style.width = "0";
      if (mode !== "live") this.ui["session-timer"].textContent = "";
    }
  }

  buildVitals() {
    this.ui.vitals.replaceChildren();
    VITALS.forEach((vital) => {
      const card = document.createElement("article");
      card.className = "vital";
      card.dataset.stale = "true";
      card.dataset.vital = vital.id;
      card.style.setProperty("--ch", `var(${vital.channel})`);

      const key = document.createElement("div");
      key.className = "vital-key";
      key.textContent = vital.key;
      const row = document.createElement("div");
      row.className = "vital-row";
      const value = document.createElement("span");
      value.className = "vital-val";
      value.textContent = "—";
      row.append(value);
      if (vital.unit) {
        const unit = document.createElement("span");
        unit.className = "vital-unit";
        unit.textContent = vital.unit;
        row.append(unit);
      }
      card.append(key, row);
      this.ui.vitals.append(card);
    });
  }

  updateVital(id, value, digits) {
    const card = this.ui.vitals.querySelector(`[data-vital="${id}"]`);
    if (!card) return;
    const text = formatNumber(value, digits);
    card.querySelector(".vital-val").textContent = text;
    card.dataset.stale = String(text === "—");
  }

  renderMfccDetails(values) {
    this.ui["mfcc-values"].replaceChildren();
    if (!Array.isArray(values) || values.length === 0) {
      const empty = document.createElement("div");
      empty.className = "mfcc-values-empty";
      empty.textContent = "Belum ada nilai koefisien.";
      this.ui["mfcc-values"].append(empty);
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
      this.ui["mfcc-values"].append(row);
    });
  }

  renderMfcc(values) {
    this.renderMfccDetails(values);
    const bars = this.ui["mfcc-bars"];
    if (!Array.isArray(values) || values.length === 0) {
      bars.className = "mfcc-empty";
      bars.textContent = "Menunggu koefisien dari alat";
      this.ui["mfcc-meta"].textContent = "menunggu data";
      return;
    }

    const peak = Math.max(...values.map((value) => Math.abs(Number(value) || 0)), 1);
    this.ui["mfcc-meta"].textContent =
      `${values.length} koefisien · puncak ${peak.toFixed(1)}`;
    if (bars.className !== "mfcc") {
      bars.className = "mfcc";
      bars.replaceChildren();
    }
    while (bars.children.length < values.length) {
      const bar = document.createElement("div");
      bar.className = "mfcc-bar";
      bar.innerHTML = "<i></i><span></span>";
      bars.append(bar);
    }
    while (bars.children.length > values.length) bars.lastElementChild.remove();

    values.forEach((raw, index) => {
      const value = Number(raw) || 0;
      const bar = bars.children[index];
      bar.dataset.sign = value < 0 ? "down" : "up";
      bar.style.setProperty("--h", `${Math.max(2, (Math.abs(value) / peak) * 45)}px`);
      bar.title = `MFCC ${index + 1}: ${value.toFixed(3)}`;
      bar.setAttribute("aria-label", `Koefisien MFCC ${index + 1}: ${value.toFixed(6)}`);
      bar.lastElementChild.textContent = index + 1;
    });
  }

  resetLinks() {
    this.links.clear();
    TOPIC_SUFFIXES.forEach((suffix) => {
      this.links.set(suffix, {
        topic: suffix === "history/response" ? this.historyResponseTopic || `ppg/${this.deviceId}/history/response/#`
          : `ppg/${this.deviceId}/${suffix}`,
        grant: "menunggu",
        granted: null,
        count: 0,
        last: 0,
      });
    });
    this.renderLinks();
  }

  renderLinks() {
    this.ui["link-rows"].replaceChildren();
    this.links.forEach((link, suffix) => {
      const grantClass =
        link.granted === true ? "grant-ok" : link.granted === false ? "grant-bad" : "idle";
      const row = document.createElement("tr");
      row.append(
        tableCell(suffix),
        tableCell(link.grant, grantClass),
        tableCell(String(link.count)),
        tableCell(link.count ? formatAge(link.last) : "—"),
      );
      this.ui["link-rows"].append(row);
    });
  }

  noteMessage(suffix) {
    const link = this.links.get(suffix);
    if (!link) return;
    link.count += 1;
    link.last = Date.now();
    this.totalMessages += 1;
  }

  pushSamples(list) {
    list.forEach((raw) => {
      const value = Number(raw);
      if (!Number.isFinite(value)) return;
      this.trace.push(value);
      this.totalSamples += 1;
    });
    if (this.trace.length > TRACE_CAPACITY) {
      this.trace.splice(0, this.trace.length - TRACE_CAPACITY);
    }
  }

  drawChart() {
    drawWaveform(this.ui.chart, this.trace);
  }

  renderResult(payload) {
    this.ui["result-history"].hidden = this.preview || !payload?.measurement_id
      || (payload.status || "completed") !== "completed";
    if (!payload) {
      this.ui["result-status"].textContent = "belum ada";
      this.ui["result-grid"].className = "result-empty";
      this.ui["result-grid"].textContent = "Belum ada sesi yang selesai.";
      return;
    }

    const status = payload.status || "completed";
    this.ui["result-status"].textContent = status;
    this.ui["result-status"].dataset.status = status;
    const cells = [];
    RESULT_FIELDS.forEach((field) => {
      if (payload[field.key] === undefined) return;
      cells.push([field.label, formatNumber(payload[field.key], field.digits, field.unit)]);
    });
    if (payload.reason) cells.push(["Alasan", String(payload.reason)]);
    if (Array.isArray(payload.mfcc_mean)) {
      cells.push(["MFCC rata-rata", `${payload.mfcc_mean.length} koefisien`]);
    }

    if (cells.length === 0) {
      this.ui["result-grid"].className = "result-empty";
      this.ui["result-grid"].textContent = "Sesi ditutup tanpa nilai rata-rata.";
      return;
    }

    this.ui["result-grid"].className = "result";
    this.ui["result-grid"].replaceChildren();
    cells.forEach(([label, value]) => {
      const wrap = document.createElement("div");
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = label;
      detail.textContent = value;
      wrap.append(term, detail);
      this.ui["result-grid"].append(wrap);
    });
  }

  handleMessage(topic, buffer) {
    let payload;
    try {
      payload = JSON.parse(buffer.toString());
    } catch (error) {
      console.error("Payload bukan JSON", topic, error);
      return;
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;

    const parts = topic.split("/");
    const deviceId = parts[1];
    const suffix = parts.slice(2).join("/");
    if (deviceId !== this.deviceId) return;

    if (topic === this.historyResponseTopic) {
      this.noteMessage("history/response");
      const pending = this.historyRequests.get(payload.request_id);
      if (!pending) return;
      this.historyRequests.delete(payload.request_id);
      clearTimeout(pending.timer);
      if (payload.ok === true) pending.resolve(payload.data);
      else pending.reject(new Error(String(payload.error || "Permintaan History gagal.")));
      return;
    }

    this.noteMessage(suffix);
    this.hideAlert();
    if (suffix === "status") {
      this.setDeviceLamp(payload.state === "online" ? "online" : "offline");
      if (payload.state !== "online") this.setMode("idle", null);
      return;
    }

    if (suffix === "raw") {
      this.setDeviceLamp("online");
      this.setMode(payload.mode || "live", payload.measurement_id);
      this.pushSamples(Array.isArray(payload.samples) ? payload.samples : []);
      if (payload.sample_period_ms > 0) {
        this.ui["trace-rate"].textContent =
          `${Math.round(1000 / payload.sample_period_ms)} Hz`;
      }
      this.ui["trace-seq"].textContent = `seq ${payload.sequence ?? "—"}`;
      this.ui["sample-count"].textContent =
        `${this.totalSamples.toLocaleString("id-ID")} sampel`;
      this.drawChart();
      return;
    }

    if (suffix === "metrics") {
      this.setDeviceLamp("online");
      this.setMode(payload.mode || "live", payload.measurement_id);
      this.updateVital("si", payload.si_m_s, 4);
      this.updateVital("hrv", payload.hrv_ms, 2);
      this.updateVital("bmi", payload.bmi, 2);
      this.updateVital("age", payload.age_years, 0);
      this.updateVital("volt", payload.voltage_v, 2);
      this.updateVital("adc", payload.adc, 0);
      this.renderMfcc(payload.mfcc);
      return;
    }

    if (suffix === "measurement/start") {
      this.setDeviceLamp("online");
      this.setMode("recording", payload.measurement_id);
      this.startedAt = Date.parse(payload.started_at) || Date.now();
      this.durationSeconds = Number(payload.duration_seconds) || null;
      this.ui["result-status"].textContent = "berjalan";
      this.ui["result-status"].dataset.status = "recording";
      return;
    }

    if (suffix === "measurement/result") {
      this.setMode(payload.status === "cancelled" ? "cancelled" : "completed", null);
      this.startedAt = null;
      this.durationSeconds = null;
      this.renderResult(payload);
      if ((payload.status || "completed") === "completed" && payload.measurement_id && !this.preview) {
        lastCompletedDevice = this.deviceId;
        history.notifyCompleted(this.deviceId, payload.measurement_id);
        page.completion.hidden = false;
        page.completionMessage.textContent = `${this.deviceId}: perekaman selesai. Buka History untuk melihat hasil dan mengisi label opsional.`;
      }
    }
  }

  requestHistory(action, parameters = {}) {
    if (this.preview || !this.client?.connected || !this.historyClientId) {
      return Promise.reject(new Error("Koneksi broker belum aktif. Hubungkan perangkat atau tunggu koneksi pulih."));
    }
    if (this.links.get("history/response")?.granted === false) {
      return Promise.reject(new Error("Izin History ditolak. ACL broker perlu diperbarui."));
    }
    if (this.historyRequests.size >= 20) return Promise.reject(new Error("Tunggu permintaan History sebelumnya selesai."));
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return new Promise((resolve, reject) => {
      const fail = (error) => {
        const pending = this.historyRequests.get(requestId);
        if (!pending) return;
        clearTimeout(pending.timer);
        this.historyRequests.delete(requestId);
        reject(error);
      };
      const timer = setTimeout(() => fail(new Error("History belum merespons. Periksa service storage dan izin History broker, lalu coba lagi.")), 10000);
      this.historyRequests.set(requestId, { resolve, reject, timer });
      try {
        this.client.publish(`ppg/${this.deviceId}/history/request`, JSON.stringify({
          ...parameters, action, device_id: this.deviceId, client_id: this.historyClientId, request_id: requestId,
        }), { qos: 1, retain: false }, (error) => { if (error) fail(error); });
      } catch (error) {
        fail(error);
      }
    });
  }

  rejectHistoryRequests() {
    this.historyRequests.forEach((pending) => {
      clearTimeout(pending.timer);
      pending.reject(new Error("Koneksi perangkat terputus. Hubungkan kembali untuk membuka History."));
    });
    this.historyRequests.clear();
  }

  connect(password) {
    const url = `${resolveWsProtocol(BROKER.port)}://${BROKER.host}:${BROKER.port}`;
    const fallbackId = Math.random().toString(16).slice(2);
    const randomId = globalThis.crypto?.randomUUID?.() ?? fallbackId;
    this.historyClientId = `dashboard-${randomId}`;
    this.historyResponseTopic = `ppg/${this.deviceId}/history/response/${this.historyClientId}`;
    this.resetLinks();
    this.setDeviceLamp("waiting");
    this.setBroker("menghubungkan…", "wait");

    const client = mqtt.connect(url, {
      username: this.username,
      password,
      clientId: this.historyClientId,
      protocolVersion: 4,
      clean: true,
      keepalive: 30,
      reconnectPeriod: 2000,
      connectTimeout: 10000,
      resubscribe: false,
    });
    this.client = client;

    client.on("connect", () => {
      if (this.closed || this.client !== client) return;
      this.setBroker("terhubung", "on");
      this.setDeviceLamp("waiting");
      this.connectedAt = Date.now();
      const topics = [...this.links.values()].map((link) => link.topic);
      client.subscribe(topics, { qos: 1 }, (error, granted) => {
        if (error) {
          this.ui["link-meta"].textContent = "subscribe gagal";
          this.showAlert("suberr", "bad", "Gagal subscribe", String(error.message || error));
          return;
        }

        let denied = 0;
        (granted || []).forEach((entry) => {
          const suffix = entry.topic === this.historyResponseTopic ? "history/response"
            : entry.topic.split("/").slice(2).join("/");
          const link = this.links.get(suffix);
          if (!link) return;
          const ok = entry.qos !== 128;
          link.granted = ok;
          link.grant = ok ? `qos ${entry.qos}` : "DITOLAK";
          if (!ok) denied += 1;
        });
        this.ui["link-meta"].textContent = denied
          ? `${denied} dari ${topics.length} topic ditolak`
          : `${topics.length} topic aktif`;
        this.renderLinks();
        if (denied) {
          this.showAlert(
            "acl",
            "bad",
            "Broker menolak sebagian langganan",
            `Username ${this.username} tidak memiliki hak baca untuk ${this.deviceId}.`,
          );
        }
        if (!page.historyPanel.hidden && el("history-device").value === this.deviceId) history.load();
      });
    });

    client.on("reconnect", () => {
      if (!this.closed) this.setBroker("menyambung ulang…", "wait");
    });
    client.on("offline", () => {
      if (!this.closed) this.setBroker("luring", "bad");
    });
    client.on("close", () => {
      this.rejectHistoryRequests();
      if (!this.closed && this.client === client) this.setBroker("terputus", "bad");
    });
    client.on("error", (error) => {
      if (this.closed) return;
      const message = String(error?.message || error);
      console.error(error);
      this.setBroker("gagal", "bad");
      this.showAlert(
        "connerr",
        "bad",
        "Koneksi broker gagal",
        /not authorized|bad user|credentials/i.test(message)
          ? "Username atau password ditolak broker."
          : message,
      );
    });
    client.on("message", (topic, buffer) => this.handleMessage(topic, buffer));
  }

  tick() {
    this.renderLinks();
    if (this.mode === "recording" && this.startedAt) {
      const elapsed = (Date.now() - this.startedAt) / 1000;
      if (this.durationSeconds) {
        this.ui["session-timer"].textContent =
          `${formatClock(elapsed)} / ${formatClock(this.durationSeconds)}`;
        this.ui["session-bar"].style.width =
          `${(Math.min(1, elapsed / this.durationSeconds) * 100).toFixed(1)}%`;
      } else {
        this.ui["session-timer"].textContent = formatClock(elapsed);
      }
    }

    if (
      this.client?.connected &&
      this.totalMessages === 0 &&
      Date.now() - this.connectedAt > 6000
    ) {
      const denied = [...this.links.values()].some((link) => link.granted === false);
      if (!denied) {
        this.showAlert(
          "nodata",
          "warn",
          "Terhubung, tetapi alat belum mengirim data",
          `Frontend siap memantau ${this.deviceId}. Pastikan aplikasi alat sedang berjalan dan Device ID-nya sama.`,
        );
      }
    }
  }

  destroy() {
    this.closed = true;
    this.rejectHistoryRequests();
    const client = this.client;
    this.client = null;
    if (client) client.end(true);
    this.node.remove();
  }
}

function removeDashboard(deviceId) {
  const dashboard = dashboards.get(deviceId);
  if (!dashboard) return;
  dashboards.delete(deviceId);
  dashboard.destroy();
  history.syncDevices();
  if (lastCompletedDevice === deviceId) page.completion.hidden = true;
  updateSummary();
  hidePageAlert();
}

function connectPreset(deviceId) {
  if (!PRESET_DEVICE_IDS.includes(deviceId)) return;
  if (dashboards.has(deviceId)) {
    if (!page.historyPanel.hidden) history.open(deviceId);
    else {
      showView("dashboard");
      dashboards.get(deviceId).node.scrollIntoView({ block: "start" });
    }
    return;
  }
  const authenticated = [...dashboards.values()].find((dashboard) =>
    PRESET_DEVICE_IDS.includes(dashboard.deviceId) && dashboard.username === dashboard.deviceId
      && dashboard.client?.connected && typeof dashboard.client.options?.password === "string");
  if (authenticated) {
    addDashboard({ deviceId, username: deviceId, password: authenticated.client.options.password });
    return;
  }
  page.deviceId.value = deviceId;
  page.username.value = deviceId;
  page.username.dataset.auto = "true";
  page.password.value = "";
  page.connection.open = true;
  page.password.focus();
  page.connection.scrollIntoView({ block: "center" });
}

function addDashboard(credentials) {
  const deviceId = (credentials?.deviceId ?? page.deviceId.value).trim();
  const username = (credentials?.username ?? page.username.value).trim();
  const password = credentials?.password ?? page.password.value;

  if (!DEVICE_ID_PATTERN.test(deviceId)) {
    showPageAlert(
      "bad",
      "Device ID tidak valid",
      "Gunakan format PPG- diikuti huruf, angka, _ atau -.",
    );
    return;
  }
  if (!username || !password) {
    showPageAlert(
      "bad",
      "Kredensial belum lengkap",
      "Username dan password MQTT wajib diisi.",
    );
    return;
  }
  if (dashboards.has(deviceId)) {
    showPageAlert(
      "warn",
      "Perangkat sudah ditampilkan",
      `${deviceId} sudah memiliki dashboard aktif.`,
    );
    return;
  }
  if (dashboards.size >= MAX_DASHBOARDS) {
    showPageAlert(
      "warn",
      "Batas dashboard tercapai",
      `Putuskan salah satu perangkat sebelum menambah lebih dari ${MAX_DASHBOARDS}.`,
    );
    return;
  }

  if (typeof mqtt === "undefined") {
    showPageAlert(
      "bad",
      "Pustaka MQTT belum tersedia",
      "Pastikan koneksi internet tersedia. Tunggu beberapa saat lalu coba hubungkan kembali; pratinjau tetap bisa digunakan.",
    );
    return;
  }

  hidePageAlert();
  const dashboard = new DeviceDashboard({ deviceId, username, password });
  dashboards.set(deviceId, dashboard);
  history.syncDevices();
  showView("dashboard");
  page.password.value = "";
  page.deviceId.value = "";
  page.username.value = "";
  page.deviceId.focus();
  updateSummary();
}

const history = new MeasurementHistory({ getDevices: () => dashboards, onOpen: () => showView("history"), formatNumber });

page.form.addEventListener("submit", (event) => {
  event.preventDefault();
  addDashboard();
});

page.deviceId.addEventListener("input", () => {
  if (!page.username.value || page.username.dataset.auto === "true") {
    page.username.value = page.deviceId.value.trim();
    page.username.dataset.auto = "true";
  }
});
page.username.addEventListener("input", () => {
  page.username.dataset.auto = String(page.username.value === page.deviceId.value.trim());
});
page.themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});
page.previewButton.addEventListener("click", () => {
  showView("dashboard");
  togglePreview();
});
page.historyButton.addEventListener("click", () => history.open());
page.presets.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => connectPreset(button.dataset.preset));
});
page.dashboardButton.addEventListener("click", () => showView("dashboard"));
page.completionOpen.addEventListener("click", () => history.open(lastCompletedDevice));
page.previewConnect.addEventListener("click", () => {
  page.connection.open = true;
  page.deviceId.focus();
});
window.addEventListener("resize", () => {
  dashboards.forEach((dashboard) => dashboard.drawChart());
  previewDashboard?.drawChart();
});
window.addEventListener("beforeunload", () => {
  stopPreview();
  dashboards.forEach((dashboard) => dashboard.destroy());
});

applyTheme(initialTheme(), false);
updateSummary();
setInterval(() => dashboards.forEach((dashboard) => dashboard.tick()), 1000);
