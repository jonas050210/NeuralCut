# Technical Decisions

This log records important Phase 1 decisions, reasons, consequences, and what would trigger revisiting them.

## D-001 — Tauri 2 shell + web frontend + Python backend

**Decision:** Use Tauri 2 as the intended desktop shell, a web frontend, and a Python FastAPI backend.

**Reason:** Research recommends Tauri for a small desktop footprint and Python for rapid media/AI ecosystem integration. A local HTTP boundary also lets the same backend run in a browser during development and inside Tauri later.

**Consequence:** Phase 1 is fully usable via browser while the Tauri shell remains a skeleton. Packaging a bundled Python/backend runtime is deferred to Phase 7.

**Revisit if:** Tauri/WebView2 cannot meet timeline/preview performance or packaging needs; Qt/MLT or another shell would then need a prototype comparison.

## D-002 — Vanilla JavaScript frontend for Phase 1

**Decision:** Use static HTML/CSS/vanilla JS with no build step or frontend dependencies.

**Reason:** Phase 1 screens are operational forms/diagnostics, not a complex timeline. Zero build tooling makes Windows setup and debugging simpler.

**Consequence:** State management and component reuse are manual. The frontend validates critical API shapes and escapes rendered strings.

**Revisit if:** Phase 2 timeline interactions make vanilla state/DOM code error-prone; evaluate a typed component framework then.

## D-003 — Same-origin HTTP API instead of Tauri commands

**Decision:** Browser/Tauri frontend calls relative `/api/v1/...` endpoints served by FastAPI.

**Reason:** One contract works in browser development, tests, and future Tauri sidecar mode. It avoids hard-coding localhost in browser code and keeps Python services independently testable.

**Consequence:** The backend must be running before the UI is functional. High-frequency preview/timeline traffic in later phases may require WebSockets, binary streams, or native commands for specific paths.

**Revisit if:** profiling shows HTTP/JSON is a bottleneck or a feature needs native OS/media APIs unavailable through the backend.

## D-004 — Pydantic validation at config, HTTP, and project boundaries

**Decision:** Use Pydantic/Pydantic Settings for configuration, API request models, and project documents.

**Reason:** Fail-fast validation is central to a deterministic editor and future validated AI tool calls. It also generates useful schemas/OpenAPI documentation.

**Consequence:** Invalid config/projects fail at startup/load with explicit errors. Model changes require migration discipline.

## D-005 — Human-readable versioned JSON project files

**Decision:** Store Phase 1 projects as single `.neuralcut` JSON documents with `version: 1`, written atomically.

**Reason:** JSON is inspectable, diff-friendly, easy to validate/migrate, and sufficient for foundation metadata.

**Consequence:** Large derived analysis data should not be embedded indefinitely in the project file. Later phases may add sidecar databases/caches and keep the project document canonical for editorial state.

**Revisit if:** timeline size, collaboration, binary assets, or query needs make a database/project-bundle format necessary. Any change requires migrations and import/export compatibility.

## D-006 — Standard-library thread job manager

**Decision:** Implement background jobs with threads, a bounded semaphore, progress callbacks, and cooperative cancellation events.

**Reason:** Phase 1 jobs are local and do not justify Celery/RQ or a separate worker service. The API matches future import/analysis/render work.

**Consequence:** Jobs are process-local and not persisted/resumed. CPU/GIL-heavy future work may need subprocess workers, especially for isolation and hard cancellation of media/model processes.

**Revisit if:** a job can crash/hang the backend, needs hard termination, or must survive restart.

## D-007 — Standard-library structured logging

**Decision:** Use Python logging with a custom JSON formatter, rotation, and correlation IDs.

**Reason:** No extra dependency, predictable startup, and logs are available to diagnostics/UI.

**Consequence:** Advanced log shipping/search is out of scope. Plain-text mode is supported for humans who prefer it.

## D-008 — No GPU or model runtime initialization in Phase 1

**Decision:** Do not add CUDA, NVML, torch, llama.cpp, Whisper, or model-download dependencies. GPU status only checks whether `nvidia-smi` is on `PATH`.

**Reason:** The foundation must run on Windows laptops without NVIDIA hardware and start quickly. Research also requires careful VRAM scheduling before multiple models are resident.

**Consequence:** Diagnostics cannot report detailed VRAM/device capabilities yet. Phase 3/5 must design lazy loading and CPU fallbacks.

## D-009 — Extension adapters fail explicitly with 503

**Decision:** Planned media/model/evaluation/self-improvement operations raise `UnavailableError` with feature/phase details.

**Reason:** The product must distinguish working systems from planned systems; fake success would corrupt future tests and user trust.

**Consequence:** Frontend/diagnostics can display stable adapter statuses now, and later phases can replace implementations without changing callers abruptly.

## D-010 — Deterministic core before AI orchestration

**Decision:** Future AI will operate over structured state and validated tools; it will not directly edit files/pixels.

**Reason:** Research consistently supports deterministic media/project operations with an LLM planner/orchestrator, grammar-constrained syntax where applicable, and semantic validation in code.

**Consequence:** Phase 2 must build a robust command/tool surface before Phase 5 chat. AI quality depends on tool design and project-state retrieval, not only model choice.

## D-011 — Canonical timeline technology deferred

**Decision:** Phase 1 does not adopt OpenTimelineIO, MLT, GStreamer, MoviePy, or FFmpeg as a runtime dependency.

**Reason:** Phase 1 has no timeline/render scope. Choosing an editing/render engine without Phase 2 prototypes would be premature and increases licensing/packaging risk.

**Consequence:** `ProjectClip` is only a minimal reference shape, not a timeline commitment. Phase 2 should prototype render/preview paths and decide whether the canonical model is custom, OTIO-aligned, or engine-backed.

## D-012 — Backend binds to loopback by default

**Decision:** Default host is `127.0.0.1`; no authentication is implemented.

**Reason:** NeuralCut is a local single-user desktop app in Phase 1. Loopback limits exposure.

**Consequence:** The backend must not be exposed to a LAN/public network in this form. Any remote mode requires auth, authorization, CSRF/origin controls, and path-access policy.

## D-013 — Tauri backend packaging deferred

**Decision:** The Tauri skeleton spawns a development Python interpreter (`NEURALCUT_PYTHON` or platform default) and bundle mode is disabled.

**Reason:** Rust/WebView2 were unavailable in the foundation environment, and freezing/bundling Python plus future media tools is release engineering, not foundation scope.

**Consequence:** The shell is a starting point, not a distributable app. Phase 7 must choose and test a backend packaging method (for example frozen executable/sidecar) and upgrade path.

## D-014 — Evaluation before training

**Decision:** Future self-improvement will build fixtures, deterministic graders, feedback review, and dataset versioning before fine-tuning.

**Reason:** Research shows most early gains come from tools, prompts, retrieval, and measurable failure fixes. Training without a trustworthy evaluator risks regressions and reward hacking.

**Consequence:** Phase 6 acceptance requires sandbox gates and rollback before any candidate can replace an incumbent model/adapter.
