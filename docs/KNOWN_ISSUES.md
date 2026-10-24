# Known Issues, Limitations, and Open Questions

This file distinguishes verified Phase 1 behavior from unverified or planned work.

## Verification limits

### Windows scripts are not yet verified on Windows

The foundation was implemented and tested in a Linux environment. GitHub Actions Windows runners passed the direct Python/Node test commands for Phase 1, but the PowerShell setup/run scripts and interactive browser flow still require a real Windows laptop run before claiming Windows setup is fully verified.

**Next check:** follow `docs/TESTING.md` on Windows 10/11 and record results.

### Tauri shell is not compiled

Rust/Cargo and the Windows WebView2 toolchain were unavailable in the development environment. `src-tauri/` is a Tauri 2 skeleton, not a verified desktop build.

Known packaging gaps:

- No bundled Python interpreter or frozen backend.
- No application icons/installer configuration.
- Bundle mode is disabled.
- The shell assumes `python -m neuralcut` works in the development checkout.

**Next check:** run `npm run tauri:dev` on Windows with Rust/WebView2 and fix any config/API issues in a focused change.

## Phase 1 functional limitations

### No editing or media functionality

There is no timeline, import, preview, render, export, transcription, tracking, effect, or AI command functionality. `ProjectAsset` and `ProjectClip` are schema references only.

### Settings UI is read-only

The Settings view displays effective config. Editing settings requires the JSON config file, environment variables, or CLI and a restart.

### Project workflow uses manual paths

The browser UI asks for directory/file paths as text. Native file dialogs should be added with the desktop shell or a later UX phase.

### One open project per backend process

`ProjectService` tracks a single current project. Opening/creating another replaces it in memory. There is no multi-window/session isolation.

### No unsaved-change tracking in the UI

Phase 1 project operations are metadata-only. Later editing phases need dirty-state tracking, autosave/recovery, and close prompts.

### Background jobs are memory-only

Jobs/results disappear when the backend exits. Running job threads are not resumed. Cancellation is cooperative; a job function that never checks `cancel_event` can continue until it returns.

### Job payloads are weakly typed at the generic API layer

The generic `POST /api/v1/jobs` accepts a JSON payload dictionary. Individual job functions must validate their own payload (the demo job does). Future domain jobs should preferably have typed submission endpoints or registered Pydantic payload schemas.

### Log endpoint reads the rotating file

The log tail endpoint reads the current rotating log file (bounded by config, default 5 MB). This is suitable for local diagnostics but not a high-volume log service.

### Recent projects are paths only

Recent entries are not validated beyond existence when listed. Missing files remain visible and are marked `[missing]`; there is no remove/repair UI yet.

### Config `data_dir` field can be confusing

The authoritative runtime data directory is resolved by `--data-dir`, `NEURALCUT_DATA_DIR`, or the platform default because the config file is normally found inside that directory. Use those mechanisms to relocate app data. The API reports the resolved context data directory.

## Security limitations

### Loopback-only trust model

The backend has no authentication and exposes local path operations suitable for a single-user desktop process. Do not bind it to `0.0.0.0` or expose it through a tunnel/reverse proxy without adding authentication, origin controls, and path authorization.

Development previews may bind broadly inside an isolated sandbox, but that is not a production security model.

### Diagnostics reveal local paths

Diagnostics/config endpoints reveal data/config paths and tool locations to anyone who can reach the local backend. This is intentional for local support but reinforces the loopback-only constraint.

## Architecture risks for later phases

### Timeline/render engine is undecided

FFmpeg alone, MLT, GStreamer, MoviePy, or a custom preview/render split have different licensing, performance, and packaging trade-offs. Phase 2 requires prototypes before committing.

### Real-time preview may outgrow same-origin JSON HTTP

Low-latency scrubbing, waveform/thumbnail streaming, and GPU preview may need binary endpoints, WebSockets, native Tauri commands, or an engine-specific preview surface.

### AI hardware claims are unmeasured

Research model sizes and speeds are not NeuralCut benchmarks. VRAM, RAM, CPU latency, thermal throttling, and model swap time must be measured on target laptops.

### Edit quality cannot be reduced to one metric

Future evaluation must combine deterministic checks, human preference, and task fixtures. A single model-judge score would be vulnerable to drift and reward hacking.

### Licensing needs phase-by-phase review

Media frameworks, codecs, ASR/diarization models, quantized LLMs, and fixture media can introduce GPL, attribution, gated-model, or redistribution constraints. No such components are bundled yet.

## Open product questions

- Which content type should Phase 2–4 optimize first: short-form, long-form, gaming, or general editing?
- Is cloud assistance prohibited entirely, allowed for offline data generation, or allowed only as explicit per-action escalation?
- Which ASR languages are launch-critical beyond English/German?
- Is NeuralCut intended for private use, open-source distribution, or commercial release?
- Should the canonical timeline model be custom, OpenTimelineIO-aligned, or directly engine-backed?
- What minimum Windows laptop specification should be treated as the performance baseline?

Record decisions in `docs/DECISIONS.md` when answered; do not encode guesses as requirements.
