# NeuralCut

NeuralCut is a **local-first AI video editor for Windows**, currently at **Phase 2: Editing Core** (version 0.2.0). It provides a real timeline editor: import local video, arrange/trim/split clips, undo/redo, preview source and edited output, and export a rendered MP4 with FFmpeg — all locally, with no cloud account and no NVIDIA GPU requirement. AI assistance is a later phase (see roadmap).

## What works in Phase 2

- Everything from the Phase 1 foundation (below), plus:
- **Media import & probing** — import local video/audio files by path; duration, resolution, fps, codec, and audio presence are probed with ffprobe (or ffmpeg fallback) and stored in the project.
- **Timeline editing** — add clips, position them on tracks (drag or numeric input), trim source in/out points, split at a chosen time, move between tracks, and remove clips. Same-track overlaps and out-of-range trims are rejected with clear errors.
- **Undo/redo** — every editing operation is reversible; undo restores the exact prior timeline state.
- **Preview** — a source preview plays the original file (with seeking via HTTP range requests), clearly separated from the edited-timeline preview, which plays clips back-to-back in the browser (an approximation; Export renders the real file).
- **Export** — deterministic FFmpeg rendering as a cancellable background job with progress: clips are rendered in timeline order with correct trims, gaps become black/silent segments, audio-less clips get silence, and the output is verified to exist and match the expected duration. MP4 (H.264/AAC) output.
- **Persistence** — timelines save/reopen in the versioned `.neuralcut` format (schema v2; v1 projects are migrated automatically).

## What worked in Phase 1 (foundation)

- Local FastAPI backend and same-origin vanilla-JavaScript frontend.
- Validated frontend/backend HTTP communication with problem-detail error responses.
- Centralized, validated configuration from defaults, JSON, environment variables, and CLI options.
- Versioned `.neuralcut` JSON project files with atomic save and validated load.
- Create/open/save/close project flow and persisted recent-project list.
- Background job manager with progress, cooperative cancellation, failure reporting, and a built-in `demo` job type.
- Rotating structured JSON logs plus health, diagnostics, configuration, and log endpoints/views.
- Integration adapters with explicit planned/unavailable status (media probing became real in Phase 2; AI models, GPU scheduling, evaluation, and self-improvement remain planned/unavailable).
- Automated pytest suite and GitHub Actions workflow for Ubuntu and Windows test runs.
- A Tauri 2 desktop-shell skeleton under `src-tauri/` for later Windows packaging.

## What is intentionally not implemented yet

- No effects, transitions, keyframes, text, or compositing (multi-track overlap compositing is not supported; export flattens the timeline into one sequence).
- No object detection/tracking, masks, transcription, or other video intelligence.
- No object detection/tracking, masks, transcription, or other video intelligence.
- No AI chat, model download, model inference, or GPU initialization.
- No training, autonomous self-improvement, Windows installer, or production Tauri bundle.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phase sequence and acceptance criteria.

## Quick start on Windows

### Prerequisites

- Windows 10/11.
- Python 3.10 or newer available as `python` on `PATH`.
- **FFmpeg on `PATH`** for import probing and export (e.g. `winget install Gyan.FFmpeg` or `choco install ffmpeg`, or set `media.ffmpeg_path`/`NEURALCUT_MEDIA__FFMPEG_PATH`). ffprobe is used when present; a lone ffmpeg also works. Without ffmpeg the app still runs, but import/export report a clear unavailable error.
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

## Using the UI

1. **Dashboard** — backend health and diagnostics.
2. **Projects** — create a `.neuralcut` project by name/directory or open one by path.
3. **Current Project** — inspect the open project summary and save it.
4. **Timeline** — the editor:
   - *Import*: enter the full local path of a video file (on the machine running NeuralCut) and import it; probed metadata appears in the asset list.
   - *Add to timeline*: appends the full clip to track 0; then drag it, or select it and set timeline start/track/source in/out numerically.
   - *Split*: select a clip, set “Split at timeline time”, and split it into two clips.
   - *Undo/Redo* buttons reverse/restore any edit. **Save project** persists the timeline (edits are not auto-saved).
   - *Preview*: “Source preview” plays an original asset; “Edited timeline preview” plays the arranged clips in the browser. They are labelled separately on purpose — only Export produces the final file.
   - *Export*: enter an output `.mp4` path and size/fps, then Export. Rendering runs as a background job with progress and cancellation (also visible under Background Jobs).
5. **Background Jobs** — submit/cancel demo and render jobs and observe progress.
6. **Settings / Logs** — inspect effective configuration and recent structured logs.

Projects reference source files by path — they are not copied. If a source file moves, the timeline marks it missing and export fails with a clear error until the path is restored.

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

AI models remain disabled by default (`models.enabled=false`). NeuralCut never downloads models or initializes a GPU in Phase 1–2.

## Tauri shell status

`src-tauri/` contains a Tauri 2 development shell skeleton that launches `python -m neuralcut --no-browser` as a local backend process and points a window at `http://127.0.0.1:8765`.

It has **not been compiled or verified in the Phase 1 Linux development environment** because Rust and Windows WebView2 tooling were unavailable. It is not yet an installer or a self-contained desktop application. Packaging a frozen/bundled backend is Phase 7 work.

## Documentation

- [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — goals, scope, and vision.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, APIs, and data flow.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phases and acceptance criteria.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — setup and troubleshooting.
- [`docs/DATA_MODELS.md`](docs/DATA_MODELS.md) — project schema v2, timeline semantics, and migration.
- [`docs/TESTING.md`](docs/TESTING.md) — automated and manual verification.
- [`docs/RESEARCH.md`](docs/RESEARCH.md) — distilled research findings.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — architectural decisions and trade-offs.
- [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) — limitations and open questions.

The original Phase 1 research deliverable is preserved unchanged as [`BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md`](BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md).

## License

The package metadata currently declares MIT. Add/confirm the project license before public distribution, and review future third-party media/model licenses separately.
