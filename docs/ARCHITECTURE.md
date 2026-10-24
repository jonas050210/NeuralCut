# Architecture

This document describes the implemented Phase 1 foundation plus Phase 2 editing core, and the boundaries reserved for later phases.

## High-level shape

```text
┌──────────────────────────────────────────────────────────────────┐
│ Browser now / Tauri WebView later                                │
│ neuralcut/frontend (static HTML/CSS/vanilla JS)                  │
└───────────────────────────────┬──────────────────────────────────┘
                                │ same-origin HTTP JSON
                                │ /api/v1/...
┌───────────────────────────────▼──────────────────────────────────┐
│ Python backend (FastAPI + uvicorn)                               │
│                                                                  │
│  API routes ─► Container ─► ProjectService ─► ProjectStore       │
│                    │              │                              │
│                    │              └────────► .neuralcut JSON (v2)│
│                    ├────────► TimelineService (edits, undo/redo) │
│                    ├────────► JobManager ─► worker threads       │
│                    │              └─ render job ─► FFmpeg engine │
│                    ├────────► MediaProcessorAdapter (ffprobe)    │
│                    ├────────► structured logging                 │
│                    └────────► AI adapters (planned, unavailable) │
└──────────────────────────────────────────────────────────────────┘

App data: config.json, logs/neuralcut.log, recent project paths
Projects: user-selected .neuralcut JSON files
```

The backend binds to `127.0.0.1:8765` by default. The frontend is served by the same process, so browser code uses relative same-origin API paths and never hard-codes a backend host.

## Runtime components

### Entry point — `neuralcut/main.py`

Responsibilities:

- Parse CLI options (`--host`, `--port`, `--config`, `--data-dir`, `--no-browser`).
- Load an `AppContext` through `load_settings()`.
- Build one `Container` and FastAPI app for that exact context.
- Optionally open the default browser after a short delay.
- Run uvicorn in the foreground; Ctrl+C / process termination shuts it down.

This design lets the future Tauri shell start the same backend with `--no-browser`.

### Dependency container — `neuralcut/backend/di.py`

`Container` owns process-wide services:

- Resolved settings and app context.
- Application logger.
- `JobManager`.
- `ProjectService` (seeded with persisted recent projects).
- Media/model/GPU/evaluation/self-improvement adapters.

Recent-project changes update settings and are persisted through `save_settings()`. Persistence failures are logged as warnings rather than making project open/create fail after the project operation itself succeeded.

### FastAPI app — `neuralcut/backend/app.py`

Responsibilities:

- Store the container at `app.state.container`.
- Register global exception handlers.
- Mount `/api/v1` routes.
- Register built-in job types (currently only `demo`).
- Serve `/assets/...` static frontend files.
- Return JSON 404 problem details for unknown `/api/...` routes.
- Fall back to `index.html` for non-API routes so hash/client navigation remains simple.

### API layer — `neuralcut/backend/api/`

Routes are synchronous FastAPI handlers because editing operations are local, short, and thread-safe at the service boundary. Long work (rendering) belongs in `JobManager`, not request handlers.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Basic liveness and version |
| `GET` | `/api/v1/diagnostics` | Platform, paths, jobs, adapter/tool status |
| `GET` | `/api/v1/config` | Effective validated configuration |
| `GET` | `/api/v1/logs?lines=50` | Tail of the application log |
| `GET` | `/api/v1/projects` | Recent project paths and existence |
| `POST` | `/api/v1/projects/create` | Create and open a project |
| `POST` | `/api/v1/projects/open` | Load and open a project file |
| `GET` | `/api/v1/projects/current` | Current project summary or `{status:"none"}` |
| `POST` | `/api/v1/projects/save` | Save current project |
| `POST` | `/api/v1/projects/close` | Close current project without saving |
| `GET` | `/api/v1/jobs` | List jobs, optionally filtered by status |
| `POST` | `/api/v1/jobs` | Submit a registered job type |
| `GET` | `/api/v1/jobs/{job_id}` | Job status/result/error |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Request cooperative cancellation |
| `GET` | `/api/v1/projects/current/timeline` | Assets, clips (with derived durations), export settings, undo state |
| `POST` | `/api/v1/projects/current/assets/import` | Probe a local file and add it as an asset |
| `DELETE` | `/api/v1/projects/current/assets/{asset_id}` | Remove an unused asset reference |
| `POST` | `/api/v1/projects/current/clips` | Add a clip (appends to the track end by default) |
| `PATCH` | `/api/v1/projects/current/clips/{clip_id}` | Move and/or trim (and rename) a clip |
| `POST` | `/api/v1/projects/current/clips/{clip_id}/split` | Split at a timeline time |
| `DELETE` | `/api/v1/projects/current/clips/{clip_id}` | Remove a clip |
| `POST` | `/api/v1/projects/current/undo` / `/redo` | Restore prior/next timeline state |
| `POST` | `/api/v1/projects/current/render` | Snapshot the project and submit a `render` job |
| `GET` | `/api/v1/media/assets/{asset_id}/content` | Stream a source file with HTTP Range support (preview/seeking) |
| `POST` | `/api/v1/projects/current/assets/{asset_id}/analyze` | Submit an `analysis` job for an asset |
| `GET` | `/api/v1/projects/current/assets/{asset_id}/analysis` | Analysis status summary |
| `GET` | `/api/v1/projects/current/assets/{asset_id}/analysis/artifacts` | Full artifact (shots, tracks/masks, speech, transcript) |
| `GET` | `/api/v1/projects/current/assets/{asset_id}/analysis/search` | Caption search (`q`) or similar shots (`similar_to`) |
| `GET` | `/api/v1/effects/types` | Effect registry (types, params, presets) |
| `POST/PATCH/DELETE` | `/api/v1/projects/current/clips/{clip_id}/effects[/​{effect_id}]` | Effect add/update/remove |
| `POST` | `/api/v1/projects/current/clips/{clip_id}/effects/{effect_id}/move` | Reorder an effect in the chain |
| `PUT` | `/api/v1/projects/current/clips/{clip_id}/effects/{effect_id}/keyframes` | Replace a property's keyframes |

FastAPI's generated OpenAPI UI remains available at `/docs` when the server is running.

### Error model — `neuralcut/errors.py`

Expected application errors derive from `NeuralCutError` and carry:

- Stable machine-readable `code`.
- Human-readable `title/message`.
- HTTP status.
- Optional structured `details`.
- Request path as `instance`.

Handlers emit RFC 7807-style JSON. Validation errors from FastAPI/Pydantic return FastAPI's standard `422` body. Unexpected exceptions return a generic `500` problem response and are logged with traceback details; internal exception text is not exposed to the frontend.

### Configuration — `neuralcut/config.py`

Settings are Pydantic models grouped into app, logging, jobs, media, models, UI, and recent projects.

Priority:

1. CLI (host/port/config/data-dir only).
2. Environment variables (`NEURALCUT_*`, nested delimiter `__`).
3. JSON config file.
4. Defaults.

`AppContext` carries the authoritative resolved `data_dir` and `config_path`. Defaults:

- Windows: `%APPDATA%/NeuralCut`.
- Linux: `~/.local/share/neuralcut`.
- macOS: `~/Library/Application Support/NeuralCut`.

`save_settings()` writes JSON atomically via `<config>.tmp` and replace.

### Logging — `neuralcut/logging.py`

- Standard-library logging only.
- JSON lines by default; plain text when `logging.json_logs=false`.
- Rotating file under `<data_dir>/logs/neuralcut.log`.
- Optional stdout handler.
- Context-variable correlation ID (`cid`) via `CorrelationScope` or `set_correlation_id()`.
- Non-serializable structured extras are stringified instead of breaking log emission.

The `/api/v1/logs` endpoint reads the bounded rotating log file and returns the requested tail. It is intended for local diagnostics, not remote log collection.

### Projects — `neuralcut/backend/projects/`

#### Model

`Project` schema version is currently `3` (see `DATA_MODELS.md`). A project contains:

- `id`, `name`, creation/modification timestamps.
- Asset references (`ProjectAsset`) with probed metadata (duration, dimensions, fps, codec, audio presence).
- Timeline clips (`ProjectClip`): track, `timeline_start_seconds`, source in/out points; the model enforces unique ids, known asset references, and no same-track overlaps.
- `export_settings` (size/fps/quality defaults) plus free-form `settings` and `metadata` dictionaries.

Pydantic validates IDs, non-empty names/paths, non-negative durations/times, and clip ranges. Assignment validation is enabled.

#### Store

`ProjectStore` saves pretty-printed JSON atomically:

1. Serialize validated project.
2. Write a temp file in the destination directory.
3. `os.replace()` it over the target.

Load flow:

1. Verify the file exists.
2. Parse JSON and require an object.
3. Reject non-integer or future schema versions before model validation.
4. Validate with Pydantic.
5. Run registered migrations if the version is older.

Version < 2 documents are migrated on the raw JSON dict before validation (v1→v2 places clips sequentially per track, preserving source ranges). Future versions are still rejected before migration.

#### Service

`ProjectService` owns the single open project and recent list. Create generates `<sanitized-name>.neuralcut`, rejects duplicates, saves, opens the project, and records it as recent. Open validates/loads before replacing current state.

### Background jobs — `neuralcut/jobs.py`

`JobManager` uses daemon threads plus a bounded semaphore. A job has:

- `queued`, `running`, `completed`, `failed`, or `cancelled` status.
- Progress `0.0–100.0` and a progress message.
- JSON-serializable result or error text/details.
- Creation/start/finish timestamps.
- A `threading.Event` for cooperative cancellation.

Job functions receive `(job, *, progress, cancel_event, **payload)`. Payload keys `job`, `progress`, and `cancel_event` are reserved and rejected. Job functions must poll `cancel_event`; Python threads cannot be safely killed.

Jobs and results are in memory only. Expired terminal jobs may be purged on submit according to `jobs.result_ttl_seconds`; `jobs.max_jobs` bounds retention and returns `429` when full.

The built-in `demo` job validates `steps` and `delay`, reports each step, and supports cancellation. Later import/analysis/render jobs must follow the same contract.

### Frontend — `neuralcut/frontend/`

The frontend is deliberately dependency-free:

- `index.html` defines dashboard, projects, current project, jobs, settings, and logs views.
- `assets/app.js` contains hash routing, API client, response shape validation, rendering, forms, and periodic refresh.
- `assets/style.css` provides the dark application shell styling.

User/backend-controlled strings are escaped before HTML insertion. Job cancellation uses event delegation rather than inline handlers.

There is no build step in Phase 1. This reduces setup friction; a component framework can be reconsidered when the timeline UI makes state management substantially more complex.

### Integration adapters — `neuralcut/backend/integration/`

| Adapter | Phase 1 behavior | Future responsibility |
|---|---|---|
| `MediaProcessorAdapter` | **Implemented (Phase 2):** resolves ffmpeg/ffprobe and probes media (duration/size/fps/codec/audio) | Proxies, thumbnails/waveforms, analysis handoff (Phase 3) |
| `ModelManagerAdapter` | Reports unavailable/disabled; operations raise `503` | Lazy local model load/unload/inference and routing support |
| `GpuManagerAdapter` | Checks only whether `nvidia-smi` exists; never initializes CUDA | Device inventory, VRAM budget, scheduling/serialization |
| `EvaluationAdapter` | Reports unavailable | Fixture suites, deterministic graders, reports |
| `SelfImprovementAdapter` | Reports unavailable | Feedback capture, datasets, experiments, promotion/rollback |

This keeps API/diagnostics contracts stable without pretending future systems exist.

### Tauri shell — `src-tauri/`

The Tauri 2 skeleton starts `python -m neuralcut --no-browser` and opens `http://127.0.0.1:8765` in a desktop window. It kills the child process when the window is destroyed.

Limitations:

- Not compiled in Phase 1's Linux environment.
- Assumes Python can import the development package; `NEURALCUT_PYTHON` can point at `.venv` Python.
- Does not yet bundle Python/dependencies/media tools/models.
- Bundling is disabled in config until Phase 7.

## Startup and shutdown flow

```text
main()
  ├─ load_settings()          resolve data/config paths and validate
  ├─ Container(context)
  │    ├─ setup_logging()
  │    ├─ JobManager(...)
  │    ├─ ProjectService(recent, persistence callback)
  │    └─ integration adapters (no heavy initialization)
  ├─ build_app(container)
  │    ├─ exception handlers
  │    ├─ API routes
  │    ├─ register demo job
  │    └─ static frontend/SPA fallback
  └─ uvicorn.run(...)         foreground server

Shutdown is uvicorn/process driven. Job threads are daemons; running jobs are
not persisted or resumed after process exit.
```

## Security and trust boundaries

- Default bind is loopback only. Do not expose the backend on a LAN without adding authentication and a threat model.
- Project/open/log endpoints operate on local paths supplied by the desktop user. This is acceptable for a local single-user app but not for a remote service.
- No cloud calls, telemetry, model downloads, or GPU initialization occur in Phase 1.
- Frontend output escaping mitigates HTML injection from project/job strings.

## Future architectural direction

Later phases should preserve these boundaries:

- Deterministic project/timeline state remains independent of LLMs.
- Analysis creates derived artifacts (shots, transcripts, embeddings, captions) once and stores them for retrieval.
- AI planning produces validated tool calls; a deterministic executor applies them transactionally with undo.
- Heavy GPU work is serialized/budgeted through the GPU/model adapters and background jobs.
- Evaluation uses deterministic graders as gates and human preference as a separate signal.

## Editing core (Phase 2) — `neuralcut/backend/editing/`

`TimelineService` is the only mutation path for assets/clips. Each operation
builds a mutated project copy, validates it with the Pydantic model
(unknown assets, source ranges beyond asset duration, same-track overlaps),
and only then swaps it in and pushes the previous full-project snapshot onto
the undo stack (max 100). Undo/redo swap snapshots back, guaranteeing exact
restoration. History is memory-only and resets when a different project
object becomes current; edits are not auto-saved.

## Rendering (Phase 2) — `neuralcut/backend/rendering/`

`FFmpegRenderEngine` flattens the timeline by `(timeline_start, track, id)`,
rejects overlaps in that flattened order (no compositing yet), converts gaps
> 0.05s into black/silent segments, renders every segment with identical
libx264/AAC parameters (audio-less clips get generated silence), concatenates
with the concat demuxer (stream copy), and finally probes the output: it must
exist, be non-empty, and match the expected timeline duration within
max(1s, 5%). Cancellation terminates the running ffmpeg subprocess.

The `render` job is registered against the container and submitted through
`POST /projects/current/render`, which snapshots the project at submission
time — later edits do not affect a running export. Long media work never
runs inside request handlers.

## Preview (Phase 2)

Source assets stream from `GET /api/v1/media/assets/{id}/content` with HTTP
Range support, so the browser `<video>` element can seek. The edited preview
is client-side sequential playback of source ranges and is labelled an
approximation; the FFmpeg export is the canonical edited output.

## Video intelligence (Phase 3) — `neuralcut/backend/intelligence/`

`AnalysisService.analyze()` runs as the `analysis` background job (project
snapshot of the asset at submission, cooperative cancellation between
steps) and never touches the timeline. Pipeline: ffprobe metadata → ffmpeg
scene-cut shot detection → grayscale frame sampling (96×54 @ 5fps, max 300
frames) → per-shot motion levels → motion detection/tracking
(`detection.py`: median background, threshold, connected components,
greedy centroid/IoU linking, RLE masks) → per-shot color-histogram
embeddings + heuristic captions → `silencedetect` speech segments →
optional faster-whisper transcription (only when installed and
`models.enabled=true`, else an explicit `unavailable` artifact).

Artifacts are versioned JSON in `<data_dir>/analysis/<fingerprint>.json`;
the fingerprint (size + mtime + sampled chunk hashes) gives cache reuse
and automatic invalidation. Search endpoints provide caption token search
and embedding cosine similarity.

## Effects and compositing (Phase 4) — `neuralcut/backend/effects/`

The registry in `effects/engine.py` is the single source of truth for
effect types (`transform`, `color`, `blur`, `glow`, `bloom`), parameter
ranges/defaults, presets, keyframe evaluation (linear/hold), and the
FFmpeg filter mapping. All mutations flow through `TimelineService`
(validated, one undo step each) into schema-v3 project documents.

The renderer keeps the fast Phase 2 segment path for plain single-track
timelines. Timelines with any effects or cross-track overlaps use the
compositing path: atomic intervals at clip boundaries, keyframes evaluated
at interval midpoints, tracks composited bottom-to-top with
opacity/scale/position, audio mixed (`amix`, silence for audio-less
layers), segments encoded identically and concatenated, output
duration-verified. The browser edited-preview evaluates the same registry
values at the playhead and applies CSS filter approximations — it is
labelled an approximation in the UI.
