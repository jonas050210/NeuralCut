# Packaging and Windows Installation (Phase 7)

## What exists

- **Tauri 2 shell** (`src-tauri/`): starts the backend on a **free loopback
  port** (no fixed-port conflicts), waits until it listens, opens the
  window at that port, and kills the backend on exit. Backend resolution:
  `NEURALCUT_BACKEND_EXE` → packaged `neuralcut-backend` sidecar next to
  the shell → `NEURALCUT_PYTHON`/`python -m neuralcut` (development).
  A sibling `ffmpeg[.exe]` is passed via `NEURALCUT_MEDIA__FFMPEG_PATH`.
- **Installer config** (`tauri.conf.json`): NSIS bundle enabled,
  per-user install, icons in `src-tauri/icons/`, restrictive CSP
  (loopback-only connect/media), unified version **0.7.0**.
- **Backend sidecar build** (`scripts/build_backend.ps1`): PyInstaller
  onefile build of `neuralcut/__main__.py` with the frontend bundled as
  data, output to `src-tauri/binaries/neuralcut-backend-x86_64-pc-windows-msvc.exe`
  (git-ignored; built, not committed).

## Build steps (home PC, Windows 10/11)

1. Install Python 3.11+, Rust (rustup, MSVC toolchain), WebView2, Node 22.
2. `.\scripts\setup.ps1` — create `.venv`, install dependencies.
3. `.\scripts\test.ps1` — full test suite + ruff + frontend check.
4. `.\scripts\build_backend.ps1` — build + smoke-test the sidecar
   (`neuralcut-backend.exe --no-browser --port 8899`, open
   http://127.0.0.1:8899/, Ctrl+C).
5. FFmpeg: either rely on a system FFmpeg on PATH, or place an
   **LGPL-configured** `ffmpeg.exe` for bundling (see Licensing).
6. `npm install` then `npx tauri build` — produces the NSIS installer
   under `src-tauri/target/release/bundle/nsis/`.

## Licensing (must read before distributing)

- NeuralCut itself: MIT (see `pyproject.toml`).
- **FFmpeg**: LGPL v2.1+ or GPL v2+ depending on build configuration.
  Many popular Windows "full" builds are GPL. Do **not** redistribute a
  GPL-configured FFmpeg with NeuralCut without GPL compliance (source
  offer, license text). Prefer an LGPL build or system-FFmpeg detection.
  `src-tauri/resources/ffmpeg.LICENSE.txt` ships this notice.
- Optional models (faster-whisper, any LLM you configure) keep their own
  licenses; NeuralCut bundles none of them.
- PyInstaller bootloader and Tauri carry their own notices; include them
  in release notes when distributing.

## Data, logs, upgrades, uninstall

- App data (config, logs, agent plans/audit, improvement registry) lives
  in the platform data dir (`%APPDATA%/NeuralCut` on Windows unless
  `NEURALCUT_DATA_DIR` is set). Projects live wherever the user saves
  them and are never deleted by install/uninstall.
- Backend logs: `<data_dir>/logs/neuralcut.log` (rotating). If the app
  fails to start, run the sidecar from a terminal to see the error, and
  check that no other process uses the chosen port (`--port` flag).
- Upgrades: project files are schema-versioned JSON with migrations;
  older projects open in newer versions. There is no automatic updater;
  install the new version over the old. Rollback = reinstall the previous
  installer; project files written by newer schema versions may not open
  in older builds (the loader refuses newer schemas with a clear error).
- Uninstall (NSIS per-user) removes the application; app data and user
  projects remain — delete `%APPDATA%/NeuralCut` manually for a full wipe.

## Verification status (honest)

| Check | Status |
|---|---|
| Test suite on Windows CI runners (Python) | Verified by GitHub Actions |
| Tauri shell compiles on Windows | **Not verified** — no Rust toolchain in the dev/CI sandbox; `src-tauri` changed in Phase 7 without compilation |
| NSIS installer installs/launches on clean Windows | **Not verified** — requires the home PC steps above |
| Sidecar (PyInstaller) smoke run | **Not verified** — script provided, not executed |
| Offline first launch, no-NVIDIA machine | **Not verified** on physical hardware |

Do not claim any "Not verified" row until it has actually been run.
