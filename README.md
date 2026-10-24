# NeuralCut

NeuralCut is a planned **local-first AI video editor for Windows**. This repository currently contains **Phase 1: Foundation** only.

Phase 1 is a working application foundation—not a video editor yet. It provides the local backend, browser UI, configuration, project persistence, background jobs, logging, diagnostics, tests, and extension points that later editing/AI phases will build on.

## What works in Phase 1

- Local FastAPI backend and same-origin vanilla-JavaScript frontend.
- Validated frontend/backend HTTP communication with problem-detail error responses.
- Centralized, validated configuration from defaults, JSON, environment variables, and CLI options.
- Versioned `.neuralcut` JSON project files with atomic save and validated load.
- Create/open/save/close project flow and persisted recent-project list.
- Background job manager with progress, cooperative cancellation, failure reporting, and a built-in `demo` job type.
- Rotating structured JSON logs plus health, diagnostics, configuration, and log endpoints/views.
- Integration adapters that explicitly report media, AI models, GPU, evaluation, and self-improvement as planned/unavailable in Phase 1.
- Automated pytest suite and GitHub Actions workflow for Ubuntu and Windows test runs.
- A Tauri 2 desktop-shell skeleton under `src-tauri/` for later Windows packaging.

## What is intentionally not implemented yet

- No timeline or video-editing operations.
- No media import, preview rendering, effects, or export.
- No object detection/tracking, masks, transcription, or other video intelligence.
- No AI chat, model download, model inference, or GPU initialization.
- No training, autonomous self-improvement, Windows installer, or production Tauri bundle.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phase sequence and acceptance criteria.

## Quick start on Windows

### Prerequisites

- Windows 10/11.
- Python 3.10 or newer available as `python` on `PATH`.
- Optional: Node.js 22 for frontend syntax checks and the future Tauri shell.
- No NVIDIA GPU is required. No cloud account is required.

### Install and run

Open PowerShell in the repository folder:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

The backend starts at:

```text
http://127.0.0.1:8765/
```

It also attempts to open your default browser. To run without opening a browser:

```powershell
.\scripts\run.ps1 --no-browser
```

To use another local port:

```powershell
.\scripts\run.ps1 --no-browser --port 9000
```

After setup, `NeuralCut.bat` can also start the backend.

If PowerShell blocks local scripts, run the setup for the current shell only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup.ps1
```

### Run tests on Windows

```powershell
.\scripts\test.ps1
```

This runs the Python test suite and checks frontend JavaScript syntax with Node.

## Quick start on Linux/macOS for development

```bash
./scripts/setup.sh
./scripts/run.sh
./scripts/test.sh
```

NeuralCut targets Windows first; Linux/macOS are supported as development environments for the Python/web foundation.

## Using the Phase 1 UI

The UI has five operational areas:

1. **Dashboard** — backend health and diagnostics.
2. **Projects** — create a `.neuralcut` project by name/directory or open one by path.
3. **Current Project** — inspect the open project summary and save it.
4. **Background Jobs** — submit/cancel the built-in demo job and observe progress.
5. **Settings / Logs** — inspect effective configuration and recent structured logs.

Project files are human-readable JSON. Keep them in a normal documents/projects folder; application data such as config and logs is stored separately.

## Configuration

Configuration priority is:

1. CLI arguments.
2. `NEURALCUT_*` environment variables.
3. JSON config file.
4. Built-in defaults.

Default application data locations:

- Windows: `%APPDATA%\NeuralCut\`
- Linux: `~/.local/share/neuralcut/`
- macOS: `~/Library/Application Support/NeuralCut/`

The default config path is `<data-dir>/config.json`. See [`config.example.json`](config.example.json) and [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

Useful environment variables include:

```text
NEURALCUT_DATA_DIR=C:\Path\To\NeuralCutData
NEURALCUT_CONFIG_FILE=C:\Path\To\config.json
NEURALCUT_PORT=9000
NEURALCUT_LOGGING__LEVEL=DEBUG
NEURALCUT_LOGGING__STDOUT=false
```

AI models remain disabled by default (`models.enabled=false`). Phase 1 never downloads models or initializes a GPU.

## Tauri shell status

`src-tauri/` contains a Tauri 2 development shell skeleton that launches `python -m neuralcut --no-browser` as a local backend process and points a window at `http://127.0.0.1:8765`.

It has **not been compiled or verified in the Phase 1 Linux development environment** because Rust and Windows WebView2 tooling were unavailable. It is not yet an installer or a self-contained desktop application. Packaging a frozen/bundled backend is Phase 7 work.

## Documentation

- [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — goals, scope, and vision.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, APIs, and data flow.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phases and acceptance criteria.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — setup and troubleshooting.
- [`docs/TESTING.md`](docs/TESTING.md) — automated and manual verification.
- [`docs/RESEARCH.md`](docs/RESEARCH.md) — distilled research findings.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — architectural decisions and trade-offs.
- [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) — limitations and open questions.

The original Phase 1 research deliverable is preserved unchanged as [`BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md`](BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md).

## License

The package metadata currently declares MIT. Add/confirm the project license before public distribution, and review future third-party media/model licenses separately.
