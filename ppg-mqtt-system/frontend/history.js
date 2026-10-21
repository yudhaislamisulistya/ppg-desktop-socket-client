/* Data History dan label tetap di PostgreSQL, bukan penyimpanan browser. */
function historyPageNumbers(current, total) {
  if (total < 1) return [];
  const start = Math.max(1, Math.min(current - 2, total - 4));
  const pages = [...new Set([1, total, ...Array.from({ length: 5 }, (_, index) => start + index)])]
    .filter((page) => page <= total).sort((left, right) => left - right);
  const result = [];
  pages.forEach((page, index) => {
    const gap = page - pages[index - 1];
    if (gap === 2) result.push(page - 1);
    else if (gap > 2) result.push(null);
    result.push(page);
  });
  return result;
}

class MeasurementHistory {
  constructor({ getDevices, onOpen, formatNumber }) {
    this.getDevices = getDevices;
    this.onOpen = onOpen;
    this.formatNumber = formatNumber;
    this.ui = Object.fromEntries(["panel", "device", "refresh", "status", "list", "badge",
      "table-wrap", "pagination", "page-info", "pages", "previous", "next", "page-size", "scroll-hint"]
      .map((key) => [key, document.getElementById(`history-${key}`)]));
    this.rows = [];
    this.currentPage = 1;
    this.total = 0;
    this.generation = 0;
    this.expected = new Map();
    this.drafts = new Map();
    this.saving = new Set();
    this.ui.device.addEventListener("change", () => this.load({ page: 1 }));
    this.ui.refresh.addEventListener("click", () => this.load());
    this.ui["page-size"].addEventListener("change", () => this.load({ page: 1 }));
    this.ui.previous.addEventListener("click", () => this.load({ page: this.currentPage - 1 }));
    this.ui.next.addEventListener("click", () => this.load({ page: this.currentPage + 1 }));
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
      this.currentPage = 1;
      this.total = 0;
      this.ui.list.replaceChildren();
      this.ui.pagination.hidden = true;
      this.ui["table-wrap"].hidden = true;
      this.ui["scroll-hint"].hidden = true;
      if (!this.ui.panel.hidden) this.load();
    }
  }

  open(deviceId) {
    this.onOpen();
    this.syncDevices();
    if (deviceId && this.getDevices().has(deviceId) && this.ui.device.value !== deviceId) {
      this.ui.device.value = deviceId;
      this.currentPage = 1;
    }
    if (this.expected.has(this.ui.device.value)) this.currentPage = 1;
    this.ui.badge.hidden = true;
    this.load();
  }

  notifyCompleted(deviceId, measurementId) {
    if (measurementId) this.expected.set(deviceId, measurementId);
    this.ui.badge.hidden = false;
    if (!this.ui.panel.hidden && this.ui.device.value === deviceId) this.load({ page: 1 });
  }

  setBusy(busy) {
    this.ui.panel.setAttribute("aria-busy", String(busy));
    this.ui.refresh.disabled = busy || !this.getDevices().has(this.ui.device.value);
    this.ui["page-size"].disabled = busy;
    this.ui.previous.disabled = busy || this.currentPage <= 1;
    this.ui.next.disabled = busy || this.currentPage >= Math.ceil(this.total / Number(this.ui["page-size"].value));
    this.ui.pages.querySelectorAll("button").forEach((button) => { button.disabled = busy; });
  }

  renderPagination() {
    const size = Number(this.ui["page-size"].value);
    const pages = Math.max(1, Math.ceil(this.total / size));
    this.ui.pagination.hidden = this.total === 0;
    this.ui["page-info"].textContent = `Menampilkan ${(this.currentPage - 1) * size + 1}–${Math.min(this.currentPage * size, this.total)} dari ${this.total} rekaman · Halaman ${this.currentPage} dari ${pages}`;
    this.ui.pages.replaceChildren();
    historyPageNumbers(this.currentPage, pages).forEach((page) => {
      if (page === null) {
        const dots = document.createElement("span");
        dots.textContent = "…";
        this.ui.pages.append(dots);
        return;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ghost-btn";
      button.textContent = page;
      button.setAttribute("aria-label", `Halaman ${page}`);
      if (page === this.currentPage) button.setAttribute("aria-current", "page");
      button.addEventListener("click", () => this.load({ page }));
      this.ui.pages.append(button);
    });
  }

  async load({ page = this.currentPage } = {}) {
    const deviceId = this.ui.device.value;
    const device = this.getDevices().get(deviceId);
    const generation = ++this.generation;
    const size = Number(this.ui["page-size"].value);
    page = Math.max(1, page);
    this.rows = [];
    this.ui.list.replaceChildren();
    this.ui["table-wrap"].hidden = true;
    this.ui["scroll-hint"].hidden = true;
    if (!device) {
      this.ui.pagination.hidden = true;
      this.setBusy(false);
      this.ui.status.textContent = "Hubungkan perangkat menggunakan Device ID, Username, dan Password untuk membuka History.";
      return;
    }
    this.setBusy(true);
    this.ui.status.textContent = "Memuat rekaman dari PostgreSQL…";
    try {
      let data;
      const expected = page === 1 ? this.expected.get(deviceId) : null;
      for (let attempt = 0; attempt < 6; attempt += 1) {
        data = await device.requestHistory("list", { limit: size, offset: (page - 1) * size });
        if (generation !== this.generation) return;
        if (!Array.isArray(data?.measurements) || !Number.isSafeInteger(data.total) || data.total < 0) {
          throw new Error("Respons pagination History tidak valid. Pastikan service storage telah diperbarui.");
        }
        const lastPage = Math.max(1, Math.ceil(data.total / size));
        if (page > lastPage) { page = lastPage; continue; }
        if (!expected || data.measurements.some((row) => row.id === expected)) break;
        this.ui.status.textContent = "Perekaman selesai. Menunggu penyimpanan hasil di PostgreSQL…";
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (generation !== this.generation) return;
      }
      this.currentPage = page;
      this.total = data.total;
      this.rows = data.measurements;
      this.render(device);
      this.ui["table-wrap"].hidden = this.rows.length === 0;
      this.ui["scroll-hint"].hidden = this.rows.length === 0;
      this.renderPagination();
      if (expected && !this.rows.some((row) => row.id === expected)) {
        this.ui.status.textContent = "Hasil terbaru belum tersimpan. Tekan Muat ulang; periksa service storage jika tetap belum muncul.";
      } else {
        if (expected) this.expected.delete(deviceId);
        if (!this.ui.panel.hidden) this.ui.badge.hidden = true;
        this.ui.status.textContent = this.rows.length
          ? `Halaman ${page}: ${this.rows.length} dari ${this.total} rekaman. Label boleh dibiarkan belum diisi.`
          : "Belum ada rekaman selesai. Rekaman akan muncul setelah Submit dan perekaman 300 detik selesai.";
      }
    } catch (error) {
      if (generation === this.generation) {
        this.ui.pagination.hidden = true;
        this.ui.status.textContent = `History gagal dimuat. ${error.message}`;
      }
    } finally {
      if (generation === this.generation) {
        this.setBusy(false);
      }
    }
  }

  date(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime())
      ? new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "medium" }).format(date) : "—";
  }

  render(device) {
    this.ui.list.replaceChildren();
    this.rows.forEach((row, index) => {
      const entry = document.createElement("tr");
      entry.className = "history-entry";
      entry.dataset.measurementId = row.id;
      const number = document.createElement("td");
      number.textContent = (this.currentPage - 1) * Number(this.ui["page-size"].value) + index + 1;
      const patient = document.createElement("th");
      patient.scope = "row";
      patient.className = "history-patient";
      patient.textContent = row.patient_name || "Nama pasien belum tersedia";
      const date = document.createElement("td");
      date.className = "history-date";
      date.textContent = this.date(row.started_at);
      entry.append(number, patient, date);
      for (const [value, digits] of [
        [row.si_mean, 4], [row.hrv_mean, 2], [row.bmi, 2],
        [row.age, 0], [row.voltage_mean, 3], [row.adc_mean, 0],
      ]) {
        const cell = document.createElement("td");
        cell.className = "history-number";
        cell.textContent = this.formatNumber(value, digits);
        entry.append(cell);
      }
      const labelCell = document.createElement("td");
      const form = document.createElement("form");
      form.className = "history-label-form";
      const field = document.createElement("div");
      field.className = "field";
      const label = document.createElement("label");
      label.textContent = "Label diabetes (opsional)";
      label.className = "sr-only";
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
        : row.label_updated_at ? `Diperbarui ${this.date(row.label_updated_at)}` : "";
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
      labelCell.append(form);
      entry.append(labelCell);
      const detailCell = document.createElement("td");
      const detailButton = document.createElement("button");
      detailButton.type = "button";
      detailButton.className = "text-btn";
      detailButton.textContent = "Detail";
      detailButton.setAttribute("aria-expanded", "false");
      const detailRow = document.createElement("tr");
      detailRow.className = "history-detail-row";
      detailRow.id = `history-detail-${this.generation}-${index}`;
      detailRow.hidden = true;
      detailButton.setAttribute("aria-controls", detailRow.id);
      detailButton.setAttribute("aria-label", `Detail rekaman ${number.textContent}`);
      detailButton.addEventListener("click", () => {
        detailRow.hidden = !detailRow.hidden;
        detailButton.setAttribute("aria-expanded", String(!detailRow.hidden));
      });
      const details = document.createElement("td");
      details.colSpan = 11;
      const meta = document.createElement("p");
      meta.className = "history-meta";
      meta.textContent = `${row.device_id} · Selesai ${this.date(row.finished_at)} · ${row.duration_seconds} detik · ${row.raw_sample_count ?? 0} sampel · ID ${row.id}`;
      details.append(meta);
      if (Array.isArray(row.mfcc) && row.mfcc.length) {
        const summary = document.createElement("p");
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
      } else {
        const empty = document.createElement("p");
        empty.textContent = "Koefisien MFCC belum tersedia pada rekaman ini.";
        details.append(empty);
      }
      detailRow.append(details);
      detailCell.append(detailButton);
      entry.append(detailCell);
      this.ui.list.append(entry, detailRow);
    });
  }
}
