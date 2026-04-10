const FLOOR_IDS = [0, 1, 2];
const HISTORY_LIMIT = 240;
const HISTORY_PAGE_SIZE = 20;
const TREND_LIMIT = 20;

const SENSOR_META = [
  { key: "temp_c", label: "Temperature", suffix: " C" },
  { key: "hum_pct", label: "Humidity", suffix: " %" },
  { key: "gas_a", label: "Gas", suffix: " A/D" },
  { key: "sound_a", label: "Sound", suffix: " A/D" },
];

const TREND_SERIES = [
  { key: "temp_c", label: "Temp", color: "#00d4ff" },
  { key: "hum_pct", label: "Humidity", color: "#00ff88" },
  { key: "gas_a", label: "Gas", color: "#f5a623" },
  { key: "sound_a", label: "Sound", color: "#ff3b5c" },
];

const state = {
  floors: {},
  history: [],
  stats: { safe_count: 0, caution_count: 0, evacuate_count: 0, total: 0 },
  selectedFloor: 0,
  paused: false,
  interval: 2000,
  ingestThingSpeak: true,
  uploadThingSpeak: false,
  historyVisibleCount: HISTORY_PAGE_SIZE,
  pollTimer: null,
  pollBusy: false,
  channels: {
    0: { channel_id: "3333445", read_api_key: "TJH75U3FO9R0C8C9" },
    1: { channel_id: "3328061", read_api_key: "MEA0BVFA9LIRWD8Z" },
    2: { channel_id: "3333277", read_api_key: "KDG5KPHE7C88AMMD" },
  },
};

const charts = {
  trend: null,
  distribution: null,
};

const els = {
  dashboardFrame: document.getElementById("dashboard-frame"),
  floorGrid: document.getElementById("floor-grid"),
  statsBar: document.getElementById("stats-bar"),
  detailFloorLabel: document.getElementById("detail-floor-label"),
  detailFloorMeta: document.getElementById("detail-floor-meta"),
  detailStateBadge: document.getElementById("detail-state-badge"),
  detailInfoGrid: document.getElementById("detail-info-grid"),
  rawJsonViewer: document.getElementById("raw-json-viewer"),
  incidentBody: document.getElementById("incident-body"),
  loadMoreBtn: document.getElementById("load-more-btn"),
  reloadHistoryBtn: document.getElementById("reload-history-btn"),
  streamPillText: document.getElementById("stream-pill-text"),
  dbPill: document.getElementById("db-pill"),
  topbarPauseBtn: document.getElementById("topbar-pause-btn"),
  sidebarPauseBtn: document.getElementById("sidebar-pause-btn"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  controlSidebar: document.getElementById("control-sidebar"),
  ingestToggle: document.getElementById("ingest-toggle"),
  uploadToggle: document.getElementById("upload-toggle"),
  streamIntervalInput: document.getElementById("stream-interval-input"),
  alertRegion: document.getElementById("alert-region"),
  toastRegion: document.getElementById("toast-region"),
  trendLegend: document.getElementById("trend-legend"),
  trendCanvas: document.getElementById("trend-chart"),
  distributionCanvas: document.getElementById("distribution-chart"),
  streamDot: document.querySelector(".live-dot"),
  channelInputs: {
    0: {
      channel: document.getElementById("channel-0-input"),
      key: document.getElementById("key-0-input"),
    },
    1: {
      channel: document.getElementById("channel-1-input"),
      key: document.getElementById("key-1-input"),
    },
    2: {
      channel: document.getElementById("channel-2-input"),
      key: document.getElementById("key-2-input"),
    },
  },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function stateClassName(value) {
  if (value === "SAFE") return "safe";
  if (value === "CAUTION") return "caution";
  if (value === "EVACUATE") return "evacuate";
  return "neutral";
}

function formatNumber(value, suffix = "", digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return `${value}${suffix}`;
  return `${number.toFixed(digits)}${suffix}`;
}

function formatSensorDisplay(key, floor) {
  if (!floor) return "-";
  if (key === "gas_a") {
    return `${formatNumber(floor.gas_a)} / ${floor.gas_d ?? "-"}`;
  }
  if (key === "sound_a") {
    return `${formatNumber(floor.sound_a)} / ${floor.sound_d ?? "-"}`;
  }
  if (key === "temp_c") return formatNumber(floor.temp_c, " C");
  if (key === "hum_pct") return formatNumber(floor.hum_pct, " %");
  return formatNumber(floor[key]);
}

function formatTimestamp(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toISOString().replace(".000", "");
}

function getLatestRowId() {
  return state.history.reduce((maxId, row) => Math.max(maxId, Number(row.id || 0)), 0);
}

function getFloorConfigs() {
  return FLOOR_IDS.map((floorId) => ({
    floor_id: floorId,
    channel_id: els.channelInputs[floorId].channel.value.trim(),
    read_api_key: els.channelInputs[floorId].key.value.trim(),
  })).filter((config) => config.channel_id);
}

function applyConfig(config) {
  els.dbPill.textContent = `DB: ${String(config.incident_log_backend || "sqlite").toUpperCase()}`;
  if (Array.isArray(config.floor_configs)) {
    config.floor_configs.forEach((entry) => {
      const floorId = Number(entry.floor_id);
      if (!FLOOR_IDS.includes(floorId)) return;
      state.channels[floorId] = {
        channel_id: String(entry.channel_id || state.channels[floorId].channel_id || ""),
        read_api_key: String(entry.read_api_key || state.channels[floorId].read_api_key || ""),
      };
      els.channelInputs[floorId].channel.value = state.channels[floorId].channel_id;
      els.channelInputs[floorId].key.value = state.channels[floorId].read_api_key;
    });
  }
}

function createLegend() {
  els.trendLegend.innerHTML = TREND_SERIES.map(
    (series) => `<span class="legend-pill"><span class="legend-swatch" style="background:${series.color}"></span>${escapeHtml(series.label)}</span>`
  ).join("");
}

function buildFloorCard(floorId, floor) {
  const article = document.createElement("article");
  const badgeClass = stateClassName(floor?.final_state);
  article.className = `floor-card ${badgeClass}${floorId === state.selectedFloor ? " selected" : ""}`;
  article.dataset.floorId = String(floorId);
  article.setAttribute("role", "button");
  article.setAttribute("tabindex", "0");
  article.setAttribute("aria-selected", String(floorId === state.selectedFloor));

  const sensorsHtml = SENSOR_META.map(
    (sensor) => `
      <div class="sensor-row">
        <span class="sensor-label">${escapeHtml(sensor.label)}</span>
        <strong class="sensor-value">${escapeHtml(formatSensorDisplay(sensor.key, floor))}</strong>
      </div>
    `
  ).join("");

  article.innerHTML = `
    <div class="floor-card-head">
      <div>
        <p class="floor-card-title">Floor ${floorId}</p>
        <p class="floor-card-subtitle">ThingSpeak ${escapeHtml(floor?.channel_id || state.channels[floorId].channel_id || "-")}</p>
      </div>
      <span class="status-badge ${badgeClass}">${escapeHtml(floor?.final_state || "WAITING")}</span>
    </div>
    <div class="sensor-list">${sensorsHtml}</div>
  `;

  return article;
}

function renderFloorCards() {
  els.floorGrid.innerHTML = "";
  FLOOR_IDS.forEach((floorId) => {
    els.floorGrid.appendChild(buildFloorCard(floorId, state.floors[floorId]));
  });
}

function renderStats() {
  const metrics = [
    { label: "SAFE", value: state.stats.safe_count || 0, className: "safe" },
    { label: "CAUTION", value: state.stats.caution_count || 0, className: "caution" },
    { label: "EVACUATE", value: state.stats.evacuate_count || 0, className: "evacuate" },
    { label: "TOTAL", value: state.stats.total || 0, className: "total" },
  ];

  els.statsBar.innerHTML = metrics.map(
    (metric) => `<div class="metric-pill ${metric.className}"><span>${metric.label}</span><span>${escapeHtml(metric.value)}</span></div>`
  ).join("");
}

function renderDetailPanel() {
  const floorId = state.selectedFloor;
  const floor = state.floors[floorId];
  const badgeClass = stateClassName(floor?.final_state);
  const cells = [
    { label: "Current State", value: floor?.final_state || "WAITING" },
    { label: "Logged UTC", value: formatTimestamp(floor?.logged_at_utc) },
    { label: "Temp C", value: formatNumber(floor?.temp_c, " C") },
    { label: "Humidity %", value: formatNumber(floor?.hum_pct, " %") },
    { label: "Gas A/D", value: floor ? `${formatNumber(floor.gas_a)} / ${floor.gas_d ?? "-"}` : "-" },
    { label: "Sound A/D", value: floor ? `${formatNumber(floor.sound_a)} / ${floor.sound_d ?? "-"}` : "-" },
    { label: "Channel", value: floor?.channel_id || state.channels[floorId]?.channel_id || "-" },
    { label: "Source", value: floor?.source || "-" },
  ];

  els.detailFloorLabel.textContent = `Floor ${floorId}`;
  els.detailFloorMeta.textContent = floor
    ? `Latest entry ${floor.entry_id || "-"} recorded ${formatTimestamp(floor.logged_at_utc)}`
    : "Awaiting floor telemetry.";
  els.detailStateBadge.className = `status-badge ${badgeClass}`;
  els.detailStateBadge.textContent = floor?.final_state || "WAITING";

  els.detailInfoGrid.innerHTML = cells.map(
    (cell) => `
      <div class="info-cell">
        <p class="info-cell-label">${escapeHtml(cell.label)}</p>
        <p class="info-cell-value">${escapeHtml(cell.value)}</p>
      </div>
    `
  ).join("");

  els.rawJsonViewer.textContent = JSON.stringify(floor?.raw_event || floor || {}, null, 2);
}

function renderIncidentFeed() {
  const visibleRows = state.history.slice(0, state.historyVisibleCount);
  els.incidentBody.innerHTML = "";

  if (visibleRows.length === 0) {
    const emptyRow = document.createElement("tr");
    emptyRow.className = "empty-row";
    emptyRow.innerHTML = '<td colspan="8">No incident rows available.</td>';
    els.incidentBody.appendChild(emptyRow);
  } else {
    visibleRows.forEach((row) => {
      const tr = document.createElement("tr");
      const badgeClass = stateClassName(row.final_state);
      tr.innerHTML = `
        <td>${escapeHtml(row.id ?? "-")}</td>
        <td>${escapeHtml(row.floor_id ?? "-")}</td>
        <td>${escapeHtml(formatTimestamp(row.logged_at_utc))}</td>
        <td><span class="status-badge ${badgeClass}">${escapeHtml(row.final_state || "-")}</span></td>
        <td>${escapeHtml(formatNumber(row.temp_c, " C"))}</td>
        <td>${escapeHtml(formatNumber(row.hum_pct, " %"))}</td>
        <td>${escapeHtml(formatNumber(row.gas_a))}</td>
        <td>${escapeHtml(formatNumber(row.sound_a))}</td>
      `;
      els.incidentBody.appendChild(tr);
    });
  }

  els.loadMoreBtn.hidden = state.historyVisibleCount >= state.history.length;
}

function getSelectedFloorHistory() {
  return state.history
    .filter((row) => Number(row.floor_id) === state.selectedFloor)
    .slice(0, TREND_LIMIT)
    .reverse();
}

function initCharts() {
  Chart.defaults.color = "#4a6a8a";
  Chart.defaults.borderColor = "#1a2540";
  Chart.defaults.font.family = "'Inter', system-ui";

  const centerLabelPlugin = {
    id: "centerLabel",
    afterDraw(chart) {
      if (chart.config.type !== "doughnut") return;
      const { ctx } = chart;
      const meta = chart.getDatasetMeta(0);
      if (!meta?.data?.length) return;
      const x = meta.data[0].x;
      const y = meta.data[0].y;
      ctx.save();
      ctx.textAlign = "center";
      ctx.fillStyle = "#4a6a8a";
      ctx.font = "500 10px Inter";
      ctx.fillText("TOTAL", x, y - 6);
      ctx.fillStyle = "#d0e8ff";
      ctx.font = "700 24px Rajdhani";
      ctx.fillText(String(state.stats.total || 0), x, y + 18);
      ctx.restore();
    },
  };

  charts.trend = new Chart(els.trendCanvas, {
    type: "line",
    data: {
      labels: [],
      datasets: TREND_SERIES.map((series) => ({
        label: series.label,
        data: [],
        borderColor: series.color,
        backgroundColor: `${series.color}44`,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: {
          grid: { color: "#1a254033" },
          ticks: { color: "#4a6a8a", maxTicksLimit: 8 },
        },
        y: {
          grid: { color: "#1a254033" },
          ticks: { color: "#4a6a8a" },
        },
      },
      elements: {
        line: { tension: 0.4, borderWidth: 2 },
        point: { radius: 2, hoverRadius: 5 },
      },
    },
  });

  charts.distribution = new Chart(els.distributionCanvas, {
    type: "doughnut",
    data: {
      labels: ["SAFE", "CAUTION", "EVACUATE"],
      datasets: [
        {
          data: [0, 0, 0],
          backgroundColor: ["#00ff88", "#f5a623", "#ff3b5c"],
          borderColor: ["#00ff88", "#f5a623", "#ff3b5c"],
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "72%",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context) {
              const total = state.stats.total || 1;
              const value = Number(context.raw || 0);
              const percent = ((value / total) * 100).toFixed(1);
              return `${context.label}: ${value} (${percent}%)`;
            },
          },
        },
      },
    },
    plugins: [centerLabelPlugin],
  });
}

function updateTrendChart() {
  const rows = getSelectedFloorHistory();
  const labels = rows.map((row) => {
    const source = row.timestamp || row.logged_at_utc;
    const date = new Date(source);
    if (Number.isNaN(date.getTime())) return source || "-";
    return date.toISOString().slice(11, 19);
  });

  if (charts.trend) {
    charts.trend.destroy();
  }

  charts.trend = new Chart(els.trendCanvas, {
    type: "line",
    data: {
      labels,
      datasets: TREND_SERIES.map((series) => ({
        label: series.label,
        data: rows.map((row) => Number(row[series.key] || 0)),
        borderColor: series.color,
        backgroundColor: `${series.color}44`,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: {
          grid: { color: "#1a254033" },
          ticks: { color: "#4a6a8a", maxTicksLimit: 8 },
        },
        y: {
          grid: { color: "#1a254033" },
          ticks: { color: "#4a6a8a" },
        },
      },
      elements: {
        line: { tension: 0.4, borderWidth: 2 },
        point: { radius: 2, hoverRadius: 5 },
      },
    },
  });
}

function updateDistributionChart() {
  if (!charts.distribution) return;
  charts.distribution.data.datasets[0].data = [
    Number(state.stats.safe_count || 0),
    Number(state.stats.caution_count || 0),
    Number(state.stats.evacuate_count || 0),
  ];
  charts.distribution.update();
}

function setPauseState(paused) {
  state.paused = paused;
  els.topbarPauseBtn.textContent = paused ? "Resume" : "Pause";
  els.sidebarPauseBtn.textContent = paused ? "Resume" : "Pause";
  els.streamPillText.textContent = paused ? "PAUSED" : `LIVE @ row #${getLatestRowId()}`;
  els.streamDot.classList.toggle("paused", paused);
  els.streamDot.classList.remove("error");
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  els.toastRegion.appendChild(toast);
  window.setTimeout(() => {
    toast.remove();
  }, 4000);
}

function playEvacuateBeep() {
  try {
    const context = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = context.createOscillator();
    const gainNode = context.createGain();
    oscillator.frequency.value = 440;
    gainNode.gain.value = 0.3;
    oscillator.connect(gainNode);
    gainNode.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.3);
    oscillator.onended = () => context.close();
  } catch (error) {
    showToast("Audio alert could not be played.");
  }
}

function showEvacuateAlert(floorId) {
  const banner = document.createElement("div");
  banner.className = "alert-banner";
  banner.innerHTML = `
    <span>&#9888; FLOOR ${escapeHtml(floorId)} - EVACUATE IMMEDIATELY</span>
    <button type="button" aria-label="Dismiss alert">&times;</button>
  `;
  const dismiss = () => banner.remove();
  banner.querySelector("button").addEventListener("click", dismiss);
  els.alertRegion.appendChild(banner);
  playEvacuateBeep();
  window.setTimeout(dismiss, 8000);
}

function detectTransitions(nextFloors) {
  FLOOR_IDS.forEach((floorId) => {
    const previous = state.floors[floorId]?.final_state;
    const current = nextFloors[floorId]?.final_state;
    if (previous && previous !== "EVACUATE" && current === "EVACUATE") {
      showEvacuateAlert(floorId);
    }
  });
}

function applyFloors(floorRows) {
  const nextFloors = {};
  floorRows.forEach((floor) => {
    nextFloors[Number(floor.floor_id)] = floor;
  });
  detectTransitions(nextFloors);
  state.floors = nextFloors;
}

function renderAll() {
  renderFloorCards();
  renderStats();
  renderDetailPanel();
  renderIncidentFeed();
  updateTrendChart();
  updateDistributionChart();
  els.streamPillText.textContent = state.paused ? "PAUSED" : `LIVE @ row #${getLatestRowId()}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;
  if (!response.ok) {
    throw new Error(payload?.error || `Request failed: ${response.status}`);
  }
  return payload;
}

async function loadConfig() {
  const config = await fetchJson("/api/config");
  applyConfig(config);
}

async function loadHistory(limit = HISTORY_LIMIT, resetVisibleCount = false) {
  const rows = await fetchJson(`/api/history?limit=${limit}`);
  state.history = Array.isArray(rows) ? rows : [];
  if (resetVisibleCount) {
    state.historyVisibleCount = HISTORY_PAGE_SIZE;
  } else if (state.historyVisibleCount < HISTORY_PAGE_SIZE) {
    state.historyVisibleCount = HISTORY_PAGE_SIZE;
  }
}

async function loadDashboardData() {
  const [floors, stats] = await Promise.all([
    fetchJson("/api/floors"),
    fetchJson("/api/stats"),
  ]);
  applyFloors(Array.isArray(floors) ? floors : []);
  state.stats = {
    safe_count: Number(stats.safe_count || 0),
    caution_count: Number(stats.caution_count || 0),
    evacuate_count: Number(stats.evacuate_count || 0),
    total: Number(stats.total || 0),
  };
}

async function pollThingSpeakIfEnabled() {
  if (!state.ingestThingSpeak) return;
  const result = await fetchJson("/api/poll", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ingest: true,
      upload: state.uploadThingSpeak,
      floor_configs: getFloorConfigs(),
    }),
  });

  if (Array.isArray(result.errors) && result.errors.length > 0) {
    throw new Error(result.errors[0].error || "ThingSpeak polling failed.");
  }
}

async function tick() {
  if (state.paused || state.pollBusy) return;
  state.pollBusy = true;
  try {
    await pollThingSpeakIfEnabled();
    await Promise.all([
      loadDashboardData(),
      loadHistory(HISTORY_LIMIT, false),
    ]);
    renderAll();
    els.streamDot.classList.remove("error");
  } catch (error) {
    els.streamPillText.textContent = "STREAM ERROR";
    els.streamDot.classList.remove("paused");
    els.streamDot.classList.add("error");
    showToast(error.message || "Polling failed.");
  } finally {
    state.pollBusy = false;
  }
}

function restartPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
  }
  state.pollTimer = window.setInterval(() => {
    tick().catch(() => {});
  }, state.interval);
}

function syncControlStateFromInputs() {
  state.interval = Math.max(1000, Number(els.streamIntervalInput.value || 2) * 1000);
  state.ingestThingSpeak = els.ingestToggle.checked;
  state.uploadThingSpeak = els.uploadToggle.checked;
}

function wireControlInputs() {
  els.streamIntervalInput.addEventListener("change", () => {
    syncControlStateFromInputs();
    restartPolling();
  });

  els.ingestToggle.addEventListener("change", () => {
    syncControlStateFromInputs();
  });

  els.uploadToggle.addEventListener("change", () => {
    syncControlStateFromInputs();
  });

  FLOOR_IDS.forEach((floorId) => {
    const { channel, key } = els.channelInputs[floorId];
    channel.addEventListener("change", () => {
      state.channels[floorId].channel_id = channel.value.trim();
      renderFloorCards();
      renderDetailPanel();
    });
    key.addEventListener("change", () => {
      state.channels[floorId].read_api_key = key.value.trim();
    });
  });
}

function wireButtons() {
  const togglePause = () => {
    setPauseState(!state.paused);
  };

  els.topbarPauseBtn.addEventListener("click", togglePause);
  els.sidebarPauseBtn.addEventListener("click", togglePause);

  els.sidebarToggle.addEventListener("click", () => {
    const nextExpanded = !els.dashboardFrame.classList.contains("sidebar-open");
    els.dashboardFrame.classList.toggle("sidebar-open", nextExpanded);
    els.sidebarToggle.setAttribute("aria-expanded", String(nextExpanded));
  });

  els.reloadHistoryBtn.addEventListener("click", async () => {
    try {
      await Promise.all([
        loadDashboardData(),
        loadHistory(HISTORY_LIMIT, true),
      ]);
      renderAll();
    } catch (error) {
      showToast(error.message || "Snapshot reload failed.");
    }
  });

  els.loadMoreBtn.addEventListener("click", () => {
    state.historyVisibleCount += HISTORY_PAGE_SIZE;
    renderIncidentFeed();
  });

  // Event delegation keeps floor-card selection stable across frequent re-renders.
  els.floorGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".floor-card");
    if (!card) return;
    const floorId = Number(card.dataset.floorId);
    if (!FLOOR_IDS.includes(floorId)) return;
    state.selectedFloor = floorId;
    renderFloorCards();
    renderDetailPanel();
    updateTrendChart();
  });

  els.floorGrid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".floor-card");
    if (!card) return;
    event.preventDefault();
    const floorId = Number(card.dataset.floorId);
    if (!FLOOR_IDS.includes(floorId)) return;
    state.selectedFloor = floorId;
    renderFloorCards();
    renderDetailPanel();
    updateTrendChart();
  });
}

async function boot() {
  createLegend();
  syncControlStateFromInputs();
  wireControlInputs();
  wireButtons();
  initCharts();
  await loadConfig();
  await Promise.all([
    loadDashboardData(),
    loadHistory(HISTORY_LIMIT, true),
  ]);
  renderAll();
  await tick();
  restartPolling();
}

boot().catch((error) => {
  els.streamPillText.textContent = "BOOT ERROR";
  els.streamDot.classList.add("error");
  showToast(error.message || "Dashboard failed to start.");
});
