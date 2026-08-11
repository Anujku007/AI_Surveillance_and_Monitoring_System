// ---------- Tab switching ----------
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");

    if (btn.dataset.tab === "events") loadEvents();
    if (btn.dataset.tab === "sessions") loadSessions();
    if (btn.dataset.tab === "analytics") loadAnalytics();
    if (btn.dataset.tab === "settings") loadSettings();
  });
});

const statusBar = document.getElementById("statusBar");
function setStatus(text) { statusBar.textContent = text; }

// ---------- Live Monitoring (multi-camera) ----------
const cameraGrid = document.getElementById("cameraGrid");
const cameraState = {}; // camera_id -> { statsTimer }

async function initCameras() {
  const res = await fetch("/api/cameras");
  const cameras = await res.json();

  cameras.forEach(cam => {
    const card = document.createElement("div");
    card.className = "camera-card";
    card.innerHTML = `
      <h4>${cam.name}</h4>
      <div class="video-frame">
        <img id="video-${cam.id}" class="video-img" alt="${cam.name} feed">
        <div id="placeholder-${cam.id}" class="video-placeholder">Camera feed will appear here</div>
      </div>
      <div class="controls-row">
        <button id="start-${cam.id}" class="btn btn-success">Start</button>
        <button id="stop-${cam.id}" class="btn btn-danger" disabled>Stop</button>
        <span id="badge-${cam.id}" class="badge badge-off" style="margin-left:auto;">Stopped</span>
      </div>
      <div class="stat-row"><span>FPS</span><span id="fps-${cam.id}">–</span></div>
      <div class="stat-row"><span class="dot dot-green"></span><span>Known</span><span id="known-${cam.id}">0</span></div>
      <div class="stat-row"><span class="dot dot-red"></span><span>Unknown</span><span id="unknown-${cam.id}">0</span></div>
      <div class="stat-row"><span class="dot dot-orange"></span><span>Spoof</span><span id="spoof-${cam.id}">0</span></div>
      <div class="stat-row"><span class="dot dot-magenta"></span><span>Repeat</span><span id="repeat-${cam.id}">0</span></div>
    `;
    cameraGrid.appendChild(card);
    cameraState[cam.id] = { statsTimer: null };

    document.getElementById(`start-${cam.id}`).addEventListener("click", () => startCamera(cam.id));
    document.getElementById(`stop-${cam.id}`).addEventListener("click", () => stopCamera(cam.id));
  });
}

async function startCamera(id) {
  const res = await fetch(`/api/live/start/${id}`, { method: "POST" });
  const data = await res.json();
  if (!data.success) {
    alert(data.message || "Could not start camera.");
    return;
  }
  document.getElementById(`video-${id}`).src = `/video_feed/${id}?t=` + Date.now();
  document.getElementById(`video-${id}`).classList.add("visible");
  document.getElementById(`placeholder-${id}`).style.display = "none";
  document.getElementById(`start-${id}`).disabled = true;
  document.getElementById(`stop-${id}`).disabled = false;
  document.getElementById(`badge-${id}`).textContent = "Running";
  document.getElementById(`badge-${id}`).className = "badge badge-on";
  cameraState[id].statsTimer = setInterval(() => pollCameraStats(id), 1000);
}

async function stopCamera(id) {
  await fetch(`/api/live/stop/${id}`, { method: "POST" });
  document.getElementById(`video-${id}`).src = "";
  document.getElementById(`video-${id}`).classList.remove("visible");
  document.getElementById(`placeholder-${id}`).style.display = "flex";
  document.getElementById(`start-${id}`).disabled = false;
  document.getElementById(`stop-${id}`).disabled = true;
  document.getElementById(`badge-${id}`).textContent = "Stopped";
  document.getElementById(`badge-${id}`).className = "badge badge-off";
  clearInterval(cameraState[id].statsTimer);
  setStatus(`Camera '${id}' stopped.`);
}

async function pollCameraStats(id) {
  try {
    const res = await fetch(`/api/live/stats/${id}`);
    const s = await res.json();
    document.getElementById(`fps-${id}`).textContent = s.fps ? s.fps.toFixed(1) : "0.0";
    document.getElementById(`known-${id}`).textContent = s.known ?? 0;
    document.getElementById(`unknown-${id}`).textContent = s.unknown ?? 0;
    document.getElementById(`spoof-${id}`).textContent = s.spoof ?? 0;
    document.getElementById(`repeat-${id}`).textContent = s.repeat ?? 0;

    const badge = document.getElementById(`badge-${id}`);
    if (s.reconnecting) {
      badge.textContent = "Reconnecting...";
      badge.className = "badge badge-warn";
    } else if (s.running) {
      badge.textContent = "Running";
      badge.className = "badge badge-on";
    }
  } catch (e) { /* ignore transient errors */ }
}

initCameras();

// ---------- Registration ----------
const regVideo = document.getElementById("regVideo");
const regVideoPlaceholder = document.getElementById("regVideoPlaceholder");
const regStartBtn = document.getElementById("regStartBtn");
const regCaptureBtn = document.getElementById("regCaptureBtn");
const regStopBtn = document.getElementById("regStopBtn");
const regStatus = document.getElementById("regStatus");
let regPollTimer = null;

regStartBtn.addEventListener("click", async () => {
  const name = document.getElementById("regName").value.trim();
  const id = document.getElementById("regId").value.trim();
  if (!name || !id) {
    alert("Enter at least Name and ID before starting the camera.");
    return;
  }
  const res = await fetch("/api/register/start", { method: "POST" });
  const data = await res.json();
  if (!data.success) {
    alert(data.message || "Could not start camera.");
    return;
  }
  regVideo.src = "/video_feed_register?t=" + Date.now();
  regVideo.classList.add("visible");
  regVideoPlaceholder.style.display = "none";
  regStartBtn.disabled = true;
  regCaptureBtn.disabled = false;
  regStopBtn.disabled = false;
  regPollTimer = setInterval(pollRegStatus, 500);
});

regStopBtn.addEventListener("click", async () => {
  await fetch("/api/register/stop", { method: "POST" });
  regVideo.src = "";
  regVideo.classList.remove("visible");
  regVideoPlaceholder.style.display = "flex";
  regStartBtn.disabled = false;
  regCaptureBtn.disabled = true;
  regStopBtn.disabled = true;
  regStatus.textContent = "Camera not started";
  clearInterval(regPollTimer);
});

async function pollRegStatus() {
  try {
    const res = await fetch("/api/register/status");
    const s = await res.json();
    if (s.face_count === 1) regStatus.textContent = "1 face detected — ready to capture";
    else if (s.face_count === 0) regStatus.textContent = "No face detected";
    else regStatus.textContent = `${s.face_count} faces detected — only one person should be in frame`;
  } catch (e) { /* ignore */ }
}

regCaptureBtn.addEventListener("click", async () => {
  const name = document.getElementById("regName").value.trim();
  const id = document.getElementById("regId").value.trim();
  const org = document.getElementById("regOrg").value.trim();
  if (!name || !id) {
    alert("Name and ID are required.");
    return;
  }
  const formData = new FormData();
  formData.append("name", name);
  formData.append("identifier", id);
  formData.append("organization", org);

  const res = await fetch("/api/register/capture", { method: "POST", body: formData });
  const data = await res.json();
  if (data.success) {
    alert(`Registered '${name}' successfully.`);
    document.getElementById("regName").value = "";
    document.getElementById("regId").value = "";
    document.getElementById("regOrg").value = "";
    regStopBtn.click();
  } else {
    alert(data.message || "Registration failed.");
  }
});

// ---------- Events table ----------
async function loadEvents() {
  setStatus("Loading events...");
  const res = await fetch("/api/logs/events");
  const logs = await res.json();
  const tbody = document.querySelector("#eventsTable tbody");
  tbody.innerHTML = "";

  logs.forEach(log => {
    const tr = document.createElement("tr");
    tr.className = log.is_suspicious ? "row-suspicious" : "row-known";
    tr.innerHTML = `
      <td>${log.log_id}</td>
      <td>${log.name || "Unknown"}</td>
      <td>${log.identifier || "-"}</td>
      <td>${log.event_type}</td>
      <td>${(log.timestamp || "").replace("T", "  ").slice(0, 19)}</td>
      <td>${log.camera_location}</td>
      <td>${log.is_suspicious ? "SUSPICIOUS" : "Authorized"}</td>
    `;
    tr.addEventListener("click", () => {
      document.querySelectorAll("#eventsTable tr").forEach(r => r.classList.remove("selected"));
      tr.classList.add("selected");
      showSnapshot("events", log.snapshot_file, `
Log ID: ${log.log_id}
Name: ${log.name || "Unknown"}
ID No.: ${log.identifier || "-"}
Event: ${log.event_type}
Time: ${(log.timestamp || "").replace("T", "  ").slice(0, 19)}
Location: ${log.camera_location}
Status: ${log.is_suspicious ? "SUSPICIOUS" : "Authorized"}`);
    });
    tbody.appendChild(tr);
  });
  setStatus(`Loaded ${logs.length} events.`);
}

// ---------- Sessions table ----------
async function loadSessions() {
  setStatus("Loading sessions...");
  const res = await fetch("/api/logs/sessions");
  const sessions = await res.json();
  const tbody = document.querySelector("#sessionsTable tbody");
  tbody.innerHTML = "";

  sessions.forEach(s => {
    const tr = document.createElement("tr");
    tr.className = s.is_suspicious ? "row-suspicious" : (s.still_present ? "row-present" : "row-known");
    const entryStr = s.entry_time ? s.entry_time.replace("T", "  ").slice(0, 19) : "-";
    const exitStr = s.exit_time ? s.exit_time.replace("T", "  ").slice(0, 19) : "-";
    tr.innerHTML = `
      <td>${s.log_id ?? "-"}</td>
      <td>${s.name}</td>
      <td>${s.identifier}</td>
      <td>${entryStr}</td>
      <td>${exitStr}</td>
      <td>${s.duration_str}</td>
      <td>${s.location}</td>
      <td>${s.is_suspicious ? "SUSPICIOUS" : "Authorized"}</td>
    `;
    tr.addEventListener("click", () => {
      document.querySelectorAll("#sessionsTable tr").forEach(r => r.classList.remove("selected"));
      tr.classList.add("selected");
      showSnapshot("sessions", s.snapshot_file, `
Log ID: ${s.log_id ?? "-"}
Name: ${s.name}
ID No.: ${s.identifier}
Entry: ${entryStr}
Exit: ${exitStr}
Duration: ${s.duration_str}
Location: ${s.location}
Status: ${s.is_suspicious ? "SUSPICIOUS" : "Authorized"}`);
    });
    tbody.appendChild(tr);
  });
  setStatus(`Loaded ${sessions.length} sessions.`);
}

function showSnapshot(prefix, filename, detailText) {
  const img = document.getElementById(prefix + "Snapshot");
  const detail = document.getElementById(prefix + "Detail");
  detail.textContent = detailText.trim();
  if (filename) {
    img.src = "/api/snapshot/" + encodeURIComponent(filename) + "?t=" + Date.now();
    img.classList.add("visible");
  } else {
    img.classList.remove("visible");
    img.src = "";
  }
}

// ---------- PDF report ----------
document.getElementById("reportBtn").addEventListener("click", () => {
  setStatus("Generating PDF report...");
  window.location.href = "/api/report";
  setTimeout(() => setStatus("Report ready — check your downloads."), 1500);
});

// ---------- Analytics ----------
const chartInstances = {};

function renderChart(canvasId, config) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  if (chartInstances[canvasId]) chartInstances[canvasId].destroy();
  chartInstances[canvasId] = new Chart(ctx, config);
}

const CHART_TEXT_COLOR = "#9099a8";
const CHART_GRID_COLOR = "#2a2f3a";

function baseOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: CHART_TEXT_COLOR } } },
    scales: {
      x: { ticks: { color: CHART_TEXT_COLOR }, grid: { color: CHART_GRID_COLOR } },
      y: { ticks: { color: CHART_TEXT_COLOR }, grid: { color: CHART_GRID_COLOR }, beginAtZero: true },
    },
    ...extra,
  };
}

async function loadAnalytics() {
  setStatus("Loading analytics...");
  const res = await fetch("/api/analytics");
  const data = await res.json();

  renderChart("chartEntriesPerDay", {
    type: "bar",
    data: {
      labels: data.entries_per_day.labels,
      datasets: [{ label: "Entries", data: data.entries_per_day.values, backgroundColor: "#3d8bfd" }],
    },
    options: baseOptions(),
  });

  renderChart("chartPeakHours", {
    type: "bar",
    data: {
      labels: data.peak_hours.labels,
      datasets: [{ label: "Entries", data: data.peak_hours.values, backgroundColor: "#2ecc71" }],
    },
    options: baseOptions(),
  });

  renderChart("chartAuthVsSusp", {
    type: "doughnut",
    data: {
      labels: ["Authorized", "Suspicious"],
      datasets: [{
        data: [data.authorized_vs_suspicious.authorized, data.authorized_vs_suspicious.suspicious],
        backgroundColor: ["#2ecc71", "#e74c3c"],
      }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: CHART_TEXT_COLOR } } } },
  });

  renderChart("chartReasons", {
    type: "doughnut",
    data: {
      labels: ["Unknown Face", "Spoof Suspected", "Repeat Offender"],
      datasets: [{
        data: [
          data.reason_breakdown.unknown_face || 0,
          data.reason_breakdown.spoof_suspected || 0,
          data.reason_breakdown.repeat_offender || 0,
        ],
        backgroundColor: ["#e74c3c", "#f39c12", "#e84fd0"],
      }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: CHART_TEXT_COLOR } } } },
  });

  renderChart("chartTopVisitors", {
    type: "bar",
    data: {
      labels: data.top_visitors.labels,
      datasets: [{ label: "Entries", data: data.top_visitors.values, backgroundColor: "#3d8bfd" }],
    },
    options: { ...baseOptions(), indexAxis: "y" },
  });

  setStatus("Analytics loaded.");
}

// ---------- Settings ----------
let cameraRows = [];

function renderCameraRows() {
  const container = document.getElementById("cameraSettingsList");
  container.innerHTML = "";
  cameraRows.forEach((cam, i) => {
    const row = document.createElement("div");
    row.className = "camera-row";
    row.innerHTML = `
      <input type="text" placeholder="Name (e.g. Main Entrance)" value="${cam.name}" data-field="name" data-index="${i}">
      <input type="text" placeholder="Source (0, 1, or camera URL)" value="${cam.source}" data-field="source" data-index="${i}">
      <button type="button" data-remove="${i}">Remove</button>
    `;
    container.appendChild(row);
  });

  container.querySelectorAll("input").forEach(input => {
    input.addEventListener("input", (e) => {
      const idx = parseInt(e.target.dataset.index);
      const field = e.target.dataset.field;
      cameraRows[idx][field] = e.target.value;
    });
  });
  container.querySelectorAll("button[data-remove]").forEach(btn => {
    btn.addEventListener("click", (e) => {
      cameraRows.splice(parseInt(e.target.dataset.remove), 1);
      renderCameraRows();
    });
  });
}

document.getElementById("addCameraBtn").addEventListener("click", () => {
  const nextNum = cameraRows.length + 1;
  cameraRows.push({ id: `cam${nextNum}`, name: `Camera ${nextNum}`, source: "" });
  renderCameraRows();
});

async function loadSettings() {
  setStatus("Loading settings...");
  const res = await fetch("/api/settings");
  const s = await res.json();

  cameraRows = (s.CAMERAS || []).map(c => ({ ...c }));
  renderCameraRows();

  document.getElementById("setDetectionConfidence").value = s.DETECTION_CONFIDENCE_THRESHOLD;
  document.getElementById("setFaceMatchTolerance").value = s.FACE_MATCH_TOLERANCE;
  document.getElementById("setProcessEveryN").value = s.PROCESS_EVERY_N_FRAMES;
  document.getElementById("setConfidenceMinFrames").value = s.CONFIDENCE_MIN_FRAMES;
  document.getElementById("setExitTimeout").value = s.EXIT_TIMEOUT_SECONDS;
  document.getElementById("setLogCooldown").value = s.LOG_COOLDOWN_SECONDS;
  document.getElementById("setRepeatThreshold").value = s.REPEAT_OFFENDER_THRESHOLD;
  document.getElementById("setLivenessEnabled").checked = !!s.ENABLE_LIVENESS_CHECK;
  document.getElementById("setEarThreshold").value = s.LIVENESS_EAR_THRESHOLD;
  document.getElementById("setLivenessTimeout").value = s.LIVENESS_TIMEOUT_SECONDS;
  document.getElementById("setSoundEnabled").checked = !!s.ENABLE_ALERT_SOUND;
  document.getElementById("setAlertCooldown").value = s.ALERT_COOLDOWN_SECONDS;
  document.getElementById("setEmailCooldown").value = s.EMAIL_ALERT_COOLDOWN_SECONDS;

  setStatus("Settings loaded.");
}

document.getElementById("saveSettingsBtn").addEventListener("click", async () => {
  const payload = {
    CAMERAS: cameraRows.map(c => ({
      id: c.id,
      name: c.name,
      source: isNaN(c.source) || c.source === "" ? c.source : parseInt(c.source),
    })),
    DETECTION_CONFIDENCE_THRESHOLD: parseFloat(document.getElementById("setDetectionConfidence").value),
    FACE_MATCH_TOLERANCE: parseFloat(document.getElementById("setFaceMatchTolerance").value),
    PROCESS_EVERY_N_FRAMES: parseInt(document.getElementById("setProcessEveryN").value),
    CONFIDENCE_MIN_FRAMES: parseInt(document.getElementById("setConfidenceMinFrames").value),
    EXIT_TIMEOUT_SECONDS: parseInt(document.getElementById("setExitTimeout").value),
    LOG_COOLDOWN_SECONDS: parseInt(document.getElementById("setLogCooldown").value),
    REPEAT_OFFENDER_THRESHOLD: parseInt(document.getElementById("setRepeatThreshold").value),
    ENABLE_LIVENESS_CHECK: document.getElementById("setLivenessEnabled").checked,
    LIVENESS_EAR_THRESHOLD: parseFloat(document.getElementById("setEarThreshold").value),
    LIVENESS_TIMEOUT_SECONDS: parseInt(document.getElementById("setLivenessTimeout").value),
    ENABLE_ALERT_SOUND: document.getElementById("setSoundEnabled").checked,
    ALERT_COOLDOWN_SECONDS: parseInt(document.getElementById("setAlertCooldown").value),
    EMAIL_ALERT_COOLDOWN_SECONDS: parseInt(document.getElementById("setEmailCooldown").value),
  };

  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  const msg = document.getElementById("settingsMsg");
  msg.textContent = data.message || (data.success ? "Saved." : "Failed to save.");
  msg.style.color = data.success ? "#2ecc71" : "#e74c3c";
});

// Initial load
loadEvents();