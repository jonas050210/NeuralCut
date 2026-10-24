# AGENTS.md — Instructions for coding agents

Welcome to NeuralCut. Read this file before changing code.

## Project state

NeuralCut is a local-first AI video editor for Windows. The repository currently implements **Phase 1: Foundation** and **Phase 2: Editing Core**:

- Python/FastAPI backend.
- Vanilla JavaScript frontend served by the backend.
- Tauri 2 shell skeleton (not yet compiled/verified).
- Validated config, JSON project persistence, background jobs, logging, diagnostics, and tests.

Do **not** start Phase 3 or later work unless the project owner explicitly requests that phase. In particular, do not add object tracking, advanced effects, AI chat/tool execution, model training, or autonomous self-improvement as incidental “improvements.” Phase 2 scope is: schema-v2 timeline, import/probe, clip operations, undo/redo, source/edited preview, and FFmpeg export via background jobs.

## Source of truth

1. Preserve `BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md` unchanged. It is the original research deliverable.
2. Start with `README.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/DECISIONS.md`.
3. Keep documentation synchronized with behavior in the same change whenever architecture, config, APIs, storage, or developer workflow changes.

## Architecture invariants

- **Local-first:** no cloud dependency, telemetry, model download, or account requirement by default.
- **Windows laptop friendly:** must work without an NVIDIA GPU. Do not import CUDA/NVML/model runtimes or initialize a GPU during normal startup.
- **Models optional:** `models.enabled` defaults to `false`. Future model work must be lazy and explicit.
- **Deterministic core first:** project state, validation, jobs, and future editing operations must remain deterministic and testable. Future LLM components should call validated tools; they must not directly mutate files or pixels.
- **Backend boundary:** frontend uses same-origin relative `/api/v1/...` calls. Do not hard-code `localhost` URLs into browser code.
- **Validation at boundaries:** use Pydantic models for HTTP/config/project data. Return `NeuralCutError` subclasses for expected application failures.
- **No fake functionality:** extension adapters must report unavailable planned features honestly. Do not add placeholder buttons/results that pretend work happened.
- **Single current project:** `ProjectService` intentionally tracks one open project. Preserve that contract unless a phase explicitly redesigns it.
- **Editing only through `TimelineService`:** all timeline mutations must go through `neuralcut/backend/editing/service.py` so validation and undo history stay consistent. Never mutate `project.clips` from route handlers or future AI code directly.
- **Render only through the job manager:** rendering is submitted as the `render` job type with a project snapshot; the engine must keep polling `cancel_event` and must verify output duration before reporting success.
- **Project schema discipline:** current schema is v2. Any change bumps `PROJECT_SCHEMA_VERSION`, adds a raw-dict migration in `projects/model.py`, and adds a committed old-version load test.
- **Media is referenced, not copied:** assets store local paths. Missing source files must surface as explicit errors/markers, never silent substitution.

## Repository map

```text
neuralcut/
  config.py                 validated settings and AppContext
  errors.py                 typed errors and problem responses
  jobs.py                   thread-based background job manager
  logging.py                structured/plain logging
  main.py                   CLI/startup entry point
  backend/
    app.py                  FastAPI app factory and SPA serving
    di.py                   dependency container
    api/v1/                 HTTP routes
    projects/               schema-v2 model + migrations, atomic store, service
    editing/                TimelineService: clip ops, validation, undo/redo
    rendering/              FFmpeg segment+concat export engine and render job
    integration/            media probe (real) + model/GPU/eval adapters
  frontend/                 static HTML/CSS/JS UI
  tests/                    pytest suite
src-tauri/                  unverified Tauri 2 shell skeleton
scripts/                    setup/run/test helpers
docs/                       project knowledge base
```

## Development workflow

Use the repository virtual environment:

Linux/macOS:

```bash
./scripts/setup.sh
./scripts/test.sh
./scripts/run.sh --no-browser
```

Windows PowerShell:

```powershell
.\scripts\setup.ps1
.\scripts\test.ps1
.\scripts\run.ps1
```

Before declaring work complete:

1. Run `./scripts/test.sh` or `.\scripts\test.ps1`.
2. Run `python -m compileall -q neuralcut` if Python modules changed.
3. Run `node --check neuralcut/frontend/assets/app.js` if frontend JS changed.
4. Start the backend and smoke-test affected endpoints/UI when practical.
5. State clearly what was and was not verified. Never claim Windows or Tauri builds passed unless actually run on Windows/with Rust.

## Testing guidance

- Add or update tests for every behavior change.
- Prefer small unit tests for config, models, jobs, and stores.
- API tests use `httpx.ASGITransport`; avoid relying on a fixed network port.
- Use pytest `tmp_path` for config/project/log files. Do not write test data into the repository or user profile.
- Avoid sleeps where an event/polling deadline is practical; background-job tests must be deterministic enough for CI.
- If a test needs Windows-only behavior, mark/skip it appropriately and document the manual Windows check in `docs/TESTING.md`.

## Coding guidance

- Python 3.10+; type hints are expected for public functions.
- Keep dependencies minimal. Prefer the standard library for infrastructure such as jobs and logging.
- Do not add heavy media/AI dependencies during foundation work.
- Keep integration adapters thin and explicit. Add a real implementation only in its roadmap phase.
- Preserve atomic writes for config/project files (write temp file in same directory, then replace).
- Background jobs must support cooperative cancellation and report progress/errors. Job payload keys `job`, `progress`, and `cancel_event` are reserved.
- Log meaningful lifecycle/error events with structured `extra={...}` fields; avoid logging secrets or large media payloads.
- Frontend must escape user-controlled strings before inserting HTML and should validate critical API response shapes.

## Git/PR guidance

- Work on the session/feature branch specified by the project owner; do not push directly to `main` unless instructed.
- Keep commits focused and describe user-visible/architectural impact.
- Open a pull request when requested. Do not merge without explicit authorization.
- Include test results and verification limits in the PR description.

## Documentation updates

Update the relevant file when you change:

- Setup/commands: `README.md`, `docs/DEVELOPMENT.md`, `docs/TESTING.md`.
- APIs/modules: `docs/ARCHITECTURE.md`, `docs/MODULES.md`.
- Scope/phase status: `docs/ROADMAP.md`, `docs/PROJECT_OVERVIEW.md`, `docs/CHANGELOG.md`.
- Technical choice: `docs/DECISIONS.md`.
- Limitation/risk: `docs/KNOWN_ISSUES.md`.
- AI/model/runtime plan: `docs/AI_INFRASTRUCTURE.md` and, for evaluation/training, `docs/SELF_IMPROVEMENT.md`.
