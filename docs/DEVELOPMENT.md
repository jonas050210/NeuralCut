# Development Guide

## Supported development setups

NeuralCut targets Windows first. The Phase 1 Python/web foundation also runs on Linux and macOS for development.

### Required

- Python 3.10 or newer.
- `pip` and the `venv` module (included with standard Python installs).
- Git.

### Optional

- Node.js 22: frontend syntax check and Tauri CLI.
- Rust stable + Cargo: Tauri shell development.
- Windows: Microsoft C++ Build Tools and WebView2 Runtime for Tauri.
- FFmpeg/ffprobe: required for Phase 2 media import/export (see the Phase 2 FFmpeg section at the end of this file); the app runs without them but import/export report unavailable.

No NVIDIA GPU, CUDA toolkit, model files, or cloud account is required.

## Windows setup

```powershell
cd <path-to-NeuralCut>
.\scripts\setup.ps1
.\scripts\run.ps1
```

The setup script:

1. Verifies `python` is on `PATH` and is at least 3.10.
2. Creates `.venv` if needed.
3. Upgrades pip inside `.venv`.
4. Installs pinned dependencies from `requirements.txt`.

Run tests:

```powershell
.\scripts\test.ps1
```

Start without opening a browser or on a different port:

```powershell
.\scripts\run.ps1 --no-browser --port 9000
```

After setup, double-click `NeuralCut.bat` or run it from a terminal.

### PowerShell execution policy

If Windows blocks `setup.ps1`, allow scripts only for the current PowerShell session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup.ps1
```

Do not change machine-wide policy unless your organization's policy allows it.

## Linux/macOS setup

```bash
./scripts/setup.sh
./scripts/run.sh
./scripts/test.sh
```

Use a specific Python interpreter if needed:

```bash
PYTHON=python3.12 ./scripts/setup.sh
```

## Dependency management

- `pyproject.toml` declares package metadata and compatible dependency ranges.
- `requirements.txt` pins the exact runtime/test versions used for reproducible Phase 1 setup.
- Setup scripts install from `requirements.txt`.

When intentionally updating dependencies:

1. Update the virtual environment.
2. Run the full test suite.
3. Regenerate or carefully update `requirements.txt`.
4. Note user-visible/security changes in `docs/CHANGELOG.md`.

Avoid adding heavy media/AI dependencies before their roadmap phase. New dependencies should include a reason in `docs/DECISIONS.md` if they affect architecture, licensing, startup, or hardware requirements.

## Running the backend directly

```bash
.venv/bin/python -m neuralcut --help
.venv/bin/python -m neuralcut --no-browser --host 127.0.0.1 --port 8765
```

Windows:

```powershell
.\.venv\Scripts\python.exe -m neuralcut --help
.\.venv\Scripts\python.exe -m neuralcut --no-browser --port 8765
```

CLI options:

| Option | Meaning |
|---|---|
| `--host` | Bind host; keep `127.0.0.1` for normal local use |
| `--port` | Bind port (1024–65535 by config validation; CLI values should follow the same range) |
| `--config` | Explicit JSON config file |
| `--data-dir` | Explicit application data directory |
| `--no-browser` | Do not open a browser tab |

## Data, config, and logs

Default data directories:

| OS | Path |
|---|---|
| Windows | `%APPDATA%\NeuralCut\` |
| Linux | `~/.local/share/neuralcut/` |
| macOS | `~/Library/Application Support/NeuralCut/` |

Contents may include:

- `config.json` — created when settings/recent projects are persisted.
- `logs/neuralcut.log` — rotating application log.
- Future caches/derived data in later phases.

Project `.neuralcut` files are stored where the user chooses in the Projects UI.

### Configuration sources

Priority: CLI > environment > JSON config > defaults.

Examples:

```powershell
$env:NEURALCUT_PORT = "9000"
$env:NEURALCUT_LOGGING__LEVEL = "DEBUG"
$env:NEuralCUT_DATA_DIR = "D:\NeuralCutData"
.\scripts\run.ps1 --no-browser
```

Environment variables are case-insensitive on Windows but use uppercase for clarity. Nested settings use `__`, for example:

- `NEURALCUT_LOGGING__LEVEL`
- `NEURALCUT_LOGGING__STDOUT`
- `NEURALCUT_JOBS__MAX_WORKERS`
- `NEURALCUT_MODELS__ENABLED` (keep `false` in Phase 1; enabling it does not implement models)
- `NEURALCUT_MEDIA__FFMPEG_PATH`

See `config.example.json` for a complete JSON shape.

## Frontend development

The frontend has no build step. Edit files under `neuralcut/frontend/` and refresh the browser.

Check JavaScript syntax:

```bash
node --check neuralcut/frontend/assets/app.js
```

Frontend API calls must remain same-origin relative paths (`/api/v1/...`) so browser, preview proxy, and Tauri sidecar modes work.

## Tauri development (unverified skeleton)

Prerequisites beyond the Python app:

- Node.js and npm.
- Rust/Cargo.
- Windows: Microsoft C++ Build Tools and WebView2.

Typical Windows attempt:

```powershell
.\scripts\setup.ps1
npm install
$env:NEURALCUT_PYTHON = "$PWD\.venv\Scripts\python.exe"
npm run tauri:dev
```

Expected development behavior: Tauri starts the Python backend as a child process and loads `http://127.0.0.1:8765`.

This has not been compiled in the Phase 1 Linux environment. If it fails, capture the first Rust/Tauri error and update `docs/KNOWN_ISSUES.md` or fix the config in a focused change. Do not treat browser-mode success as Tauri verification.

## Troubleshooting

### `python` is not recognized on Windows

Install Python 3.10+ and enable “Add python.exe to PATH,” or use the Python Launcher to verify:

```powershell
py --version
```

Phase 1 scripts call `python`; adjust `PATH` rather than editing scripts locally.

### Port 8765 is already in use

Use another port consistently in the browser URL:

```powershell
.\scripts\run.ps1 --no-browser --port 9000
```

Then open `http://127.0.0.1:9000/`.

### Browser says backend unreachable

- Confirm the run terminal is still open and shows the NeuralCut URL.
- Check `http://127.0.0.1:8765/api/v1/health` directly.
- Check the log file under the data directory.
- Confirm no local firewall/security tool is blocking loopback Python traffic.

### Invalid configuration at startup

The backend intentionally fails fast. Read the Pydantic error, correct the JSON/environment value, and restart. To reset local config, stop the app and rename `<data-dir>/config.json`; do not delete project files.

### Project file will not open

Common causes:

- Path is a directory or missing file (`404 project_error`).
- File is not valid JSON or fails schema validation (`400 validation_error`).
- Project schema is newer than this NeuralCut version.

Project files are JSON; inspect a copy in a text editor. Do not edit the only copy without a backup.

### Logs are empty in the UI

- Confirm `logging.stdout`/`file` settings; the UI reads the file handler path.
- Check the `file` value returned by `/api/v1/logs`.
- If running a test/custom data dir, logs are under that data dir, not the default profile.

### FFmpeg/model/GPU status says unavailable

For models/GPU/evaluation that is expected — they are later phases and models are disabled by default. For media it means ffmpeg was not found: install it or set `media.ffmpeg_path` (see the Phase 2 FFmpeg section below), then restart and re-check diagnostics (`probe_mode` should be `ffprobe` or `ffmpeg`).

## Code quality

- Run tests before submitting changes.
- Keep public Python functions typed.
- Run `node --check` for frontend JS.
- Optional local linting with Ruff is configured in `pyproject.toml`, but Ruff is not a pinned Phase 1 dependency.

## Phase 2: FFmpeg prerequisite

Import probing and export require ffmpeg:

- **Windows:** `winget install Gyan.FFmpeg` or `choco install ffmpeg`, or download a static build and add it to `PATH`. ffprobe (included in those packages) is preferred; a lone ffmpeg also works via the parsing fallback.
- **Linux:** `sudo apt install ffmpeg` (or your distro's package).
- **Config override:** set `media.ffmpeg_path` / `media.probe_path` in `config.json`, or `NEURALCUT_MEDIA__FFMPEG_PATH` / `NEURALCUT_MEDIA__PROBE_PATH` environment variables.
- Check `GET /api/v1/diagnostics` → `media` to confirm what was resolved (`probe_mode`: `ffprobe` or `ffmpeg`).

Rendering writes temporary segment files under `<data_dir>/render-tmp/` and deletes them after each export. Exports always re-encode (libx264/AAC) and are verified by probing the finished file; a duration mismatch fails the job instead of reporting success.

For tests, `neuralcut/tests/media_helpers.py` generates tiny synthetic videos with ffmpeg lavfi sources. Tests that need a real binary skip when none is available; installing the optional `imageio-ffmpeg` pip package into the dev venv is a convenient way to get one locally (it is not a runtime dependency).

## Phases 3–4 notes

- **Analysis artifacts** are written to `<data_dir>/analysis/<fingerprint>.json`. Deleting that folder is safe; artifacts regenerate on demand. The Analyze button reuses cached artifacts when the source fingerprint is unchanged; `POST .../analyze` with `{"force": true}` forces recomputation.
- **Motion detection** is pure Python on 96×54 grayscale frames sampled at 5fps (max 300 frames). It needs no model, no GPU, and no network — and it only finds *moving* regions (see `docs/KNOWN_ISSUES.md`).
- **Optional transcription:** `pip install faster-whisper` plus `"models": {"enabled": true}` in the config enables CPU ASR (the `tiny` model downloads on first use — that is the only model download in the app, and it is opt-in twice over). Without it, transcript artifacts report `unavailable` and speech segments still work.
- **Effects in exports:** any clip with effects, or any cross-track overlap, switches the renderer to the compositing path (atomic intervals, keyframes at interval midpoints). Plain single-track timelines keep the faster Phase 2 path. Both paths verify output duration by probing.
