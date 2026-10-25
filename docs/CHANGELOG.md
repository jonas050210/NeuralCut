# Changelog

All significant changes to NeuralCut are recorded here.

## [Unreleased]

### Fixed (hardening pass)

- **Logging isolation (High):** isolated containers (benchmark runner) no longer reconfigure/close the live application's root logging handlers (`Container(configure_logging=False)`); regression test proves handlers and live log file survive a full benchmark run.
- **Held-out sealing:** routine benchmark/experiment evaluation now excludes held-out cases; held-out is reachable only via baseline recording and the explicit, audit-logged gate-evaluation step required before promotion.
- **Experiment state machine:** legal status transitions enforced; promoted experiments cannot be re-evaluated/demoted or re-promoted; invalid rollback sequences rejected.
- **Registry audit consistency:** audit-write failures no longer fail already-persisted operations; the error is recorded (`registry.last_audit_error`, surfaced in `/improvement/status`) and logged.
- **Job queue:** queued jobs no longer fail after a fixed 300 s wait; they wait cancellably. Job API responses redact payloads (render payloads previously embedded whole project documents).
- **Feedback:** rating range validated in the store itself; status uses a streaming count instead of parsing the whole feedback file.
- **Agent:** chat context is snapshotted under the agent lock; snapshot failures during execution mark plan undo unavailable explicitly.

### Added

- Benchmark reports now include per-case agent tool-call trajectories and explicit `held_out_accessed`/`splits_evaluated` markers.
- `scripts/check_packaging.py` packaging-configuration validation, wired into CI.
- `.github/workflows/windows-installer.yml`: builds the NSIS `setup.exe` on Windows runners (PyInstaller sidecar + health smoke test + Tauri build) and uploads it as a CI artifact. Desktop shortcut via NSIS hooks.
- Fine-tuning readiness checked (no training run): training libraries/entrypoint are intentionally absent in-app; dry-run spec validated. Home-PC steps unchanged.

## [0.7.0] — 2026-10-24 — Phases 5 (hardening), 6, and 7

### Fixed (Phase 5 hardening)

- **Plan undo correctness:** agent plan undo now restores the exact pre-plan snapshot and refuses when the timeline changed since execution (previously it popped N entries from the global undo stack, reverting unrelated manual edits). Partially executed plans are undoable per plan; `undo`/`redo` tools no longer inflate the applied-edit count.
- **Thread safety:** `TimelineService` and `ProjectService` serialize read-modify-write cycles and project lifecycle with re-entrant locks.
- **Persistence visibility:** agent plan/audit write failures are logged instead of silently swallowed; plan retention cap (200) and audit rotation (2 MB) added.
- **Model parsing:** model JSON extraction tolerates code fences and surrounding prose.
- **CI:** every test file now runs in CI, including `test_agent.py` and `test_improvement.py`; Ruff and the frontend syntax check are CI steps.
- Documentation contradictions in Known Issues corrected.

### Added (Phase 6 — Self-Improvement)

- `backend/improvement/`: versioned synthetic benchmark datasets (provenance, deterministic template-based train/val/held-out splits, sealed held-out), isolated benchmark runner (temporary container/projects; user projects untouched — sentinel-tested) with deterministic graders and failure-category taxonomy, baseline reports, opt-in local feedback store (inspect/export/delete; refuses while disabled), experiment registry with per-split promotion gates, mandatory human spot-check promotion, one-action rollback, and audit log. Fine-tuning exists only as validated dry-run job specifications; training execution refuses in-app.

### Added/Changed (Phase 7 — Packaging)

- Tauri shell: free-port selection, sidecar/dev backend resolution, backend readiness wait, process cleanup, restrictive CSP; NSIS installer configuration with icons; unified version 0.7.0; PyInstaller sidecar build script (`scripts/build_backend.ps1`); project saves fsync before atomic replace; actionable port-in-use error at backend startup; `docs/PACKAGING.md` (build steps, FFmpeg licensing, upgrades/uninstall, honest verification table).

### Not verified

- Tauri compilation, NSIS installer behaviour, PyInstaller sidecar, and all physical-Windows flows (no Rust/Windows in this environment). See docs/PACKAGING.md.

## [0.5.0] — 2026-10-24 — Phase 5: AI Editing Agent

### Added

- Agent backend (`backend/agent/`): tool registry with strict argument schemas and risk levels (read/edit/external); deterministic built-in planner (bounded intents; clarification instead of guessing); optional OpenAI-compatible local/cloud model routing with JSON-plan parsing, validation, and built-in fallback; approval-gated execution through `TimelineService`/job submission with per-step re-validation, partial-failure recording, per-plan undo, persisted plans, and a JSONL audit log.
- Chat UI (AI Agent view): instruction form, plan review with steps/results, approve/reject/undo controls, model-route status, and audit viewer.
- Config: `models.provider` (`builtin|local|cloud`), `endpoint`, `model`, `allow_cloud`, `api_key_env`, `timeout_seconds`. Cloud is never contacted unless explicitly allowed and keyed via environment variable; no model loads at startup.
- Tests: tool-schema rejection (including shell-style tools), read-only auto-execution, approval gating, undo-plan exactness, ambiguity/clarification, rejection, invalid-model fallback, execution-time semantic validation, cloud opt-in routing, and a full API flow including an agent-requested render job.

### Not included

- Hosted/in-process model inference, fine-tuning or self-improvement (Phase 6), installer (Phase 7), and any Phase 8 audit work.

## [0.4.0] — 2026-10-24 — Phases 3 (Video Intelligence) + 4 (Effects and Animation)

### Added

- **Phase 3 analysis** (`backend/intelligence/`): per-asset background analysis jobs — ffmpeg scene-cut shot detection, speech/silence segments, per-shot color-histogram embeddings + heuristic captions with text/similarity search, and CPU motion object detection/tracking (background subtraction, connected components, greedy tracking) with normalized bboxes and RLE masks at 96×54. Artifacts are versioned sidecar JSON under `<data_dir>/analysis/`, cached by source fingerprint with automatic invalidation. Optional faster-whisper transcription only when installed and `models.enabled=true`; otherwise an honest `unavailable` status. UI: analyze/view per asset, artifact summary, track boxes overlaid on the source preview. Analysis never modifies the timeline.
- **Phase 4 effects** (project schema v3 with v2→v3 migration): ordered per-clip effect chains — transform (opacity/scale/x/y), color, blur, glow, bloom — with a single validating registry, presets, enable/disable/reorder, and linear/hold keyframes for every parameter. All effect operations go through `TimelineService` (validated, one undo step each) and persist exactly through save/load.
- **Compositing renderer**: timelines with effects or overlapping tracks render as atomic intervals composited bottom-to-top (overlay with keyframed opacity/scale/position, per-clip effect filter chains, audio mixing; silence for audio-less layers), then concatenated and duration-verified as before. Simple single-track timelines keep the faster Phase 2 path.
- Tests: moving-car detection/tracking/mask fixture, scene-change shots, cache invalidation, analysis cancellation + API flow; keyframe evaluation, effect validation/CRUD/presets/reorder/persistence/undo, v2→v3 migration, and pixel-verified renders (brightness change, glow spread, two-track compositing, opacity blending). A keyframe range-validation bug found by these tests was fixed.

### Not included

- Semantic ML object classification, transitions, text, AI chat (Phase 5), training/self-improvement (Phase 6), Windows installer (Phase 7), and any Phase 8 audit work.

### Verification note

56 automated tests pass in the Linux dev environment plus a live end-to-end smoke test (analyze moving-car video → 1 track, displacement 0.70; compositing render with fade-in preset + keyframed glow verified at 3.04s). Windows-laptop verification remains pending — see `docs/TESTING.md`.

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
