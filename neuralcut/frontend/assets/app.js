/* NeuralCut frontend — Phase 1 (vanilla JS, no build step).

Talks to the local Python backend over same-origin HTTP (FastAPI). Critical
responses are shape-validated before rendering; backend failures are surfaced
as problem details in the UI instead of silent misbehavior.
*/

"use strict";

const API_BASE = ""; // same origin: /api/v1/... (browser and Tauri sidecar modes)

class ApiError extends Error {
  constructor(message, { status, code, details, instance } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.instance = instance;
  }
}

/* ---------- validation ---------- */

function isPlainObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function requireShape(value, spec, where) {
  if (!isPlainObject(value)) {
    throw new Error(
      `expected object at ${where}, got ${value === null ? "null" : typeof value}`
    );
  }

  for (const [key, rule] of Object.entries(spec)) {
    const required =
      typeof rule === "string" ? rule === "required" : rule.required !== false;
    const expectedType = typeof rule === "string" ? null : rule.type;

    if (!(key in value)) {
      if (required) throw new Error(`missing required field "${key}" at ${where}`);
      continue;
    }

    const v = value[key];
    if (!expectedType) continue;

    const matches =
      expectedType === "array"
        ? Array.isArray(v)
        : expectedType === "object"
          ? isPlainObject(v)
          : typeof v === expectedType;

    if (!matches) {
      const actual = Array.isArray(v) ? "array" : v === null ? "null" : typeof v;
      throw new Error(
        `field "${key}" at ${where} expected ${expectedType}, got ${actual}`
      );
    }
  }

  return value;
}

/* ---------- API client ---------- */

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...opts.headers };
  let body;
  if (opts.body !== undefined) body = JSON.stringify(opts.body);

  const res = await fetch(`${API_BASE}/api/v1${path}`, { ...opts, headers, body });
  let json;
  try {
    json = await res.json();
  } catch (_) {
    json = {};
  }

  if (!res.ok) {
    const validationDetail = Array.isArray(json.detail)
      ? json.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
      : json.detail;
    const message = json.title || validationDetail || `HTTP ${res.status}`;
    throw new Error(message, {
      cause: {
        status: res.status,
        code: json.code,
        details: json.details || json.detail,
        instance: json.instance,
      },
    });
  }

  return json;
}

async function apiJson(path, opts = {}) {
  try {
    return await api(path, opts);
  } catch (err) {
    const cause = err.cause || {};
    throw new ApiError(err.message, {
      status: cause.status,
      code: cause.code,
      details: cause.details,
      instance: cause.instance,
    });
  }
}

/* ---------- UI helpers ---------- */

const navLinks = document.querySelectorAll(".nav-link");

function showView(id) {
  document.querySelectorAll(".view").forEach((el) => {
    el.style.display = "none";
  });

  const target = document.getElementById(`view-${id}`);
  if (target) target.style.display = "";

  navLinks.forEach((a) => {
    a.classList.toggle("active", a.dataset.nav === id);
  });

  if (window.location.hash !== `#${id}`) {
    window.location.hash = id;
  }

  if (id === "jobs") void loadJobs();
  if (id === "settings") void loadConfig();
  if (id === "logs") void loadLogs();
  if (id === "project") void loadCurrentProject();
  if (id === "timeline") void loadTimeline();
  if (id === "agent") void loadAgent();
  if (id === "projects") void loadRecent();
}

function nav() {
  const hash = (window.location.hash || "#dashboard").replace("#", "");
  const valid = ["dashboard", "projects", "project", "timeline", "agent", "jobs", "settings", "logs"];
  showView(valid.includes(hash) ? hash : "dashboard");
}

navLinks.forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    showView(a.dataset.nav);
  });
});
window.addEventListener("hashchange", nav);

function $el(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const el = $el(id);
  if (el) el.textContent = text;
}

function setHtml(id, html) {
  const el = $el(id);
  if (el) el.innerHTML = html;
}

function setJson(id, value) {
  const el = $el(id);
  if (!el) return;
  el.textContent =
    value === undefined || value === null ? "-" : JSON.stringify(value, null, 2);
  el.className = "code";
}

function setPill(ok) {
  const p = $el("status-pill");
  if (!p) return;
  p.className = `status-pill ${ok ? "ok" : "bad"}`;
  p.textContent = ok ? "backend reachable" : "backend unreachable";
}

function msg(id, text, kind) {
  const el = $el(id);
  if (!el) return;
  el.textContent = text;
  el.className = `msg ${kind || ""}`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

/* ---------- dashboard ---------- */

async function loadHealth() {
  try {
    const data = requireShape(
      await apiJson("/health"),
      {
        status: { type: "string" },
        service: { type: "string" },
        version: { type: "string" },
      },
      "health response"
    );
    setPill(true);
    setJson("health-out", data);
    return true;
  } catch (err) {
    setPill(false);
    setJson("health-out", {
      error: err.message,
      code: err.code,
      details: err.details,
    });
    return false;
  }
}

async function loadDiagnostics() {
  try {
    const data = requireShape(
      await apiJson("/diagnostics"),
      {
        service: { type: "string" },
        version: { type: "string" },
        phase: { type: "string" },
        media: { type: "object" },
        gpu: { type: "object" },
        models: { type: "object" },
      },
      "diagnostics response"
    );
    setJson("diagnostics-out", data);
    return data;
  } catch (err) {
    setJson("diagnostics-out", {
      error: err.message,
      code: err.code,
      details: err.details,
    });
    return null;
  }
}

/* ---------- projects ---------- */

async function loadRecent() {
  try {
    const data = requireShape(
      await apiJson("/projects"),
      { recent: { type: "array" } },
      "recent projects response"
    );

    const list = $el("recent-list");
    if (data.recent.length === 0) {
      list.innerHTML = '<div class="list empty">No recent projects.</div>';
    } else {
      list.innerHTML = data.recent
        .map(
          (p) => `
            <div style="padding:8px 12px;border-bottom:1px solid var(--panel-border);font-size:13px;">
              <div style="font-weight:600">${escapeHtml(p.name)}</div>
              <div style="color:var(--muted)">${escapeHtml(p.path)} ${
                p.exists
                  ? ""
                  : "<span style='color:var(--danger)'>[missing]</span>"
              }</div>
            </div>`
        )
        .join("");
    }
  } catch (err) {
    setHtml(
      "recent-list",
      `<div class="list empty">Error: ${escapeHtml(err.message)}</div>`
    );
  }
}

async function loadCurrentProject() {
  try {
    const data = await apiJson("/projects/current");
    if (!isPlainObject(data)) {
      throw new Error("current project response must be an object");
    }

    if (data.status === "none") {
      setText("project-name", "(none)");
      setJson("project-json", { status: "no project open" });
      return;
    }

    requireShape(
      data,
      {
        id: { type: "string" },
        name: { type: "string" },
        version: { type: "number" },
        asset_count: { type: "number" },
        clip_count: { type: "number" },
      },
      "current project response"
    );

    setText("project-name", data.name);
    setJson("project-json", data);
  } catch (err) {
    setJson("project-json", {
      error: err.message,
      code: err.code,
      details: err.details,
    });
  }
}

async function handleCreateProject(form) {
  const fd = new FormData(form);
  const body = { name: fd.get("name"), directory: fd.get("directory") };

  try {
    const created = await apiJson("/projects/create", { method: "POST", body });
    msg("create-msg", `Created "${created.name}" (v${created.version})`, "ok");
    form.reset();
    await loadRecent();
    await loadCurrentProject();
    showView("project");
  } catch (err) {
    msg("create-msg", err.message, "err");
  }
}

async function handleOpenProject(form) {
  const fd = new FormData(form);

  try {
    const opened = await apiJson("/projects/open", {
      method: "POST",
      body: { path: fd.get("path") },
    });
    msg("open-msg", `Opened "${opened.name}"`, "ok");
    await loadCurrentProject();
    await loadRecent();
    showView("project");
  } catch (err) {
    msg("open-msg", err.message, "err");
  }
}

/* ---------- jobs ---------- */

const JOB_STATUS_COLOR = {
  queued: "var(--muted)",
  running: "var(--warn)",
  completed: "var(--ok)",
  failed: "var(--danger)",
  cancelled: "var(--muted)",
};

async function loadJobs() {
  try {
    const data = requireShape(
      await apiJson("/jobs"),
      { jobs: { type: "array" } },
      "jobs response"
    );

    const list = $el("jobs-list");
    if (data.jobs.length === 0) {
      list.innerHTML = '<div class="list empty">No jobs.</div>';
    } else {
      list.innerHTML = data.jobs.map(renderJob).join("");
    }
  } catch (err) {
    $el("jobs-list").innerHTML =
      `<div class="list empty">Error: ${escapeHtml(err.message)}</div>`;
  }
}

function renderJob(j) {
  const pct = Math.max(0, Math.min(100, j.progress ?? 0));
  const statusColor = JOB_STATUS_COLOR[j.status] || "var(--muted)";
  const details =
    j.details && Object.keys(j.details).length
      ? `<div style="color:var(--muted);font-size:11px;margin-top:4px">${escapeHtml(
          JSON.stringify(j.details)
        )}</div>`
      : "";
  const err = j.error
    ? `<div style="color:var(--danger);font-size:12px;margin-top:4px">${escapeHtml(
        j.error
      )}</div>`
    : "";

  let controls = "";
  if (j.status === "queued" || j.status === "running") {
    controls = `<button class="btn" data-cancel-job="${escapeHtml(
      j.id
    )}" style="color:var(--danger)">Cancel</button>`;
  }

  return `
    <div class="job-row" id="job-${escapeHtml(j.id)}">
      <div class="head">
        <span class="name">${escapeHtml(j.name)}</span>
        <span class="meta" style="color:${statusColor}">${escapeHtml(j.status)}</span>
        <span class="meta">${escapeHtml(j.type)}</span>
      </div>
      <div class="meta">${escapeHtml(j.progress_message ?? "")} · created ${new Date(
        j.created_at ?? 0
      ).toLocaleString()}</div>
      <div class="progress"><div class="fill ${
        (j.status === "completed" && "done") ||
        (j.status === "failed" && "err") ||
        ""
      }" style="width:${pct}%"></div></div>
      <div class="controls">${controls}</div>
      ${details}${err}
    </div>
  `;
}

async function submitDemoJob(form) {
  const fd = new FormData(form);
  const body = {
    type: "demo",
    name: fd.get("name") || "Demo job",
    payload: {
      steps: parseInt(fd.get("steps") || "5", 10),
      delay: parseFloat(fd.get("delay") || "0.3"),
    },
  };

  try {
    await apiJson("/jobs", { method: "POST", body });
    msg("job-msg", "Job submitted", "ok");
    form.reset();
    await loadJobs();
  } catch (err) {
    msg("job-msg", err.message, "err");
  }
}

async function cancelJob(jobId) {
  try {
    await apiJson(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    });
    await loadJobs();
  } catch (err) {
    alert("Cancel failed: " + err.message);
  }
}

/* ---------- settings ---------- */

async function loadConfig() {
  try {
    const data = requireShape(
      await apiJson("/config"),
      {
        app_name: { type: "string" },
        version: { type: "string" },
        logging: { type: "object" },
        jobs: { type: "object" },
        media: { type: "object" },
        models: { type: "object" },
        ui: { type: "object" },
      },
      "config response"
    );
    setJson("config-out", data);
  } catch (err) {
    setJson("config-out", {
      error: err.message,
      code: err.code,
      details: err.details,
    });
  }
}

/* ---------- logs ---------- */

async function loadLogs() {
  const lines = $el("sel-log-lines").value;

  try {
    const data = requireShape(
      await apiJson(`/logs?lines=${encodeURIComponent(lines)}`),
      { lines: { type: "array" }, file: { type: "string" } },
      "logs response"
    );

    const out = $el("logs-out");
    if (data.error) {
      out.textContent = `error reading log: ${data.error}`;
      out.className = "code note";
    } else if (!data.lines || data.lines.length === 0) {
      out.textContent = "(no log lines yet)";
      out.className = "code note";
    } else {
      out.textContent = data.lines.join("\n");
      out.className = "code";
      out.scrollTop = out.scrollHeight;
    }
  } catch (err) {
    $el("logs-out").textContent = `error: ${err.message}`;
    $el("logs-out").className = "code note";
  }
}

/* ---------- boot ---------- */

async function boot() {
  nav();

  const ok = await loadHealth();
  if (ok) await loadDiagnostics();
  await loadRecent();
  await loadCurrentProject();

  setInterval(async () => {
    const active = window.location.hash.replace("#", "") || "dashboard";
    if (active === "jobs") await loadJobs();
    if (active === "dashboard") await loadHealth();
  }, 3000);

  $el("form-create")?.addEventListener("submit", (e) => {
    e.preventDefault();
    void handleCreateProject(e.target);
  });
  $el("form-open")?.addEventListener("submit", (e) => {
    e.preventDefault();
    void handleOpenProject(e.target);
  });
  $el("form-job")?.addEventListener("submit", (e) => {
    e.preventDefault();
    void submitDemoJob(e.target);
  });

  $el("btn-check-health")?.addEventListener("click", loadHealth);
  $el("btn-refresh-project")?.addEventListener("click", loadCurrentProject);
  $el("btn-save-project")?.addEventListener("click", async () => {
    try {
      const saved = await apiJson("/projects/save", { method: "POST" });
      msg("project-msg", `Saved to ${saved.path}`, "ok");
      await loadCurrentProject();
    } catch (err) {
      msg("project-msg", err.message, "err");
    }
  });
  $el("btn-refresh-logs")?.addEventListener("click", loadLogs);
  $el("sel-log-lines")?.addEventListener("change", loadLogs);
  $el("jobs-list")?.addEventListener("click", (e) => {
    const button = e.target.closest("[data-cancel-job]");
    if (button) void cancelJob(button.dataset.cancelJob);
  });


  /* ----- Phase 2 timeline wiring ----- */
  $el("form-import")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await timelineCall("/projects/current/assets/import", {
        method: "POST", body: { path: fd.get("path") },
      });
      msg("timeline-msg", "Media imported and probed.", "ok");
      e.target.reset();
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });

  $el("asset-list")?.addEventListener("click", async (e) => {
    const add = e.target.closest("[data-add-clip]");
    const remove = e.target.closest("[data-remove-asset]");
    const analyze = e.target.closest("[data-analyze-asset]");
    const view = e.target.closest("[data-view-analysis]");
    if (analyze) { try { await analyzeAsset(analyze.dataset.analyzeAsset); } catch (err) { msg("timeline-msg", err.message, "err"); } return; }
    if (view) { await viewAnalysis(view.dataset.viewAnalysis); return; }
    try {
      if (add) {
        const data = await timelineCall("/projects/current/clips", {
          method: "POST", body: { asset_id: add.dataset.addClip },
        });
        selectedClipId = data.clip.id;
        renderTimeline();
        msg("timeline-msg", "Clip added at the end of track 0.", "ok");
      }
      if (remove) {
        await timelineCall(`/projects/current/assets/${encodeURIComponent(remove.dataset.removeAsset)}`, { method: "DELETE" });
        msg("timeline-msg", "Asset removed from project (source file untouched).", "ok");
      }
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });

  $el("sel-source-asset")?.addEventListener("change", updateSourcePreview);

  const tracksEl = $el("timeline-tracks");
  tracksEl?.addEventListener("click", (e) => {
    const clipEl = e.target.closest("[data-clip]");
    if (clipEl) { selectedClipId = clipEl.dataset.clip; renderClipEditor();
      document.querySelectorAll(".clip").forEach((el) => el.classList.toggle("selected", el.dataset.clip === selectedClipId)); }
  });

  // Drag clips horizontally to move them.
  let drag = null;
  tracksEl?.addEventListener("pointerdown", (e) => {
    const clipEl = e.target.closest("[data-clip]");
    if (!clipEl || !timelineState) return;
    const track = clipEl.parentElement;
    drag = { clipEl, track, startX: e.clientX, moved: false };
    clipEl.setPointerCapture?.(e.pointerId);
  });
  tracksEl?.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.startX;
    if (Math.abs(dx) > 3) drag.moved = true;
    if (drag.moved) drag.clipEl.style.transform = `translateX(${dx}px)`;
  });
  tracksEl?.addEventListener("pointerup", async (e) => {
    if (!drag) return;
    const { clipEl, track, startX, moved } = drag;
    drag = null;
    clipEl.style.transform = "";
    if (!moved || !timelineState) return;
    const clip = timelineState.clips.find((c) => c.id === clipEl.dataset.clip);
    if (!clip) return;
    const width = track.getBoundingClientRect().width || 1;
    const duration = Math.max(timelineState.duration_seconds, 1);
    const deltaSeconds = ((e.clientX - startX) / width) * duration;
    const newStart = Math.max(0, Math.round((clip.timeline_start_seconds + deltaSeconds) * 10) / 10);
    try {
      await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}`, {
        method: "PATCH", body: { timeline_start_seconds: newStart },
      });
      msg("timeline-msg", `Moved clip to ${newStart.toFixed(1)}s.`, "ok");
    } catch (err) { msg("timeline-msg", err.message, "err"); renderTimeline(); }
  });

  $el("btn-undo")?.addEventListener("click", async () => {
    try { await timelineCall("/projects/current/undo", { method: "POST" }); msg("timeline-msg", "Undone.", "ok"); }
    catch (err) { msg("timeline-msg", err.message, "err"); }
  });
  $el("btn-redo")?.addEventListener("click", async () => {
    try { await timelineCall("/projects/current/redo", { method: "POST" }); msg("timeline-msg", "Redone.", "ok"); }
    catch (err) { msg("timeline-msg", err.message, "err"); }
  });
  $el("btn-save-timeline")?.addEventListener("click", async () => {
    try {
      const saved = await apiJson("/projects/save", { method: "POST" });
      msg("timeline-msg", `Saved to ${saved.path}`, "ok");
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });

  $el("btn-edited-play")?.addEventListener("click", () => {
    if (editedPlayback.playing) { stopEditedPlayback(); return; }
    const seek = parseFloat($el("edited-seek").value || "0");
    playEditedFrom(Number.isFinite(seek) ? seek : 0);
  });
  $el("edited-video")?.addEventListener("timeupdate", editedTimeUpdate);
  $el("edited-video")?.addEventListener("pause", () => {
    if (editedPlayback.playing && $el("edited-video").ended) stopEditedPlayback();
  });
  $el("edited-seek")?.addEventListener("input", (e) => {
    const time = parseFloat(e.target.value || "0");
    setText("edited-time", `${time.toFixed(1)}s / ${fmtTime(timelineState?.duration_seconds || 0)}`);
    if (editedPlayback.playing) playEditedFrom(time);
  });

  $el("form-export")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const data = await apiJson("/projects/current/render", {
        method: "POST",
        body: {
          output_path: fd.get("output_path"),
          width: parseInt(fd.get("width"), 10),
          height: parseInt(fd.get("height"), 10),
          fps: parseFloat(fd.get("fps")),
        },
      });
      const jobId = data.job.id;
      setHtml("export-job", `<p class="muted">Export job ${escapeHtml(jobId)} queued…</p>`);
      msg("timeline-msg", "Export started as a background job (see Background Jobs).", "ok");
      const timer = setInterval(async () => {
        try {
          const job = await apiJson(`/jobs/${encodeURIComponent(jobId)}`);
          setHtml("export-job", `<div>${renderJob(job)}</div>`);
          if (["completed", "failed", "cancelled"].includes(job.status)) clearInterval(timer);
        } catch (_) { clearInterval(timer); }
      }, 1000);
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });

  $el("source-video")?.addEventListener("timeupdate", drawTrackOverlay);
  $el("source-video")?.addEventListener("seeked", drawTrackOverlay);
  $el("btn-analyze-selected")?.addEventListener("click", async () => {
    const assetId = $el("sel-source-asset")?.value;
    if (!assetId) { msg("timeline-msg", "Import and select an asset first.", "err"); return; }
    try { await analyzeAsset(assetId); } catch (err) { msg("timeline-msg", err.message, "err"); }
  });

  $el("form-agent")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const plan = await apiJson("/agent/chat", { method: "POST", body: { message: fd.get("message") } });
      msg("agent-msg", plan.status === "needs_clarification" ? "The agent needs clarification (see plan)." :
        plan.risk === "read" ? "Answered." : "Plan drafted — review and approve below.", plan.status === "needs_clarification" ? "err" : "ok");
      e.target.reset();
      await loadAgent();
      if (plan.risk === "read" && typeof loadTimeline === "function") void loadTimeline();
    } catch (err) { msg("agent-msg", err.message, "err"); }
  });
  $el("agent-plans")?.addEventListener("click", (e) => {
    const approve = e.target.closest("[data-plan-approve]");
    const reject = e.target.closest("[data-plan-reject]");
    const undo = e.target.closest("[data-plan-undo]");
    if (approve) void agentPlanAction("approve", approve.dataset.planApprove);
    if (reject) void agentPlanAction("reject", reject.dataset.planReject);
    if (undo) void agentPlanAction("undo", undo.dataset.planUndo);
  });

  setText("api-url", API_BASE || window.location.origin);
}

document.addEventListener("DOMContentLoaded", boot);

/* ---------- timeline / editing (Phase 2) ---------- */

let timelineState = null;
let selectedClipId = null;
let editedPlayback = { playing: false, raf: null };

function fmtTime(v) {
  return `${Number(v || 0).toFixed(2)}s`;
}

function sortedTimelineClips() {
  if (!timelineState) return [];
  return [...timelineState.clips].sort(
    (a, b) => a.timeline_start_seconds - b.timeline_start_seconds || a.track - b.track
  );
}

async function timelineCall(path, opts = {}) {
  const data = await apiJson(path, opts);
  if (data.timeline) {
    timelineState = data.timeline;
    renderTimeline();
  }
  return data;
}

async function loadTimeline() {
  try {
    timelineState = await apiJson("/projects/current/timeline");
    renderTimeline();
    msg("timeline-msg", "", "");
  } catch (err) {
    timelineState = null;
    msg("timeline-msg", `No project open or timeline unavailable: ${err.message}`, "err");
    setHtml("asset-list", '<div class="list empty">Open or create a project first (Projects view).</div>');
    setHtml("timeline-tracks", "");
    setHtml("clip-editor", "");
  }
}

function renderTimeline() {
  if (!timelineState) return;
  setText("timeline-duration", `— duration ${fmtTime(timelineState.duration_seconds)}`);
  $el("btn-undo").disabled = !timelineState.history.can_undo;
  $el("btn-redo").disabled = !timelineState.history.can_redo;

  // Assets
  const assets = timelineState.assets;
  if (!assets.length) {
    setHtml("asset-list", '<div class="list empty">No media imported yet.</div>');
  } else {
    setHtml("asset-list", assets.map((a) => `
      <div class="asset-row">
        <div>
          <strong>${escapeHtml(a.name)}</strong>
          <span class="muted">${escapeHtml(a.path)}</span>
          <span class="muted">${a.width && a.height ? `${a.width}×${a.height}` : "unknown size"} · ${fmtTime(a.duration_seconds)} · ${a.codec || "unknown codec"}${a.has_audio ? " · audio" : " · no audio"}</span>
          ${a.missing ? '<span class="missing">SOURCE FILE MISSING</span>' : ""}
        </div>
        <div class="controls">
          <button class="btn" data-add-clip="${escapeHtml(a.id)}" ${a.missing ? "disabled" : ""}>Add to timeline</button>
          <button class="btn" data-analyze-asset="${escapeHtml(a.id)}" ${a.missing ? "disabled" : ""}>Analyze</button>
          <button class="btn" data-view-analysis="${escapeHtml(a.id)}" ${a.missing ? "disabled" : ""}>View analysis</button>
          <button class="btn" data-remove-asset="${escapeHtml(a.id)}">Remove</button>
        </div>
      </div>`).join(""));
  }
  const sel = $el("sel-source-asset");
  const previous = sel.value;
  sel.innerHTML = assets.map((a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}</option>`).join("");
  if (assets.some((a) => a.id === previous)) sel.value = previous;
  updateSourcePreview();

  // Tracks
  const duration = Math.max(timelineState.duration_seconds, 1);
  const tracks = new Map();
  for (const clip of timelineState.clips) {
    if (!tracks.has(clip.track)) tracks.set(clip.track, []);
    tracks.get(clip.track).push(clip);
  }
  if (!tracks.size) tracks.set(0, []);
  setHtml("timeline-tracks", [...tracks.entries()].sort((a, b) => a[0] - b[0]).map(([track, clips]) => `
    <div class="track-label">Track ${track}</div>
    <div class="track" data-track="${track}">
      ${clips.map((clip) => {
        const left = (clip.timeline_start_seconds / duration) * 100;
        const width = Math.max((clip.duration_seconds / duration) * 100, 2);
        return `<div class="clip ${clip.id === selectedClipId ? "selected" : ""} ${clip.asset_missing ? "missing" : ""}"
          data-clip="${escapeHtml(clip.id)}" style="left:${left}%;width:${width}%"
          title="${escapeHtml(clip.name)}">${escapeHtml(clip.name)} · ${fmtTime(clip.duration_seconds)}</div>`;
      }).join("")}
    </div>`).join(""));

  // Seek range mirrors the edited preview
  const seek = $el("edited-seek");
  seek.max = String(Math.max(timelineState.duration_seconds, 0.1));
  setText("edited-time", `0.0s / ${fmtTime(timelineState.duration_seconds)}`);

  renderClipEditor();
}

function renderClipEditor() {
  const box = $el("clip-editor");
  if (!timelineState) { box.innerHTML = ""; return; }
  const clip = timelineState.clips.find((c) => c.id === selectedClipId);
  if (!clip) {
    box.innerHTML = '<p class="muted">Select a clip on the timeline to move, trim, split, or remove it.</p>';
    return;
  }
  box.innerHTML = `
    <form id="form-clip-edit" class="clip-form">
      <h4>${escapeHtml(clip.name)}</h4>
      <div class="field"><label>Timeline start (s)</label><input type="number" step="0.1" min="0" name="timeline_start_seconds" value="${clip.timeline_start_seconds}"></div>
      <div class="field"><label>Track</label><input type="number" step="1" min="0" name="track" value="${clip.track}"></div>
      <div class="field"><label>Source in (s)</label><input type="number" step="0.1" min="0" name="source_start_seconds" value="${clip.source_start_seconds}"></div>
      <div class="field"><label>Source out (s)</label><input type="number" step="0.1" min="0" name="source_end_seconds" value="${clip.source_end_seconds}"></div>
      <div class="field"><label>Split at timeline time (s)</label><input type="number" step="0.1" min="0" name="split_at" value="${(clip.timeline_start_seconds + clip.duration_seconds / 2).toFixed(2)}"></div>
      <div class="controls">
        <button class="btn" type="submit">Apply move/trim</button>
        <button class="btn" type="button" id="btn-split-clip">Split</button>
        <button class="btn" type="button" id="btn-remove-clip" style="color:var(--danger)">Remove clip</button>
      </div>
    </form>`;
  box.insertAdjacentHTML("beforeend", renderEffectsEditor(clip));
  void wireEffectsEditor(clip);
  $el("form-clip-edit").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}`, {
        method: "PATCH",
        body: {
          timeline_start_seconds: parseFloat(fd.get("timeline_start_seconds")),
          track: parseInt(fd.get("track"), 10),
          source_start_seconds: parseFloat(fd.get("source_start_seconds")),
          source_end_seconds: parseFloat(fd.get("source_end_seconds")),
        },
      });
      msg("timeline-msg", "Clip updated.", "ok");
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });
  $el("btn-split-clip").addEventListener("click", async () => {
    const fd = new FormData($el("form-clip-edit"));
    try {
      await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/split`, {
        method: "POST", body: { at_timeline_seconds: parseFloat(fd.get("split_at")) },
      });
      msg("timeline-msg", "Clip split.", "ok");
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });
  $el("btn-remove-clip").addEventListener("click", async () => {
    try {
      selectedClipId = null;
      await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}`, { method: "DELETE" });
      msg("timeline-msg", "Clip removed.", "ok");
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });
}

function updateSourcePreview() {
  const sel = $el("sel-source-asset");
  const video = $el("source-video");
  if (!sel || !video) return;
  const assetId = sel.value;
  if (!assetId) { video.removeAttribute("src"); return; }
  const url = `/api/v1/media/assets/${encodeURIComponent(assetId)}/content`;
  if (!video.src.endsWith(url)) {
    video.src = url;
    video.load();
  }
}

/* Edited preview: play clips back-to-back from their source ranges. */
function clipAtTimelineTime(time) {
  return sortedTimelineClips().find(
    (c) => time >= c.timeline_start_seconds && time < c.timeline_end_seconds
  ) || null;
}

function playEditedFrom(time) {
  const video = $el("edited-video");
  const clip = clipAtTimelineTime(time) ||
    sortedTimelineClips().find((c) => c.timeline_start_seconds >= time);
  if (!clip) { editedPlayback.playing = false; setText("btn-edited-play", "▶ Play timeline"); return; }
  editedPlayback.playing = true;
  setText("btn-edited-play", "⏸ Pause timeline");
  editedPlayback.clipId = clip.id;
  const offset = Math.max(0, time - clip.timeline_start_seconds);
  const url = `/api/v1/media/assets/${encodeURIComponent(clip.asset_id)}/content`;
  const startPlayback = () => {
    video.currentTime = clip.source_start_seconds + offset;
    void video.play();
  };
  if (!video.src.endsWith(url)) {
    video.src = url;
    video.addEventListener("loadedmetadata", startPlayback, { once: true });
    video.load();
  } else {
    startPlayback();
  }
}

function stopEditedPlayback() {
  editedPlayback.playing = false;
  $el("edited-video").pause();
  setText("btn-edited-play", "▶ Play timeline");
}

function editedTimeUpdate() {
  const video = $el("edited-video");
  if (!editedPlayback.playing || !editedPlayback.clipId || !timelineState) return;
  const clip = timelineState.clips.find((c) => c.id === editedPlayback.clipId);
  if (!clip) return;
  const timelineTime = clip.timeline_start_seconds + (video.currentTime - clip.source_start_seconds);
  // Preview approximation of the effect chain (export renders it exactly):
  const localT = video.currentTime - clip.source_start_seconds;
  let filter = "", opacity = 1;
  for (const effect of (clip.effects || [])) {
    if (!effect.enabled) continue;
    const v = (name) => evaluatedEffectValue(effect, name, localT);
    if (effect.type === "color") filter += ` brightness(${1 + v("brightness")}) contrast(${v("contrast")}) saturate(${v("saturation")})`;
    if (effect.type === "blur") filter += ` blur(${v("radius") / 4}px)`;
    if (effect.type === "glow" || effect.type === "bloom") filter += ` brightness(${1 + v("strength") * 0.3})`;
    if (effect.type === "transform") opacity = v("opacity");
  }
  video.style.filter = filter || "";
  video.style.opacity = String(opacity);
  $el("edited-seek").value = String(Math.min(timelineTime, timelineState.duration_seconds));
  setText("edited-time", `${timelineTime.toFixed(1)}s / ${fmtTime(timelineState.duration_seconds)}`);
  if (video.currentTime >= clip.source_end_seconds - 0.05 || video.ended) {
    const next = sortedTimelineClips().find(
      (c) => c.timeline_start_seconds >= clip.timeline_end_seconds - 1e-6 && c.id !== clip.id
    );
    if (next) playEditedFrom(next.timeline_start_seconds);
    else stopEditedPlayback();
  }
}

/* ---------- Phase 3 analysis ---------- */

let analysisState = { assetId: null, artifact: null };
const EFFECT_TYPES = ["transform", "color", "blur", "glow", "bloom"];
const EFFECT_PARAMS = {
  transform: ["opacity", "scale", "x", "y"],
  color: ["brightness", "contrast", "saturation"],
  blur: ["radius"],
  glow: ["strength", "radius"],
  bloom: ["strength", "radius", "threshold"],
};

async function analyzeAsset(assetId) {
  msg("timeline-msg", "Analysis job submitted…", "");
  const data = await apiJson(`/projects/current/assets/${encodeURIComponent(assetId)}/analyze`, {
    method: "POST", body: { force: false },
  });
  const jobId = data.job.id;
  setText("analysis-status", `Analysis running (job ${jobId})…`);
  const timer = setInterval(async () => {
    try {
      const job = await apiJson(`/jobs/${encodeURIComponent(jobId)}`);
      setText("analysis-status", `Analysis: ${job.status} ${job.progress_message || ""} (${Math.round(job.progress)}%)`);
      if (["completed", "failed", "cancelled"].includes(job.status)) {
        clearInterval(timer);
        if (job.status === "completed") await viewAnalysis(assetId);
        else msg("timeline-msg", `Analysis ${job.status}: ${job.error || ""}`, "err");
      }
    } catch (_) { clearInterval(timer); }
  }, 1000);
}

async function viewAnalysis(assetId) {
  try {
    const artifact = await apiJson(`/projects/current/assets/${encodeURIComponent(assetId)}/analysis/artifacts`);
    analysisState = { assetId, artifact };
    renderAnalysis();
  } catch (err) {
    setText("analysis-status", `No artifacts yet: ${err.message}`);
    setHtml("analysis-results", "");
    analysisState = { assetId, artifact: null };
  }
}

function renderAnalysis() {
  const a = analysisState.artifact;
  if (!a) return;
  setText("analysis-status",
    `Analyzed ${new Date(a.analyzed_at).toLocaleString()} · ${a.shots.length} shot(s) · ${a.tracks.length} track(s) · transcript: ${a.transcript.status}`);
  const tracks = a.tracks.map((tr) => {
    const frames = tr.frames.map((f) => `${f.time_seconds.toFixed(1)}s`).join(", ");
    return `<div class="effect-row"><strong>${escapeHtml(tr.id)}</strong> ${escapeHtml(tr.label)}
      <span class="muted">${tr.start_seconds.toFixed(1)}s–${tr.end_seconds.toFixed(1)}s · displacement ${(tr.displacement * 100).toFixed(0)}% of frame · masks ${tr.mask_resolution.join("×")} (RLE)</span>
      <div class="muted">frames: ${escapeHtml(frames)}</div></div>`;
  }).join("") || '<p class="muted">No moving objects tracked.</p>';
  const shots = a.shots.map((s) =>
    `<span class="track-chip">#${s.index + 1} ${s.start_seconds.toFixed(1)}–${s.end_seconds.toFixed(1)}s · ${escapeHtml(s.dominant_color)} · motion ${s.motion_level}</span>`).join("");
  const speech = a.speech_segments.map((s) =>
    `<span class="track-chip">${s.start_seconds.toFixed(1)}–${s.end_seconds.toFixed(1)}s</span>`).join("") || "none";
  const transcript = a.transcript.status === "ready"
    ? a.transcript.segments.map((s) => `<div>${s.start_seconds.toFixed(1)}s ${escapeHtml(s.text)}</div>`).join("")
    : `<span class="muted">unavailable — ${escapeHtml(a.transcript.reason || "")}</span>`;
  setHtml("analysis-results", `
    <h4>Object tracks (drawn on the source preview)</h4>${tracks}
    <h4>Shots</h4><div>${shots}</div>
    <h4>Speech segments</h4><div>${speech}</div>
    <h4>Transcript</h4><div>${transcript}</div>`);
  drawTrackOverlay();
}

function drawTrackOverlay() {
  const canvas = $el("track-overlay");
  const video = $el("source-video");
  if (!canvas || !video) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const a = analysisState.artifact;
  if (!a || analysisState.assetId !== $el("sel-source-asset")?.value) return;
  const time = video.currentTime || 0;
  ctx.lineWidth = 3;
  ctx.font = "20px sans-serif";
  for (const tr of a.tracks) {
    let best = null;
    for (const f of tr.frames) {
      if (!best || Math.abs(f.time_seconds - time) < Math.abs(best.time_seconds - time)) best = f;
    }
    if (!best || Math.abs(best.time_seconds - time) > 0.35) continue;
    const [x, y, w, h] = best.bbox;
    ctx.strokeStyle = "#4da3ff";
    ctx.fillStyle = "#4da3ff";
    ctx.strokeRect(x * canvas.width, y * canvas.height, w * canvas.width, h * canvas.height);
    ctx.fillText(`${tr.id} ${tr.label}`, x * canvas.width, Math.max(20, y * canvas.height - 6));
  }
}

/* ---------- Phase 4 effects ---------- */

function evaluatedEffectValue(effect, param, t) {
  let value = effect.params?.[param] ?? 0;
  const frames = effect.keyframes?.[param];
  if (frames && frames.length) {
    const sorted = [...frames].sort((a, b) => a.time_seconds - b.time_seconds);
    if (t <= sorted[0].time_seconds) value = sorted[0].value;
    else if (t >= sorted[sorted.length - 1].time_seconds) value = sorted[sorted.length - 1].value;
    else for (let i = 0; i + 1 < sorted.length; i++) {
      const prev = sorted[i], cur = sorted[i + 1];
      if (t >= prev.time_seconds && t <= cur.time_seconds) {
        value = cur.interpolation === "hold" ? prev.value
          : prev.value + (cur.value - prev.value) * ((t - prev.time_seconds) / Math.max(cur.time_seconds - prev.time_seconds, 1e-9));
        break;
      }
    }
  }
  return value;
}

function renderEffectsEditor(clip) {
  const effects = clip.effects || [];
  const rows = effects.map((e, idx) => {
    const params = (EFFECT_PARAMS[e.type] || []).map((name) =>
      `<label>${name} <input type="number" step="0.05" data-param="${name}" value="${e.params?.[name] ?? ""}"></label>`).join(" ");
    const keyframes = Object.entries(e.keyframes || {}).map(([prop, frames]) =>
      `<div class="muted">${escapeHtml(prop)}: ${frames.map((f) => `${f.time_seconds}s→${f.value} (${f.interpolation})`).join(", ")}</div>`).join("");
    return `<div class="effect-row" data-effect="${escapeHtml(e.id)}">
      <strong>${escapeHtml(e.type)}</strong> ${e.enabled ? "" : '<span class="muted">(disabled)</span>'}
      <div class="controls">${params}<button class="btn" data-fx-apply="${escapeHtml(e.id)}">Apply params</button></div>
      <div class="controls">
        <button class="btn" data-fx-toggle="${escapeHtml(e.id)}">${e.enabled ? "Disable" : "Enable"}</button>
        <button class="btn" data-fx-up="${escapeHtml(e.id)}" ${idx === 0 ? "disabled" : ""}>↑</button>
        <button class="btn" data-fx-down="${escapeHtml(e.id)}" ${idx === effects.length - 1 ? "disabled" : ""}>↓</button>
        <button class="btn" data-fx-delete="${escapeHtml(e.id)}" style="color:var(--danger)">Delete</button>
      </div>
      <div class="controls">
        <label>Keyframe property <select data-kf-prop="${escapeHtml(e.id)}">${(EFFECT_PARAMS[e.type] || []).map((n) => `<option>${n}</option>`).join("")}</select></label>
        <label>at (clip s) <input type="number" step="0.1" min="0" value="0" data-kf-time="${escapeHtml(e.id)}"></label>
        <label>value <input type="number" step="0.05" value="1" data-kf-value="${escapeHtml(e.id)}"></label>
        <select data-kf-interp="${escapeHtml(e.id)}"><option>linear</option><option>hold</option></select>
        <button class="btn" data-kf-add="${escapeHtml(e.id)}">Add keyframe</button>
        <button class="btn" data-kf-clear="${escapeHtml(e.id)}">Clear property keyframes</button>
      </div>
      ${keyframes}
    </div>`;
  }).join("");
  return `<div class="effect-editor">
    <h4>Effects & animation (apply in chain order)</h4>
    <div class="controls">
      <select id="fx-new-type">${EFFECT_TYPES.map((n) => `<option>${n}</option>`).join("")}</select>
      <select id="fx-new-preset"><option value="">no preset</option><option>subtle-glow</option><option>strong-bloom</option><option>fade-in</option><option>punch-in</option></select>
      <button class="btn" id="btn-fx-add" type="button">Add effect</button>
    </div>
    ${rows || '<p class="muted">No effects on this clip.</p>'}
  </div>`;
}

async function wireEffectsEditor(clip) {
  const box = $el("clip-editor");
  if (!box) return;
  box.querySelector("#btn-fx-add")?.addEventListener("click", async () => {
    const preset = box.querySelector("#fx-new-preset").value;
    const type = box.querySelector("#fx-new-type").value;
    try {
      await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects`, {
        method: "POST", body: preset ? { preset } : { type },
      });
      msg("timeline-msg", "Effect added.", "ok");
    } catch (err) { msg("timeline-msg", err.message, "err"); }
  });
  const clipEffects = clip.effects || [];
  const act = async (selector, fn) => {
    box.querySelectorAll(selector).forEach((el) => el.addEventListener("click", async () => {
      try { await fn(el); } catch (err) { msg("timeline-msg", err.message, "err"); }
    }));
  };
  await act("[data-fx-toggle]", async (el) => {
    const effect = clipEffects.find((e) => e.id === el.dataset.fxToggle);
    await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects/${encodeURIComponent(el.dataset.fxToggle)}`,
      { method: "PATCH", body: { enabled: !effect.enabled } });
  });
  await act("[data-fx-delete]", async (el) => {
    selectedClipId = clip.id;
    await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects/${encodeURIComponent(el.dataset.fxDelete)}`, { method: "DELETE" });
  });
  await act("[data-fx-up]", async (el) => {
    await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects/${encodeURIComponent(el.dataset.fxUp)}/move`,
      { method: "POST", body: { direction: -1 } });
  });
  await act("[data-fx-down]", async (el) => {
    await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects/${encodeURIComponent(el.dataset.fxDown)}/move`,
      { method: "POST", body: { direction: 1 } });
  });
  await act("[data-fx-apply]", async (el) => {
    const row = el.closest(".effect-row");
    const params = {};
    row.querySelectorAll("[data-param]").forEach((input) => { params[input.dataset.param] = parseFloat(input.value); });
    await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects/${encodeURIComponent(el.dataset.fxApply)}`,
      { method: "PATCH", body: { params } });
    msg("timeline-msg", "Effect parameters updated.", "ok");
  });
  await act("[data-kf-add]", async (el) => {
    const id = el.dataset.kfAdd;
    const effect = clipEffects.find((e) => e.id === id);
    const prop = box.querySelector(`[data-kf-prop="${id}"]`).value;
    const existing = (effect.keyframes?.[prop] || []).filter(
      (f) => Math.abs(f.time_seconds - parseFloat(box.querySelector(`[data-kf-time="${id}"]`).value)) > 1e-9);
    const frames = [...existing, {
      time_seconds: parseFloat(box.querySelector(`[data-kf-time="${id}"]`).value),
      value: parseFloat(box.querySelector(`[data-kf-value="${id}"]`).value),
      interpolation: box.querySelector(`[data-kf-interp="${id}"]`).value,
    }].sort((a, b) => a.time_seconds - b.time_seconds);
    await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects/${encodeURIComponent(id)}/keyframes`,
      { method: "PUT", body: { property: prop, keyframes: frames } });
    msg("timeline-msg", "Keyframe added.", "ok");
  });
  await act("[data-kf-clear]", async (el) => {
    const id = el.dataset.kfClear;
    const prop = box.querySelector(`[data-kf-prop="${id}"]`).value;
    await timelineCall(`/projects/current/clips/${encodeURIComponent(clip.id)}/effects/${encodeURIComponent(id)}/keyframes`,
      { method: "PUT", body: { property: prop, keyframes: [] } });
  });
}

/* ---------- Phase 5 agent ---------- */

function renderPlan(plan) {
  const steps = (plan.steps || []).map((s, i) =>
    `<div class="muted">${i + 1}. <strong>${escapeHtml(s.tool)}</strong> ${escapeHtml(JSON.stringify(s.args))}</div>`).join("");
  const results = (plan.results || []).map((r) =>
    `<div class="muted">✓ ${escapeHtml(r.tool)} → ${escapeHtml(JSON.stringify(r.result))}</div>`).join("");
  let controls = "";
  if (plan.status === "draft") {
    controls = `<button class="btn" data-plan-approve="${plan.id}">Approve & execute</button>
                <button class="btn" data-plan-reject="${plan.id}">Reject</button>`;
  }
  if (plan.status === "executed" && plan.applied_edit_steps > 0) {
    controls = `<button class="btn" data-plan-undo="${plan.id}">Undo plan edits</button>`;
  }
  const answer = plan.answer && plan.status === "executed"
    ? `<div><strong>Answer:</strong> ${escapeHtml(plan.answer)}</div>` : "";
  const clar = plan.clarification ? `<div style="color:var(--warn)">${escapeHtml(plan.clarification)}</div>` : "";
  const err = plan.error ? `<div style="color:var(--danger)">${escapeHtml(plan.error)}</div>` : "";
  const note = plan.model_note ? `<div class="muted">${escapeHtml(plan.model_note)}</div>` : "";
  return `<div class="job-row">
    <div class="head"><span class="name">${escapeHtml(plan.message)}</span>
      <span class="meta">${escapeHtml(plan.status)} · risk ${escapeHtml(plan.risk)} · via ${escapeHtml(plan.source)}</span></div>
    <div>${escapeHtml(plan.explanation || "")}</div>${answer}${clar}${steps}${results}${note}${err}
    <div class="controls">${controls}</div>
  </div>`;
}

async function loadAgent() {
  try {
    const status = await apiJson("/agent/status");
    const route = status.router.route;
    setText("agent-route", `Model route: ${route.mode}${route.model ? ` (${route.model})` : ""} — ${route.detail}. Approval: ${status.approval_policy}`);
    const plans = await apiJson("/agent/plans");
    setHtml("agent-plans", plans.plans.length ? plans.plans.map(renderPlan).join("") : '<div class="list empty">No plans yet.</div>');
    const audit = await apiJson("/agent/audit?limit=50");
    setJson("agent-audit", audit.events);
  } catch (err) {
    msg("agent-msg", err.message, "err");
  }
}

async function agentPlanAction(kind, id) {
  try {
    await apiJson(`/agent/plans/${encodeURIComponent(id)}/${kind}`, { method: "POST" });
    await loadAgent();
    if (typeof loadTimeline === "function") void loadTimeline();
  } catch (err) { msg("agent-msg", err.message, "err"); }
}
