# Known Issues, Limitations, and Open Questions

This file distinguishes verified behavior from unverified or planned work.

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

## Phase 2 functional limitations

### Agent limits (Phase 5)

- The **built-in planner is intentionally narrow** (documented intent list in the UI/`planner.py`); anything else returns a clarification. It resolves clips/assets by unique name substring — ambiguous names are refused, not guessed.
- **External model quality is unmeasured**: no real LLM endpoint was available in the dev/CI environment. Model plans are validated identically to built-in plans, but a model can still propose a *valid yet unwanted* plan — that is what the approval step is for. Never enable auto-approval for edit/external tools.
- Plan undo reverses applied *edit* steps via the timeline undo stack; it cannot un-run jobs (analysis/render) a plan started — cancel those in Background Jobs.
- Agent plans/audit live under `<data_dir>/agent/`; they are not part of the project file and are not encrypted. Audit records contain the user's instruction text.

### Video intelligence limits (Phase 3)

- **Motion detector, not a semantic detector:** tracks are `moving_object` regions from background subtraction at 96×54 / 5fps sampling. Static objects are invisible to it, a moving camera turns the whole frame into motion, lighting changes create false regions, objects that stop for >2s end their track, and small/fast objects may be missed or merged. It must never be described as car/person recognition.
- **Transcription is off by default:** without the optional faster-whisper install and `models.enabled=true`, users get speech *segments* only. ASR accuracy, word timing, and model-download behaviour are unverified in the test environment.
- **Heuristic captions/embeddings are retrieval aids**, based on dominant color + motion and a 12-bin color histogram — not semantic scene understanding.
- Analysis sampling caps at 300 frames (~60s at 5fps); longer assets are analyzed over their opening portion only for tracks/motion (shots still span the full file). This truncation is not yet surfaced in the UI beyond artifact timing.
- Artifact fingerprints use sampled chunks + size/mtime; a same-size edit preserving mtime could theoretically go stale — use Analyze with force (re-analyze) after replacing a source file in place. (The Analyze button currently submits `force=false`; the API accepts `force=true`.)

### Effects limits (Phase 4)

- **ffmpeg version sensitivity (found by CI):** with the runner's ffmpeg 8.x, framesync-based effect chains could emit runaway video stream durations (a 2s clip reported as 2048s) while audio stayed correct. Composite segments are therefore hard-bounded with `trim`/`setpts` + `atrim`/`asetpts` and an output `-t`, making segment length exact across ffmpeg builds. Prefer a current ffmpeg (7.x/8.x) and report render-duration mismatches with the ffmpeg version attached.
- Keyframes are evaluated once per atomic render interval (at its midpoint), so a fast ramp inside one long clip renders as steps at clip boundaries rather than a continuous ramp. The preview evaluates at the playhead, so preview/export can differ slightly on ramps.
- No transitions, text, speed ramps, or mask-based effects (track masks are analysis data, not yet effect inputs).
- Compositing re-encodes every interval; long multi-track projects render slower than the Phase 2 single-track path.

### Editing core limits

- Export is **MP4 (H.264/AAC) only**; no other containers/codecs, transitions, text, or speed changes. Effects/keyframes and multi-track compositing are supported (Phase 4) within the registry's effect set.
- Same-track overlaps are rejected at edit time by the project model; overlapping clips on *different* tracks are composited in timeline order.
- **Edited preview is approximate:** the browser plays source ranges back-to-back; seams at clip boundaries and gap timing are not frame-accurate. Only the FFmpeg export is the final output.
- **Assets are path references, not copies.** Moving/deleting a source file marks it missing; there is no relink UI yet.
- **Undo history is memory-only** (max 100 snapshots), resets when switching projects, and edits are not auto-saved — unsaved edits are lost if the backend exits.
- Probing without ffprobe uses `ffmpeg -i` text parsing, which reports fewer fields (no format name) and may vary slightly by ffmpeg build.

### Phase 1 limitations that remain

- The Settings UI is still read-only, projects are single-open per process, and jobs/agent plans are memory/app-data only (see below). Transcription, tracking, effects, and AI commands have since landed in Phases 3–5.

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

### Timeline/render engine (decided for Phase 2, revisit if needed)

Phase 2 chose a custom timeline model + direct FFmpeg segment/concat rendering (D-017). MLT/GStreamer/OTIO were not adopted; revisit if compositing, effects, or frame-accurate preview outgrow this design. FFmpeg's own licensing (GPL builds vs LGPL builds) must be reviewed before bundling it in a distributed installer (Phase 7).

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

### Self-improvement limits (Phase 6)

- Benchmark cases cover the built-in planner's documented intents on synthetic fixtures. They do not measure real-model plan quality, open-ended editing quality, or performance on real footage; treat accuracy as a regression signal, not a quality score.
- Promotion changes the registry's champion record only. Applying a champion configuration to the live app remains a manual config change by the user; nothing rewrites running settings automatically.
- Feedback is a local JSONL file containing the instruction/note text the user chose to record. It is never uploaded; delete it from the Improvement view/API or remove `<data_dir>/improvement/feedback.jsonl`.

### Packaging limits (Phase 7)

- The Tauri shell and installer configuration are **uncompiled and unverified** (no Rust/WebView2 in the development environment); the PyInstaller sidecar script is likewise unrun. Physical Windows verification steps and current status are tracked in `docs/PACKAGING.md`.
- No code signing or auto-update mechanism exists; Windows SmartScreen warnings are expected for unsigned installers.
