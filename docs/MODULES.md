# Modules and Extension Points

This document maps the codebase to responsibilities and explains where later phases should extend it.

## Python package

### `neuralcut/config.py`

- Defines validated settings models: logging, jobs, media, models, and UI.
- Resolves data/config paths.
- Loads defaults < JSON config < environment variables.
- Saves config atomically.
- Key extension pattern: add a new settings group as a Pydantic model and expose it in `/api/v1/config` only if safe/useful for the UI.

### `neuralcut/errors.py`

- Defines `NeuralCutError` and subclasses for validation, not-found, conflict, unavailable, project, job, and configuration errors.
- Converts errors to RFC 7807-style problem responses.
- Key extension pattern: raise a typed error with stable `code`, appropriate HTTP status, and structured `details`; do not return ad-hoc error strings from services.

### `neuralcut/logging.py`

- Configures root logging, rotating file output, optional stdout, JSON/plain formatting, and correlation IDs.
- Key extension pattern: log lifecycle events from services/jobs with `extra={...}`. Use `CorrelationScope` around a request/job when a future code path needs traceability.

### `neuralcut/jobs.py`

- Defines `Job`, `JobStatus`, and `JobManager`.
- Runs registered job functions on threads with bounded concurrency.
- Supports progress, result/error capture, cooperative cancellation, list/get/cancel, TTL purge, and max-job bounds.
- Key extension pattern:

```python
def analyze(job, *, progress, cancel_event, asset_id):
    progress(5, "loading metadata")
    if cancel_event.is_set():
        return {"cancelled": True}
    # Real future work here. Return JSON-serializable data.
    return {"asset_id": asset_id, "done": True}

job_manager.register_job_type("analysis.import", analyze)
```

Job functions must poll `cancel_event`, validate payload values, and avoid mutating global project state without a service-level transaction design.

### `neuralcut/main.py`

- CLI parsing and uvicorn startup.
- Builds the app from the CLI-selected `AppContext`.
- Opens the browser unless `--no-browser` is supplied.
- Key extension pattern: keep desktop/sidecar startup options here; do not bury process startup inside API routes.

## Backend

### `neuralcut/backend/di.py`

- Owns the service graph for one process.
- Initializes logging before services that log.
- Seeds/persists recent projects.
- Instantiates all integration adapters without heavy work.
- Key extension pattern: construct long-lived services here and pass the container to `build_app()`; avoid global singletons inside route modules.

### `neuralcut/backend/app.py`

- FastAPI factory, exception handlers, router mounting, built-in job registration, static frontend, and SPA fallback.
- Key extension pattern: register production job types during app construction or a dedicated startup registry; keep unknown `/api/...` paths returning JSON 404.

### `neuralcut/backend/demo_job.py`

- Registers the Phase 1 `demo` job.
- Demonstrates payload validation, progress, and cancellation.
- Later phases should replace demo-only registration with domain job registries grouped by import/analysis/render/evaluation.

### `neuralcut/backend/api/deps.py`

- Retrieves the `Container` from `request.app.state`.
- Route handlers should use this instead of importing global service instances.

### `neuralcut/backend/api/v1/system.py`

- Health, diagnostics, log tail, and effective config.
- Diagnostics is the place to expose safe capability/status information for support and UI capability gating.

### `neuralcut/backend/api/v1/editing.py` (Phase 2)

- Timeline, asset import/remove, clip add/patch/split/delete, undo/redo, render submission, and range-streamed media content endpoints.
- Handlers delegate every mutation to `TimelineService`; they never touch `project.clips` directly.
- Render submission snapshots the project into the job payload so later edits cannot affect a running export.

### `neuralcut/backend/editing/service.py` (Phase 2)

- `TimelineService`: the single mutation path for timeline state.
- Validates each mutated project with the Pydantic model before committing; a rejected edit changes nothing.
- Snapshot undo/redo (max 100), in-memory, reset on project switch.
- Missing source files, unknown ids, out-of-range trims, and overlaps raise typed errors.

### `neuralcut/backend/rendering/ffmpeg.py` (Phase 2)

- `FFmpegRenderEngine`: segment-and-concat export (see `docs/ARCHITECTURE.md`), progress callbacks, subprocess-terminating cancellation, output-duration verification.
- `register_render_jobs()`: binds the `render` job type to the container.
- Raises `RenderError`/`RenderCancelled` (job failures surface these messages).

### `neuralcut/backend/intelligence/` (Phase 3)

- `analysis.py` — `AnalysisService` (shots, motion, embeddings/captions, speech, optional ASR), `AnalysisStore` (fingerprinted sidecar JSON), `register_analysis_jobs()`.
- `detection.py` — pure-Python motion detection/tracking and RLE mask codec; detector-agnostic track representation.
- Rules: analysis never mutates the timeline; artifacts are derived/regenerable; no fabricated transcripts or semantic labels.

### `neuralcut/backend/effects/engine.py` (Phase 4)

- The effect registry: types, parameter specs, presets, validation, keyframe evaluation, and FFmpeg filter mapping.
- Add an effect here first; service/API/UI/preview/renderer pick it up from the registry. `transform` is compositing-time only.

### `neuralcut/backend/api/v1/intelligence.py` (Phases 3–4)

- Analysis submit/status/artifacts/search endpoints and effect/keyframe endpoints. All mutations delegate to `TimelineService`.

### `neuralcut/backend/agent/` (Phase 5)

- `tools.py` — tool registry: names, argument schemas, risk levels. This is the agent's entire permission boundary; add tools here (with a service-level implementation) and nowhere else.
- `planner.py` — deterministic built-in planner; ambiguity → clarification with zero steps.
- `model_client.py` — `ModelRouter`: builtin/local/cloud routing rules and JSON-plan generation over an injectable transport.
- `service.py` — `AgentService`: context building, plan lifecycle (draft/approve/reject/undo), controlled execution, plan persistence, JSONL audit.

### `neuralcut/backend/api/v1/agent.py` (Phase 5)

- `/agent/status|chat|plans|plans/{id}/approve|reject|undo|audit`. Handlers delegate to `AgentService`; no execution logic in routes.

### `neuralcut/backend/api/v1/projects.py`

- Project create/open/current/save/close and recent list endpoints.
- Request models strip and reject blank names/directories/paths.
- Responses are summaries; the full project document stays in the service/store layer.

### `neuralcut/backend/api/v1/jobs.py`

- Job submit/list/get/cancel endpoints.
- Unknown job types and reserved payload keys become client errors through `JobManager`.

### `neuralcut/backend/projects/model.py`

- Canonical project schema (currently v2) and raw-dict migration registry (`RAW_MIGRATIONS`); semantics in `docs/DATA_MODELS.md`.
- When schema changes:
  1. Increment `PROJECT_SCHEMA_VERSION`.
  2. Add a raw-dict migration with `@register_migration(old, new)`.
  3. Add load/migration tests with a real old-version document.
  4. Document the change in `CHANGELOG.md` and `DECISIONS.md`.

### `neuralcut/backend/projects/store.py`

- Atomic JSON save and validated/version-gated load.
- Future sidecar/derived-data stores should be separate classes; do not hide caches inside the canonical project store.

### `neuralcut/backend/projects/service.py`

- Single-open-project lifecycle and recent list.
- Create/open set current state only after successful save/load.
- Future multi-project/session behavior requires an explicit phase decision and API redesign.

## Integration adapters

### `integration/media.py` — probing implemented (Phase 2)

Implemented: binary resolution (settings → `PATH` → optional `imageio-ffmpeg`),
ffprobe-JSON probing with an `ffmpeg -i` parsing fallback, supported-format
validation, and typed errors for missing/unsupported/unreadable files.

Future responsibilities: proxies/thumbnails/waveforms and analysis handoff
(Phase 3). Do not call FFmpeg synchronously from API handlers for long
operations; submit jobs (rendering already follows this rule).

### `integration/models.py` — planned Phase 3/5

Future responsibilities:

- Inventory local models and licenses/sizes.
- Lazy load/unload one heavy model family at a time when required.
- Provide inference interfaces for ASR/VLM/LLM/embedding specialists.
- Enforce `models.enabled`, explicit download consent, and memory budgets.

No model should load during application startup unless a future user setting explicitly requests it and tests cover the failure mode.

### `integration/gpu.py` — planned Phase 3/5

Future responsibilities:

- Optional device discovery without making NVIDIA a requirement.
- VRAM budgeting and heavy-job serialization.
- CPU fallback reporting.
- Safe behavior when drivers/tools are missing.

### `integration/evaluation.py` — planned Phase 6

Future responsibilities:

- Load fixture tasks.
- Run sandbox evaluations against fixture copies.
- Execute deterministic graders and produce versioned reports.

### `integration/self_improvement.py` — planned Phase 6

Future responsibilities:

- Explicit feedback records.
- Dataset/version registry.
- Candidate experiment tracking.
- Promotion/rollback coordination with evaluation gates.

It must never silently train on user media or auto-promote a candidate.

## Frontend

### `neuralcut/frontend/index.html`

- Application shell and view markup.
- Add new views as `<section id="view-...">` plus a matching `data-nav` link.

### `neuralcut/frontend/assets/app.js`

- Same-origin API client and `ApiError`.
- `requireShape()` response validation.
- Hash routing and per-view loaders.
- Project/job/settings/log interactions.
- Escape all strings inserted with `innerHTML`; prefer `textContent` for plain data.

### `neuralcut/frontend/assets/style.css`

- Dark shell, cards, forms, lists, code/log blocks, progress bars, and status colors.

## Tauri

### `src-tauri/src/main.rs`

- Starts/stops the Python backend child process for development.
- `NEURALCUT_PYTHON` overrides the interpreter.

### `src-tauri/tauri.conf.json`

- Main window points at the local backend.
- Bundle mode is disabled until Phase 7 packaging.

### `src-tauri/capabilities/default.json`

- Minimal core capability. Add permissions only when a real Tauri command/plugin requires them and document why.

## Tests and scripts

- `neuralcut/tests/` — pytest unit/API tests using temp dirs and ASGI transport.
- `scripts/setup.*`, `run.*`, `test.*` — platform setup/run/test entry points.
- `.github/workflows/ci.yml` — Ubuntu/Windows Python tests and JS syntax check.
- `requirements.txt` — pinned runtime/test dependencies used by setup scripts.
- `pyproject.toml` — package metadata, dependency ranges, pytest config.
