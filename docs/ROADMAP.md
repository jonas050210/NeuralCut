# Roadmap

NeuralCut is developed in explicit phases. **Do not begin a later phase automatically.** Each phase requires owner approval and should end with its acceptance criteria verified and documented.

## Phase 1 — Foundation

**Status:** implemented and merged (PR #1); Windows/Tauri verification still required on a Windows machine.

### Scope

- Modular application architecture and startup/shutdown.
- Local frontend/backend communication with validation and error handling.
- Centralized configuration with defaults and validation.
- Project data model, creation, validation, save/load, schema versioning, and recent projects.
- Structured logging, diagnostics, typed errors, and reproducible dependencies.
- Background jobs with status, progress, cooperative cancellation, and error reporting.
- Extension interfaces for media, AI models, GPU resources, evaluation, and self-improvement.
- Automated tests, setup scripts, CI definition, and project knowledge base.
- Tauri 2 shell skeleton for future desktop packaging.

### Out of scope

Timeline, editing actions, media processing, effects, tracking, AI commands, model training, and autonomous self-improvement.

### Acceptance criteria

- [x] Backend starts locally and serves the frontend.
- [x] Frontend can call health/diagnostics/config/log APIs and display validated responses.
- [x] Invalid API/config/project inputs produce clear errors rather than silent failure.
- [x] A project can be created, saved, closed, reopened, and appears in recent projects.
- [x] Project files are versioned JSON and written atomically.
- [x] A demo background job can complete, fail, report progress, and be cancelled cooperatively.
- [x] Logs are written to a rotating structured log file and can be viewed through the API/UI.
- [x] Media/model/GPU/evaluation/self-improvement adapters expose explicit planned/unavailable status.
- [x] Automated tests pass in the development environment.
- [x] Documentation explains architecture, development, testing, limitations, and next phases.
- [x] GitHub Actions test jobs pass on Ubuntu and Windows runners for Python 3.11 and 3.12.
- [ ] Windows PowerShell setup/run/test scripts are verified on a Windows laptop.
- [ ] Tauri shell compiles and launches the backend on Windows with Rust/WebView2 installed.

## Phase 2 — Editing Core

**Status:** implemented (schema v2, timeline service + UI, undo/redo, FFmpeg export, automated tests with generated videos, live smoke test passed). Remaining: verification on a physical Windows laptop (PowerShell setup, ffmpeg install path, browser flow).

### Scope

- Timeline data model and timeline UI.
- Media import/probing and asset management.
- Clip operations such as insert, trim, split, move, delete, and track management.
- Deterministic command model with undo/redo.
- Preview strategy (proxy/FFmpeg-backed or engine-backed) and render/export pipeline.
- Project schema migration from v1 as needed.

### Acceptance criteria

- [x] A user can import supported local media and see accurate asset metadata. (ffprobe JSON, ffmpeg fallback; tested with generated videos)
- [x] A user can build a multi-clip timeline, save/reopen it, and get identical project state. (persistence roundtrip test)
- [x] Core clip operations are deterministic, validated, and covered by unit/API tests. (UI is exercised by live smoke test, not automated browser tests)
- [x] Undo/redo restores exact prior timeline states for supported operations. (snapshot history; exact-state test)
- [x] A timeline can be rendered/exported to a playable file with correct duration, ordering, and A/V sync on fixture media. (duration verified by probe; sync verified only structurally — same trim applied to A/V — not by perceptual sync test)
- [x] Rendering runs as a cancellable background job with progress and actionable errors. (subprocess is terminated on cancel)
- [ ] The core works on a Windows laptop without an NVIDIA GPU. (No GPU is used by design; GitHub Windows runners run the suite, but a physical-laptop run is still pending)
- [x] Documentation and known codec/license limitations are updated. (MP4/H.264+AAC only; see KNOWN_ISSUES)

## Phase 3 — Video Intelligence

**Status:** implemented (CPU, model-free). Semantic ML detection/classification and default ASR remain opt-in future work — see acceptance notes.

### Scope

- Import-time or on-demand analysis jobs.
- Shot/scene detection and derived shot index.
- Speech transcription with word timing where feasible.
- Embeddings/captions for retrieval.
- Object detection, tracking, and mask representations.
- Analysis caching, invalidation, status, and storage management.

### Acceptance criteria

- [x] Analysis runs as background jobs and reports completion without automatically editing the timeline. (API test asserts timeline is untouched)
- [x] Shot boundaries and transcript artifacts are stored, versioned, and reloadable without reprocessing unchanged media. (fingerprinted sidecar store; cache test; transcript artifact stores status/engine/segments)
- [x] Object tracks/masks are represented in project/derived data and can be inspected in the UI. (sidecar artifacts; track list + preview overlay)
- [x] Analysis can be cancelled and resumed/restarted safely. (cooperative cancellation between steps; restart is a fresh job; cached steps make re-runs cheap — there is no mid-step resume)
- [ ] CPU fallback behavior and optional GPU acceleration are documented and measured on target-class hardware. (CPU-only by design and documented; no GPU path exists and no Windows-laptop measurements yet)
- [x] Fixture tests verify expected shots/transcript timing/track persistence within documented tolerances. (moving-car track/mask, scene-cut shots, speech segments; ASR *timing* is unverified because ASR is opt-in and not installed in the test environment)
- [x] Model licenses, download/size disclosures, and opt-in behavior are documented. (no model is bundled/downloaded by default; optional faster-whisper path documents its `tiny` model download at first use)

## Phase 4 — Effects and Animation

**Status:** implemented (schema v3, registry-driven effects, compositing renderer).

### Scope

- Keyframed properties and interpolation.
- Compositing model and effect chains.
- Initial effects including glow and bloom.
- Effect parameter validation, presets, enable/disable, and ordering.
- Preview/render parity strategy.

### Acceptance criteria

- [x] Users can add, reorder, disable, and remove effects on supported clips/tracks. (per-clip chains; tracks supported via clips on them)
- [x] Keyframes can be created/edited/deleted and persist exactly through save/load and undo/redo. (roundtrip + undo/redo tests)
- [x] Glow/bloom and the initial effect set render deterministically in export fixtures. (pixel-verified glow spread, brightness, compositing renders)
- [x] Invalid effect parameters are rejected with actionable UI/API errors. (registry ranges; API returns 400 with range details)
- [x] Preview degradation/fallback is explicit when real-time rendering is not feasible. (edited preview is labelled an approximation and uses CSS equivalents)
- [ ] Performance is measured on a Windows laptop without requiring a discrete NVIDIA GPU. (no GPU is used; physical-laptop measurements still pending)
- [x] Effect data model and render semantics are documented. (`docs/DATA_MODELS.md`, D-022)

## Phase 5 — AI Editing Agent

**Status:** implemented. The default route is the deterministic built-in planner; external local/cloud models are optional and go through identical validation and approval.

### Scope

- Chat/agent panel.
- Local model integration and deterministic model routing.
- Project-state/context retrieval from structured state and analysis artifacts.
- Planner that emits validated tool calls or an editable plan.
- Controlled execution through the deterministic editing core, with approval policy, undo, and audit log.
- Optional larger/cloud escalation only if explicitly approved by product policy and user action.

### Acceptance criteria

- [x] The agent can answer project questions from stored project/analysis state without reprocessing raw video unnecessarily. (context built from timeline + cached analysis status)
- [x] Supported natural-language requests produce a visible plan/tool-call sequence before execution, unless a documented low-risk auto-approval policy applies. (read-only plans auto-execute; everything else is an approvable draft)
- [x] Every tool call is schema- and semantics-validated; invalid calls cannot mutate the project. (registry schemas + re-validation at execution; tested with nonexistent IDs)
- [x] Executed agent actions are undoable and recorded in an audit/event log. (per-plan applied-edit counting, undo-plan, JSONL audit)
- [x] The agent refuses or asks for clarification on ambiguous/unsupported requests rather than fabricating media or IDs. (clarification plans have zero steps; tested)
- [x] Local models are lazy-loaded, optional, and scheduled within a documented memory/VRAM policy. (nothing loads at startup; the app never hosts model weights — a user-run local endpoint is called per request with a timeout; VRAM is that server's concern, bounded by `models.max_vram_gb` guidance in docs)
- [x] Headless task fixtures measure success/failure rates for supported intents. (the agent test suite covers each intent family end-to-end, incl. failure/clarification cases)
- [x] No cloud escalation occurs silently. (cloud requires provider=cloud + allow_cloud=true + env key; otherwise routing falls back to builtin and says so)

## Phase 6 — Self-Improvement

**Status:** implemented (evaluation/feedback/experiments/promotion; fine-tuning prepared as dry-run only, never executed in-app).

### Scope

- Evaluation fixture library and deterministic graders.
- Failure mining and human review workflow.
- Explicit user feedback capture (accept/reject/corrections) with privacy controls.
- Versioned datasets and experiment tracking.
- Isolated candidate experiments, optional adapter fine-tuning, promotion gates, and rollback.
- Safeguards against leakage, benchmark overfitting, reward hacking, and regressions.

### Acceptance criteria

- [x] A sandbox evaluation run executes against fixture copies, never user projects, and produces a reproducible report. (isolated temp container; sentinel-project test)
- [x] Train/validation/held-out data are split by task template + setup (deterministic cycle, provenance per case); held-out is sealed — used by promotion gates only, never for training/tuning inputs.
- [x] Feedback is opt-in (default off, recording refuses while disabled), inspectable, exportable, and deletable. No silent training on user media occurs anywhere.
- [x] Candidate configurations are compared with the stored baseline per split (train/val/held-out) with tolerance gates; dataset fingerprints must match.
- [x] Promotion requires passing gates AND a named reviewer with spot_check_confirmed=true; rollback restores the previous champion in one call. There is no automatic promotion path.
- [x] Experiment/report records carry dataset version + fingerprint and the candidate model-route config; benchmark reports are reproducible from dataset version.
- [x] Per-split gates (incl. held-out presence) plus the failure-category taxonomy (wrong_plan/clarification_miss/execution_failure/harness_error) act as canaries; a split regression beyond tolerance blocks promotion.
- [x] Gates return per-check baseline/candidate values; promotion/rollback/gate outcomes are audit-logged (improvement/audit.jsonl).

## Phase 7 — Packaging and Release

**Status:** implemented as far as this environment permits — Tauri shell hardened (free port, sidecar resolution, backend cleanup), NSIS installer config + icons, PyInstaller sidecar build script, unified 0.7.0 versions, packaging/licensing docs. **Compilation, installer execution, and physical-Windows verification remain outstanding (docs/PACKAGING.md lists them explicitly as not verified).**

### Scope

- Self-contained Windows application packaging/installer.
- Bundled or managed backend runtime and required media tools.
- First-run experience, optional model downloads, disk-space checks, and upgrades/uninstall.
- Performance, memory, startup, and large-project testing.
- Usability/accessibility passes and release documentation.
- Code signing and update strategy if distributing publicly.

### Acceptance criteria

- [ ] A clean Windows 10/11 machine can install and launch NeuralCut without a developer Python environment.
- [ ] The packaged app starts without an NVIDIA GPU and without network access.
- [ ] Projects created by the packaged app can be saved/reopened after restart and upgrade.
- [ ] Installer/uninstaller behavior, app-data retention, and log locations are tested and documented.
- [ ] Startup time, idle memory, render performance, and model-memory behavior are measured on target-class laptops.
- [ ] Release checklist covers licenses, third-party notices, signing, privacy, and support diagnostics.
- [ ] A rollback/previous-version path exists for failed upgrades.
