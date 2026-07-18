/* global mqtt */

const MAX_SAMPLES = 1000;
const samples = [];
let client = null;

// Broker MQTT diakses lewat Traefik/Coolify (server terpisah dari frontend
// ini) yang hanya membuka port 443 (WSS) ke internet. Port WebSocket
// mentah Mosquitto (9001) tidak reachable dari luar, jadi default di sini
// TIDAK memakai window.location.hostname/9001 (itu hanya benar kalau
// halaman ini dan broker berada di jaringan/host yang sama).
const DEFAULT_MQTT_HOST = "mqtt-glucometer.sivia.id";
const DEFAULT_MQTT_WSS_PORT = "443";

const elements = {
  host: document.querySelector("#host"),
  port: document.querySelector("#port"),
  username: document.querySelector("#username"),
  password: document.querySelector("#password"),
  deviceId: document.querySelector("#device-id"),
  connectButton: document.querySelector("#connect-button"),
  connectionStatus: document.querySelector("#connection-status"),
  currentDevice: document.querySelector("#current-device"),
  currentMode: document.querySelector("#current-mode"),
  measurementId: document.querySelector("#measurement-id"),
  realtimeSi: document.querySelector("#realtime-si"),
  realtimeHrv: document.querySelector("#realtime-hrv"),
  realtimeBmi: document.querySelector("#realtime-bmi"),
  realtimeAge: document.querySelector("#realtime-age"),
  realtimeVoltage: document.querySelector("#realtime-voltage"),
  realtimeMfcc: document.querySelector("#realtime-mfcc"),
  lastAdc: document.querySelector("#last-adc"),
  sampleCount: document.querySelector("#sample-count"),
  resultStatus: document.querySelector("#result-status"),
  lastResult: document.querySelector("#last-result"),
  canvas: document.querySelector("#chart"),
};

elements.host.value = DEFAULT_MQTT_HOST;
elements.port.value = DEFAULT_MQTT_WSS_PORT;
elements.connectButton.addEventListener("click", toggleConnection);
window.addEventListener("resize", drawChart);

function resolveWsProtocol(port) {
  // 443/8883 hanya masuk akal lewat TLS (WSS lewat reverse proxy).
  // Selain itu, ikuti protokol halaman ini sendiri (mis. ws:// untuk
  // testing LAN langsung ke port 9001 tanpa TLS).
  if (port === "443" || port === "8883") {
    return "wss";
  }
  return window.location.protocol === "https:" ? "wss" : "ws";
}

function toggleConnection() {
  if (client) {
    client.end(true);
    client = null;
    setConnectionStatus("Disconnected", false);
    elements.connectButton.textContent = "Connect";
    return;
  }

  const port = elements.port.value.trim();
  const protocol = resolveWsProtocol(port);
  const url = `${protocol}://${elements.host.value}:${port}`;
  const deviceId = elements.deviceId.value.trim() || "+";

  const fallbackId = Math.random().toString(16).slice(2);
  const randomId = globalThis.crypto?.randomUUID?.() ?? fallbackId;

  client = mqtt.connect(url, {
    username: elements.username.value,
    password: elements.password.value,
    clientId: `dashboard-${randomId}`,
    reconnectPeriod: 1000,
    connectTimeout: 10000,
    clean: true,
  });

  setConnectionStatus("Connecting...", false);

  client.on("connect", () => {
    const topics = [
      `ppg/${deviceId}/raw`,
      `ppg/${deviceId}/metrics`,
      `ppg/${deviceId}/measurement/start`,
      `ppg/${deviceId}/measurement/result`,
      `ppg/${deviceId}/status`,
    ];
    client.subscribe(topics, { qos: 1 });
    setConnectionStatus("Connected", true);
    elements.connectButton.textContent = "Disconnect";
  });

  client.on("reconnect", () => setConnectionStatus("Reconnecting...", false));
  client.on("offline", () => setConnectionStatus("Offline", false));
  client.on("error", (error) => {
    console.error(error);
    setConnectionStatus("Connection error", false);
  });
  client.on("message", handleMessage);
}

function handleMessage(topic, payloadBuffer) {
  try {
    const payload = JSON.parse(payloadBuffer.toString());
    const parts = topic.split("/");
    const deviceId = parts[1];
    const event = parts.slice(2).join("/");

    elements.currentDevice.textContent = deviceId;

    if (event === "raw") {
      elements.currentMode.textContent = payload.mode || "-";
      elements.measurementId.textContent = payload.measurement_id || "Live preview";

      const incoming = Array.isArray(payload.samples) ? payload.samples : [];
      samples.push(...incoming.map(Number));
      if (samples.length > MAX_SAMPLES) {
        samples.splice(0, samples.length - MAX_SAMPLES);
      }

      if (incoming.length) {
        elements.lastAdc.textContent = Math.round(incoming[incoming.length - 1]);
      }
      elements.sampleCount.textContent = `${samples.length} samples`;
      drawChart();
    } else if (event === "metrics") {
      elements.currentMode.textContent = payload.mode || "-";
      elements.measurementId.textContent = payload.measurement_id || "Live preview";
      elements.realtimeSi.textContent = formatMetric(payload.si_m_s, 4, " m/s");
      elements.realtimeHrv.textContent = formatMetric(payload.hrv_ms, 2, " ms");
      elements.realtimeBmi.textContent = formatMetric(payload.bmi, 2);
      elements.realtimeAge.textContent = formatMetric(payload.age_years, 0, " yr");
      elements.realtimeVoltage.textContent = formatMetric(payload.voltage_v, 2, " V");
      elements.lastAdc.textContent = formatMetric(payload.adc, 0);
      elements.realtimeMfcc.textContent = Array.isArray(payload.mfcc)
        ? JSON.stringify(payload.mfcc, null, 2)
        : "[]";
    } else if (event === "measurement/start") {
      elements.currentMode.textContent = "recording";
      elements.measurementId.textContent = payload.measurement_id;
      elements.resultStatus.textContent = "Measurement berjalan";
    } else if (event === "measurement/result") {
      elements.currentMode.textContent = "live";
      elements.measurementId.textContent = "Live preview";
      elements.resultStatus.textContent = payload.status || "completed";
      elements.lastResult.textContent = JSON.stringify(payload, null, 2);
    } else if (event === "status") {
      setConnectionStatus(`Broker connected / Device ${payload.state}`, payload.state === "online");
    }
  } catch (error) {
    console.error("Payload tidak valid", error);
  }
}

function formatMetric(value, digits, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}${suffix}` : "-";
}

function setConnectionStatus(text, online) {
  elements.connectionStatus.textContent = text;
  elements.connectionStatus.className = `badge ${online ? "online" : "offline"}`;
}

function drawChart() {
  const canvas = elements.canvas;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(300, canvas.clientWidth);
  const height = Math.max(200, canvas.clientHeight);

  canvas.width = width * ratio;
  canvas.height = height * ratio;

  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  context.strokeStyle = "#1d3550";
  context.lineWidth = 1;
  for (let line = 1; line < 5; line += 1) {
    const y = (height / 5) * line;
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }

  if (samples.length < 2) {
    return;
  }

  const min = Math.min(...samples);
  const max = Math.max(...samples);
  const range = Math.max(1, max - min);

  context.strokeStyle = "#50d9ff";
  context.lineWidth = 2;
  context.beginPath();
  samples.forEach((value, index) => {
    const x = (index / (samples.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 24) - 12;
    if (index === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.stroke();
}

drawChart();
