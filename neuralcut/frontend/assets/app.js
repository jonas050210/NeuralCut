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
  if (id === "projects") void loadRecent();
}

function nav() {
  const hash = (window.location.hash || "#dashboard").replace("#", "");
  const valid = ["dashboard", "projects", "project", "jobs", "settings", "logs"];
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

  setText("api-url", API_BASE || window.location.origin);
}

document.addEventListener("DOMContentLoaded", boot);
