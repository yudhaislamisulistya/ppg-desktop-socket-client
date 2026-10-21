/* Data History dan label tetap di PostgreSQL, bukan penyimpanan browser. */
class MeasurementHistory {
  constructor({ getDevices, onOpen, formatNumber }) {
    this.getDevices = getDevices;
    this.onOpen = onOpen;
    this.formatNumber = formatNumber;
    this.ui = Object.fromEntries(["panel", "device", "refresh", "status", "list", "more", "badge"]
      .map((key) => [key, document.getElementById(`history-${key}`)]));
    this.rows = [];
    this.generation = 0;
    this.expected = new Map();
    this.drafts = new Map();
    this.saving = new Set();
    this.ui.device.addEventListener("change", () => this.load());
    this.ui.refresh.addEventListener("click", () => this.load());
    this.ui.more.addEventListener("click", () => this.load({ append: true }));
    this.syncDevices();
  }

  syncDevices() {
    const devices = [...this.getDevices().keys()];
    const previous = this.ui.device.value;
    this.ui.device.disabled = devices.length === 0;
    this.ui.refresh.disabled = devices.length === 0;
    if ([...this.ui.device.options].map((option) => option.value).join("|") === devices.join("|")) return;
    this.generation += 1;
    this.ui.panel.setAttribute("aria-busy", "false");
    this.ui.device.replaceChildren(...devices.map((id) => new Option(id, id)));
    this.ui.device.value = devices.includes(previous) ? previous : devices[0] || "";
    for (const [id, draft] of this.drafts) if (!devices.includes(draft.deviceId)) this.drafts.delete(id);
    for (const id of this.expected.keys()) if (!devices.includes(id)) this.expected.delete(id);
    if (previous !== this.ui.device.value || !devices.length) {
      this.rows = [];
      this.ui.list.replaceChildren();
      this.ui.more.hidden = true;
      if (!this.ui.panel.hidden) this.load();
    }
  }

  open(deviceId) {
    this.onOpen();
    this.syncDevices();
    if (deviceId && this.getDevices().has(deviceId)) this.ui.device.value = deviceId;
    this.ui.badge.hidden = true;
    this.load();
  }

  notifyCompleted(deviceId, measurementId) {
    if (measurementId) this.expected.set(deviceId, measurementId);
    this.ui.badge.hidden = false;
    if (!this.ui.panel.hidden && this.ui.device.value === deviceId) this.load();
  }

  async load({ append = false } = {}) {
    const deviceId = this.ui.device.value;
    const device = this.getDevices().get(deviceId);
    const generation = ++this.generation;
    if (!append) {
      this.rows = [];
      this.ui.list.replaceChildren();
    }
    this.ui.more.hidden = true;
    if (!device) {
      this.ui.panel.setAttribute("aria-busy", "false");
      this.ui.status.textContent = "Hubungkan perangkat menggunakan Device ID, Username, dan Password untuk membuka History.";
      return;
    }
    this.ui.panel.setAttribute("aria-busy", "true");
    this.ui.refresh.disabled = true;
    this.ui.status.textContent = "Memuat rekaman dari PostgreSQL…";
    try {
      let data;
      const expected = append ? null : this.expected.get(deviceId);
      for (let attempt = 0; attempt < 6; attempt += 1) {
        data = await device.requestHistory("list", { limit: 20, offset: append ? this.rows.length : 0 });
        if (generation !== this.generation) return;
        if (!Array.isArray(data?.measurements)) throw new Error("Respons History tidak valid.");
        if (!expected || data.measurements.some((row) => row.id === expected)) break;
        this.ui.status.textContent = "Perekaman selesai. Menunggu penyimpanan hasil di PostgreSQL…";
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (generation !== this.generation) return;
      }
      const merged = new Map(this.rows.map((row) => [row.id, row]));
      data.measurements.forEach((row) => merged.set(row.id, row));
      this.rows = [...merged.values()];
      this.render(device);
      this.ui.more.hidden = !data.has_more;
      if (expected && !this.rows.some((row) => row.id === expected)) {
        this.ui.status.textContent = "Hasil terbaru belum tersimpan. Tekan Muat ulang; periksa service storage jika tetap belum muncul.";
      } else {
        this.expected.delete(deviceId);
        if (!this.ui.panel.hidden) this.ui.badge.hidden = true;
        this.ui.status.textContent = this.rows.length
          ? `${this.rows.length} rekaman ditampilkan. Label boleh dibiarkan belum diisi.`
          : "Belum ada rekaman selesai. Rekaman akan muncul setelah Submit dan perekaman 300 detik selesai.";
      }
    } catch (error) {
      if (generation === this.generation) this.ui.status.textContent = `History gagal dimuat. ${error.message}`;
    } finally {
      if (generation === this.generation) {
        this.ui.panel.setAttribute("aria-busy", "false");
        this.ui.refresh.disabled = !this.getDevices().has(deviceId);
      }
    }
  }

  date(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime())
      ? new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "medium" }).format(date) : "—";
  }

  label(value) {
    return value === true ? "Diabetes" : value === false ? "Tidak diabetes" : "Belum diisi";
  }

  render(device) {
    this.ui.list.replaceChildren();
    this.rows.forEach((row, index) => {
      const entry = document.createElement("article");
      entry.className = "history-entry";
      entry.dataset.measurementId = row.id;
      const head = document.createElement("header");
      head.className = "history-entry-head";
      const title = document.createElement("h3");
      title.textContent = row.patient_name || "Nama pasien belum tersedia";
      const badge = document.createElement("span");
      badge.className = "tag";
      badge.textContent = this.label(row.diabetes_label);
      head.append(title, badge);
      const meta = document.createElement("p");
      meta.className = "history-meta";
      meta.textContent = `${row.device_id} · ${this.date(row.started_at)} · Selesai · ${row.duration_seconds} detik`;
      const metrics = document.createElement("dl");
      metrics.className = "result history-metrics";
      for (const [label, value, digits, unit] of [
        ["SI rata-rata", row.si_mean, 4, "m/s"], ["HRV rata-rata", row.hrv_mean, 2, "ms"],
        ["BMI", row.bmi, 2, "kg/m²"], ["Umur", row.age, 0, "th"],
        ["Voltase rata-rata", row.voltage_mean, 3, "V"], ["ADC rata-rata", row.adc_mean, 0, ""],
      ]) {
        const cell = document.createElement("div");
        const term = document.createElement("dt");
        term.textContent = label;
        const detail = document.createElement("dd");
        detail.textContent = `${this.formatNumber(value, digits)}${unit ? ` ${unit}` : ""}`;
        cell.append(term, detail);
        metrics.append(cell);
      }
      const form = document.createElement("form");
      form.className = "history-label-form";
      const field = document.createElement("div");
      field.className = "field";
      const label = document.createElement("label");
      label.textContent = "Label diabetes (opsional)";
      const select = document.createElement("select");
      select.id = `history-label-${this.generation}-${index}`;
      label.htmlFor = select.id;
      select.append(new Option("Belum diisi", ""), new Option("Diabetes", "true"), new Option("Tidak diabetes", "false"));
      const savedValue = () => row.diabetes_label === true ? "true" : row.diabetes_label === false ? "false" : "";
      select.value = this.drafts.get(row.id)?.value ?? savedValue();
      select.disabled = this.saving.has(row.id);
      field.append(label, select);
      const save = document.createElement("button");
      save.type = "submit";
      save.className = "ghost-btn";
      save.textContent = "Simpan label";
      save.disabled = select.disabled || select.value === savedValue();
      const status = document.createElement("p");
      status.className = "history-label-status";
      status.setAttribute("role", "status");
      status.textContent = select.disabled ? "Menyimpan label…" : select.value !== savedValue() ? "Perubahan belum disimpan."
        : row.label_updated_at ? `Diperbarui ${this.date(row.label_updated_at)}` : "Dapat diisi nanti.";
      select.addEventListener("change", () => {
        this.drafts.set(row.id, { deviceId: device.deviceId, value: select.value });
        save.disabled = select.value === savedValue();
        status.textContent = save.disabled ? "Tidak ada perubahan." : "Perubahan belum disimpan.";
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (this.saving.has(row.id)) return;
        this.saving.add(row.id);
        select.disabled = true;
        save.disabled = true;
        status.textContent = "Menyimpan label…";
        try {
          const result = await device.requestHistory("set_label", {
            measurement_id: row.id, diabetes_label: select.value === "" ? null : select.value === "true",
          });
          row.diabetes_label = result.diabetes_label;
          row.label_updated_at = result.label_updated_at;
          const current = this.rows.find((item) => item.id === row.id);
          if (current) Object.assign(current, { diabetes_label: result.diabetes_label, label_updated_at: result.label_updated_at });
          this.drafts.delete(row.id);
          badge.textContent = this.label(row.diabetes_label);
          select.value = savedValue();
          status.textContent = `Label tersimpan. ${this.date(row.label_updated_at)}`;
        } catch (error) {
          status.textContent = `Label belum terkonfirmasi. ${error.message} Muat ulang untuk memeriksa.`;
        } finally {
          this.saving.delete(row.id);
          select.disabled = false;
          save.disabled = select.value === savedValue();
          if (!entry.isConnected && this.ui.device.value === device.deviceId) this.render(device);
        }
      });
      form.append(field, save, status);
      entry.append(head, meta, metrics, form);
      if (Array.isArray(row.mfcc) && row.mfcc.length) {
        const details = document.createElement("details");
        details.className = "mfcc-details";
        const summary = document.createElement("summary");
        summary.textContent = "Detail koefisien MFCC rata-rata";
        const values = document.createElement("dl");
        values.className = "mfcc-values";
        row.mfcc.forEach((value, coefficient) => {
          const cell = document.createElement("div");
          const term = document.createElement("dt");
          term.textContent = `C${String(coefficient + 1).padStart(2, "0")}`;
          const detail = document.createElement("dd");
          detail.textContent = this.formatNumber(value, 6);
          cell.append(term, detail);
          values.append(cell);
        });
        details.append(summary, values);
        entry.append(details);
      }
      this.ui.list.append(entry);
    });
  }
}
