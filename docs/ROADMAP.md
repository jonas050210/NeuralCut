# Roadmap

NeuralCut is developed in explicit phases. **Do not begin a later phase automatically.** Each phase requires owner approval and should end with its acceptance criteria verified and documented.

## Phase 1 — Foundation

**Status:** implemented in this repository; Windows/Tauri verification still required on a Windows machine.

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
- [ ] Windows PowerShell setup/run/test scripts are verified on a Windows laptop.
- [ ] Tauri shell compiles and launches the backend on Windows with Rust/WebView2 installed.

## Phase 2 — Editing Core

**Status:** not started.

### Scope

- Timeline data model and timeline UI.
- Media import/probing and asset management.
- Clip operations such as insert, trim, split, move, delete, and track management.
- Deterministic command model with undo/redo.
- Preview strategy (proxy/FFmpeg-backed or engine-backed) and render/export pipeline.
- Project schema migration from v1 as needed.

### Acceptance criteria

- [ ] A user can import supported local media and see accurate asset metadata.
- [ ] A user can build a multi-clip timeline, save/reopen it, and get identical project state.
- [ ] Core clip operations are deterministic, validated, and covered by unit/API/UI tests.
- [ ] Undo/redo restores exact prior timeline states for supported operations.
- [ ] A timeline can be rendered/exported to a playable file with correct duration, ordering, and A/V sync on fixture media.
- [ ] Rendering runs as a cancellable background job with progress and actionable errors.
- [ ] The core works on a Windows laptop without an NVIDIA GPU.
- [ ] Documentation and known codec/license limitations are updated.

## Phase 3 — Video Intelligence

**Status:** not started.

### Scope

- Import-time or on-demand analysis jobs.
- Shot/scene detection and derived shot index.
- Speech transcription with word timing where feasible.
- Embeddings/captions for retrieval.
- Object detection, tracking, and mask representations.
- Analysis caching, invalidation, status, and storage management.

### Acceptance criteria

- [ ] Analysis runs as background jobs and reports completion without automatically editing the timeline.
- [ ] Shot boundaries and transcript artifacts are stored, versioned, and reloadable without reprocessing unchanged media.
- [ ] Object tracks/masks are represented in project/derived data and can be inspected in the UI.
- [ ] Analysis can be cancelled and resumed/restarted safely.
- [ ] CPU fallback behavior and optional GPU acceleration are documented and measured on target-class hardware.
- [ ] Fixture tests verify expected shots/transcript timing/track persistence within documented tolerances.
- [ ] Model licenses, download/size disclosures, and opt-in behavior are documented.

## Phase 4 — Effects and Animation

**Status:** not started.

### Scope

- Keyframed properties and interpolation.
- Compositing model and effect chains.
- Initial effects including glow and bloom.
- Effect parameter validation, presets, enable/disable, and ordering.
- Preview/render parity strategy.

### Acceptance criteria

- [ ] Users can add, reorder, disable, and remove effects on supported clips/tracks.
- [ ] Keyframes can be created/edited/deleted and persist exactly through save/load and undo/redo.
- [ ] Glow/bloom and the initial effect set render deterministically in export fixtures.
- [ ] Invalid effect parameters are rejected with actionable UI/API errors.
- [ ] Preview degradation/fallback is explicit when real-time rendering is not feasible.
- [ ] Performance is measured on a Windows laptop without requiring a discrete NVIDIA GPU.
- [ ] Effect data model and render semantics are documented.

## Phase 5 — AI Editing Agent

**Status:** not started.

### Scope

- Chat/agent panel.
- Local model integration and deterministic model routing.
- Project-state/context retrieval from structured state and analysis artifacts.
- Planner that emits validated tool calls or an editable plan.
- Controlled execution through the deterministic editing core, with approval policy, undo, and audit log.
- Optional larger/cloud escalation only if explicitly approved by product policy and user action.

### Acceptance criteria

- [ ] The agent can answer project questions from stored project/analysis state without reprocessing raw video unnecessarily.
- [ ] Supported natural-language requests produce a visible plan/tool-call sequence before execution, unless a documented low-risk auto-approval policy applies.
- [ ] Every tool call is schema- and semantics-validated; invalid calls cannot mutate the project.
- [ ] Executed agent actions are undoable and recorded in an audit/event log.
- [ ] The agent refuses or asks for clarification on ambiguous/unsupported requests rather than fabricating media or IDs.
- [ ] Local models are lazy-loaded, optional, and scheduled within a documented memory/VRAM policy.
- [ ] Headless task fixtures measure success/failure rates for supported intents.
- [ ] No cloud escalation occurs silently.

## Phase 6 — Self-Improvement

**Status:** not started.

### Scope

- Evaluation fixture library and deterministic graders.
- Failure mining and human review workflow.
- Explicit user feedback capture (accept/reject/corrections) with privacy controls.
- Versioned datasets and experiment tracking.
- Isolated candidate experiments, optional adapter fine-tuning, promotion gates, and rollback.
- Safeguards against leakage, benchmark overfitting, reward hacking, and regressions.

### Acceptance criteria

- [ ] A sandbox evaluation run executes against fixture copies, never user projects, and produces a reproducible report.
- [ ] Train/validation/held-out data are split by source video and task template; held-out data is access-controlled in the pipeline.
- [ ] Feedback is opt-in, inspectable, and deletable; no silent training on user media occurs.
- [ ] Candidate improvements are compared with the incumbent on held-out and regression suites.
- [ ] Promotion requires deterministic gates plus human spot-checks; rollback to the previous version is one action.
- [ ] Experiments record code/config/model/data versions sufficient to reproduce results.
- [ ] Canary checks detect major general-capability or tool-calling regressions.
- [ ] Documentation explains what improved, what regressed, and why a candidate was promoted or rejected.

## Phase 7 — Packaging and Release

**Status:** not started.

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
