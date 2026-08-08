// ---------- Tab switching ----------
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");

    if (btn.dataset.tab === "events") loadEvents();
    if (btn.dataset.tab === "sessions") loadSessions();
  });
});

const statusBar = document.getElementById("statusBar");
function setStatus(text) { statusBar.textContent = text; }

// ---------- Live Monitoring ----------
const liveVideo = document.getElementById("liveVideo");
const liveVideoPlaceholder = document.getElementById("liveVideoPlaceholder");
const liveStartBtn = document.getElementById("liveStartBtn");
const liveStopBtn = document.getElementById("liveStopBtn");
let liveStatsTimer = null;

liveStartBtn.addEventListener("click", async () => {
  const res = await fetch("/api/live/start", { method: "POST" });
  const data = await res.json();
  if (!data.success) {
    alert(data.message || "Could not start camera.");
    return;
  }
  liveVideo.src = "/video_feed?t=" + Date.now();
  liveVideo.classList.add("visible");
  liveVideoPlaceholder.style.display = "none";
  liveStartBtn.disabled = true;
  liveStopBtn.disabled = false;
  document.getElementById("statStatus").textContent = "Running";
  document.getElementById("statStatus").className = "badge badge-on";
  liveStatsTimer = setInterval(pollLiveStats, 1000);
});

liveStopBtn.addEventListener("click", async () => {
  await fetch("/api/live/stop", { method: "POST" });
  liveVideo.src = "";
  liveVideo.classList.remove("visible");
  liveVideoPlaceholder.style.display = "flex";
  liveStartBtn.disabled = false;
  liveStopBtn.disabled = true;
  document.getElementById("statStatus").textContent = "Stopped";
  document.getElementById("statStatus").className = "badge badge-off";
  clearInterval(liveStatsTimer);
  setStatus("Live monitoring stopped.");
});

async function pollLiveStats() {
  try {
    const res = await fetch("/api/live/stats");
    const s = await res.json();
    document.getElementById("statFps").textContent = s.fps ? s.fps.toFixed(1) : "0.0";
    document.getElementById("statFaces").textContent = s.faces ?? 0;
    document.getElementById("statKnown").textContent = s.known ?? 0;
    document.getElementById("statUnknown").textContent = s.unknown ?? 0;
    document.getElementById("statSpoof").textContent = s.spoof ?? 0;
    document.getElementById("statRepeat").textContent = s.repeat ?? 0;
  } catch (e) { /* ignore transient errors */ }
}

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

// Initial load
loadEvents();