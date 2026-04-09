const FLOOR_IDS = [0, 1, 2];

const state = {
  cursorId: 0,
  rows: [],
  counts: { SAFE: 0, CAUTION: 0, EVACUATE: 0, TOTAL: 0 },
  pollTimer: null,
  pollBusy: false,
  paused: false,
  historyLimit: 300,
  floorLatest: { 0: null, 1: null, 2: null },
  selectedFloor: 0,
};

const els = {
  shell: document.getElementById("dashboard-shell"),
  dbPill: document.getElementById("db-pill"),
  livePill: document.getElementById("live-pill"),
  statusLine: document.getElementById("status-line"),
  loggedAt: document.getElementById("logged-at"),
  detailState: document.getElementById("detail-state"),
  detailTemp: document.getElementById("detail-temp"),
  detailHum: document.getElementById("detail-hum"),
  detailGas: document.getElementById("detail-gas"),
  detailSound: document.getElementById("detail-sound"),
  sourceValue: document.getElementById("source-value"),
  channelValue: document.getElementById("channel-value"),
  floorSelect: document.getElementById("floor-select"),
  rawJson: document.getElementById("raw-json"),
  countSafe: document.getElementById("count-safe"),
  countCaution: document.getElementById("count-caution"),
  countEvacuate: document.getElementById("count-evacuate"),
  countTotal: document.getElementById("count-total"),
  historyBody: document.getElementById("history-body"),
  refreshHistoryBtn: document.getElementById("refresh-history"),
  pauseBtn: document.getElementById("pause-btn"),
  streamInterval: document.getElementById("stream-interval"),
  ingestEnabled: document.getElementById("ingest-enabled"),
  uploadToggle: document.getElementById("upload-toggle"),
  floor0Channel: document.getElementById("floor0-channel"),
  floor0Key: document.getElementById("floor0-key"),
  floor1Channel: document.getElementById("floor1-channel"),
  floor1Key: document.getElementById("floor1-key"),
  floor2Channel: document.getElementById("floor2-channel"),
  floor2Key: document.getElementById("floor2-key"),
};

const floorView = {
  0: {
    card: document.getElementById("floor-card-0"),
    badge: document.getElementById("floor-badge-0"),
    temp: document.getElementById("floor-temp-0"),
    hum: document.getElementById("floor-hum-0"),
    gas: document.getElementById("floor-gas-0"),
    sound: document.getElementById("floor-sound-0"),
  },
  1: {
    card: document.getElementById("floor-card-1"),
    badge: document.getElementById("floor-badge-1"),
    temp: document.getElementById("floor-temp-1"),
    hum: document.getElementById("floor-hum-1"),
    gas: document.getElementById("floor-gas-1"),
    sound: document.getElementById("floor-sound-1"),
  },
  2: {
    card: document.getElementById("floor-card-2"),
    badge: document.getElementById("floor-badge-2"),
    temp: document.getElementById("floor-temp-2"),
    hum: document.getElementById("floor-hum-2"),
    gas: document.getElementById("floor-gas-2"),
    sound: document.getElementById("floor-sound-2"),
  },
};

function stateClass(finalState) {
  if (finalState === "SAFE") return "safe";
  if (finalState === "CAUTION") return "caution";
  if (finalState === "EVACUATE") return "evacuate";
  return "neutral";
}

function shellStateClass(finalState) {
  if (finalState === "SAFE") return "state-safe";
  if (finalState === "CAUTION") return "state-caution";
  if (finalState === "EVACUATE") return "state-evacuate";
  return "state-neutral";
}

function escapeHtml(text) {
  const value = String(text ?? "");
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmt(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return `${value}${suffix}`;
  return `${n.toFixed(2)}${suffix}`;
}

function floorConfigsFromInputs() {
  return [
    { floor_id: 0, channel_id: els.floor0Channel.value.trim(), read_api_key: els.floor0Key.value.trim() },
    { floor_id: 1, channel_id: els.floor1Channel.value.trim(), read_api_key: els.floor1Key.value.trim() },
    { floor_id: 2, channel_id: els.floor2Channel.value.trim(), read_api_key: els.floor2Key.value.trim() },
  ].filter((cfg) => cfg.channel_id);
}

function applyFloorConfigs(configs) {
  if (!Array.isArray(configs)) return;
  for (const cfg of configs) {
    if (!cfg) continue;
    const floorId = Number(cfg.floor_id);
    if (floorId === 0) {
      els.floor0Channel.value = cfg.channel_id || "";
      els.floor0Key.value = cfg.read_api_key || "";
    } else if (floorId === 1) {
      els.floor1Channel.value = cfg.channel_id || "";
      els.floor1Key.value = cfg.read_api_key || "";
    } else if (floorId === 2) {
      els.floor2Channel.value = cfg.channel_id || "";
      els.floor2Key.value = cfg.read_api_key || "";
    }
  }
}

function renderFloorCard(floorId) {
  const row = state.floorLatest[floorId];
  const view = floorView[floorId];
  if (!view) return;

  const finalState = row?.final_state || null;
  const cls = stateClass(finalState);
  view.badge.className = `badge ${cls}`;
  view.badge.textContent = finalState || "WAITING";

  view.card.classList.remove("safe", "caution", "evacuate");
  if (cls !== "neutral") view.card.classList.add(cls);

  view.temp.textContent = fmt(row?.temp_c, " C");
  view.hum.textContent = fmt(row?.hum_pct, " %");
  view.gas.textContent = `${fmt(row?.gas_a)} / ${row?.gas_d ?? "-"}`;
  view.sound.textContent = `${fmt(row?.sound_a)} / ${row?.sound_d ?? "-"}`;
}

function renderAllFloorCards() {
  for (const floorId of FLOOR_IDS) {
    renderFloorCard(floorId);
  }
}

function renderSelectedFloorDetail() {
  const floorId = Number(state.selectedFloor);
  const row = state.floorLatest[floorId];

  if (!row) {
    els.detailState.textContent = "-";
    els.loggedAt.textContent = "-";
    els.detailTemp.textContent = "-";
    els.detailHum.textContent = "-";
    els.detailGas.textContent = "-";
    els.detailSound.textContent = "-";
    els.channelValue.textContent = "-";
    els.sourceValue.textContent = "-";
    els.rawJson.textContent = "{}";
    els.statusLine.textContent = `Waiting for floor ${floorId} live data.`;
    return;
  }

  els.detailState.textContent = row.final_state || "-";
  els.loggedAt.textContent = row.logged_at_utc || "-";
  els.detailTemp.textContent = fmt(row.temp_c, " C");
  els.detailHum.textContent = fmt(row.hum_pct, " %");
  els.detailGas.textContent = `${fmt(row.gas_a)} / ${row.gas_d ?? "-"}`;
  els.detailSound.textContent = `${fmt(row.sound_a)} / ${row.sound_d ?? "-"}`;
  els.channelValue.textContent = row.channel_id || "-";
  els.sourceValue.textContent = row.source || "-";
  els.rawJson.textContent = JSON.stringify(row, null, 2);
  els.statusLine.textContent = `Floor ${floorId}: ${row.final_state || "UNKNOWN"} (row #${row.id ?? "-"})`;

  els.shell.classList.remove("state-safe", "state-caution", "state-evacuate", "state-neutral");
  els.shell.classList.add(shellStateClass(row.final_state));
}

function renderCounts() {
  els.countSafe.textContent = String(state.counts.SAFE || 0);
  els.countCaution.textContent = String(state.counts.CAUTION || 0);
  els.countEvacuate.textContent = String(state.counts.EVACUATE || 0);
  els.countTotal.textContent = String(state.counts.TOTAL || 0);
}

function renderHistory() {
  if (!Array.isArray(state.rows) || state.rows.length === 0) {
    els.historyBody.innerHTML = '<tr><td colspan="8" class="empty">No incidents yet.</td></tr>';
    return;
  }

  const html = state.rows.map((row) => {
    const cls = `${stateClass(row.final_state)}-row`;
    return `<tr class="${cls}">
      <td>${escapeHtml(row.id)}</td>
      <td>${escapeHtml(row.floor_id ?? "-")}</td>
      <td>${escapeHtml(row.logged_at_utc ?? "-")}</td>
      <td><span class="badge ${stateClass(row.final_state)}">${escapeHtml(row.final_state ?? "-")}</span></td>
      <td>${escapeHtml(row.temp_c ?? "-")}</td>
      <td>${escapeHtml(row.hum_pct ?? "-")}</td>
      <td>${escapeHtml(row.gas_a ?? "-")}</td>
      <td>${escapeHtml(row.sound_a ?? "-")}</td>
    </tr>`;
  }).join("");
  els.historyBody.innerHTML = html;
}

function recomputeFloorLatest() {
  state.floorLatest = { 0: null, 1: null, 2: null };
  for (const row of state.rows) {
    const floorId = Number(row.floor_id);
    if (!FLOOR_IDS.includes(floorId)) continue;
    if (!state.floorLatest[floorId]) {
      state.floorLatest[floorId] = row;
    }
  }
}

function maxIdFromRows(rows) {
  return rows.reduce((mx, row) => Math.max(mx, Number(row.id || 0)), 0);
}

function mergeNewRows(newRows) {
  if (!Array.isArray(newRows) || newRows.length === 0) return;
  const known = new Set(state.rows.map((row) => Number(row.id)));
  for (const row of newRows) {
    const rowId = Number(row.id || 0);
    if (rowId > 0 && !known.has(rowId)) {
      state.rows.unshift(row);
      known.add(rowId);
      const key = String(row.final_state || "").toUpperCase();
      if (key in state.counts) state.counts[key] += 1;
      state.counts.TOTAL += 1;
    }
  }
  state.rows.sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
  if (state.rows.length > state.historyLimit) {
    state.rows = state.rows.slice(0, state.historyLimit);
  }
  recomputeFloorLatest();
}

function renderAll() {
  renderCounts();
  renderHistory();
  renderAllFloorCards();
  renderSelectedFloorDetail();
}

async function loadConfig() {
  const resp = await fetch("/api/config");
  const cfg = await resp.json();
  els.dbPill.textContent = `DB: ${String(cfg.incident_log_backend || "unknown").toUpperCase()}`;
  applyFloorConfigs(cfg.floor_configs || []);
}

async function loadSnapshot() {
  const resp = await fetch("/api/history?limit=300");
  const payload = await resp.json();
  state.rows = Array.isArray(payload.recent) ? payload.recent.slice() : [];
  state.counts = {
    SAFE: Number(payload.counts?.SAFE || 0),
    CAUTION: Number(payload.counts?.CAUTION || 0),
    EVACUATE: Number(payload.counts?.EVACUATE || 0),
    TOTAL: Number(payload.counts?.TOTAL || 0),
  };
  state.cursorId = Math.max(state.cursorId, maxIdFromRows(state.rows));
  recomputeFloorLatest();
  renderAll();
}

async function ingestAllFloors() {
  if (!els.ingestEnabled.checked) return;
  const floorConfigs = floorConfigsFromInputs();
  if (floorConfigs.length === 0) return;

  const payload = {
    floor_configs: floorConfigs,
    upload: els.uploadToggle.checked,
  };
  const resp = await fetch("/api/live/poll-multi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.error || "Multi-floor ThingSpeak ingest failed.");
  }
}

async function fetchLiveDelta() {
  const query = new URLSearchParams({
    after_id: String(state.cursorId),
    limit: "300",
  });
  const resp = await fetch(`/api/live/extract?${query.toString()}`);
  if (!resp.ok) throw new Error("Live extraction failed.");
  const payload = await resp.json();

  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (rows.length > 0) {
    mergeNewRows(rows);
    renderAll();
  }

  const latestId = Number(payload.latest_id || state.cursorId);
  if (latestId > state.cursorId) state.cursorId = latestId;
  els.livePill.textContent = `Stream: Live @ id ${state.cursorId}`;
}

async function tickLive() {
  if (state.paused || state.pollBusy) return;
  state.pollBusy = true;
  try {
    await ingestAllFloors();
    await fetchLiveDelta();
  } catch (error) {
    els.livePill.textContent = "Stream: Error";
    els.statusLine.textContent = error.message;
  } finally {
    state.pollBusy = false;
  }
}

function stopLoop() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function startLoop() {
  stopLoop();
  const seconds = Math.max(1, Number(els.streamInterval.value || 2));
  state.pollTimer = setInterval(() => {
    tickLive().catch(() => {});
  }, seconds * 1000);
}

function togglePause() {
  state.paused = !state.paused;
  els.pauseBtn.textContent = state.paused ? "Resume" : "Pause";
  els.livePill.textContent = state.paused ? "Stream: Paused" : "Stream: Live";
}

function wireEvents() {
  els.pauseBtn.addEventListener("click", () => {
    togglePause();
  });

  els.refreshHistoryBtn.addEventListener("click", () => {
    loadSnapshot().catch((error) => {
      els.statusLine.textContent = error.message;
    });
  });

  els.streamInterval.addEventListener("change", () => {
    startLoop();
  });

  els.floorSelect.addEventListener("change", () => {
    state.selectedFloor = Number(els.floorSelect.value || 0);
    renderSelectedFloorDetail();
  });
}

async function boot() {
  wireEvents();
  await loadConfig();
  await loadSnapshot();
  await tickLive();
  startLoop();
}

boot().catch((error) => {
  els.statusLine.textContent = error.message;
  els.livePill.textContent = "Stream: Failed";
});
