# Changelog

All significant changes to NeuralCut are recorded here.

## [Unreleased]

- Nothing yet.

## [0.2.0] — 2026-10-24 — Phase 2: Editing Core

### Added

- Project schema v2 with raw-dict migration from v1 (sequential per-track placement, source-range preservation); new `docs/DATA_MODELS.md`.
- Media import/probing via ffprobe (JSON) with an ffmpeg-output fallback, including the optional `imageio-ffmpeg` binary; probed metadata stored on assets.
- `TimelineService`: add/move/trim/split/remove clips and remove assets, with same-track overlap, source-range, unknown-id, and missing-media validation; every edit is one validated, atomic state transition.
- Snapshot-based undo/redo (max 100 states) for all editing operations.
- FFmpeg render engine: timeline-order segments, gap segments, silence for audio-less clips, concat-demuxer assembly, progress, subprocess-terminating cancellation, and output existence/duration verification. Registered as the `render` background job with a typed `/projects/current/render` endpoint that snapshots the project at submission.
- HTTP Range streaming of source media (`/api/v1/media/assets/{id}/content`) for seekable preview.
- Timeline UI: import, asset list with probed metadata/missing markers, drag-to-move and click-to-select clips, numeric move/trim/split/remove editor, undo/redo, save, source vs. edited preview players, and export form with live job progress.
- Tests: timeline operations, exact undo/redo restoration, v1→v2 migration, persistence roundtrip, real probing, rendering (duration/probe verification, missing-media and cancellation errors), and editing/render API flows — using short ffmpeg-generated videos.

### Not included

- Effects/transitions/compositing, object tracking, AI chat, model inference/training, self-improvement, Windows installer.

### Verification note

Automated suite (42 tests) and a live end-to-end smoke test (import → add → split → undo → save → render job → probe-verified 2.02s MP4) passed in the Linux development environment using an ffmpeg 7.0.2 binary. Windows-laptop verification (PowerShell scripts, ffmpeg installation, interactive browser flow, Tauri) is still pending — see `docs/TESTING.md`.

## [0.1.0] — 2026-10-24 — Phase 1: Foundation

### Added

- Python/FastAPI local backend with uvicorn entry point.
- Same-origin vanilla JavaScript frontend with dashboard, projects, current project, jobs, settings, and logs views.
- Centralized Pydantic configuration with defaults, JSON config, environment variables, CLI overrides, and atomic save.
- Versioned `.neuralcut` JSON project model with atomic persistence, validation, migration registry, single-project service, and persisted recent projects.
- Background job manager with status, progress, cooperative cancellation, typed failure reporting, TTL purge, and a validated demo job.
- Structured JSON/plain logging with rotation, correlation IDs, diagnostics, log tail endpoint, and RFC 7807-style error responses.
- Explicit unavailable/planned adapters for media processing, AI models, GPU resources, evaluation, and self-improvement.
- Tauri 2 desktop shell skeleton that can launch the Python backend in development.
- Windows and Linux/macOS setup/run/test scripts plus a Windows batch launcher.
- Pytest suite covering config, logging, projects, jobs, API, frontend serving, and adapters.
- GitHub Actions workflow for Ubuntu/Windows tests on Python 3.11/3.12.
- Project knowledge base: overview, architecture, roadmap, research, decisions, modules, testing, development, AI infrastructure, self-improvement, known issues, and agent instructions.

### Not included

- Timeline/editing operations, media import/render/export, video intelligence, effects, AI agent/model inference, training/self-improvement, or a Windows installer.

### Verification note

Phase 1 was implemented and automated-tested in a Linux environment, and the initial GitHub Actions run passed on Ubuntu and Windows runners (Python 3.11/3.12). Windows laptop script/UI execution and Tauri compilation still require follow-up verification as documented in `docs/TESTING.md` and `docs/KNOWN_ISSUES.md`.
