# Testing and Verification

## Automated test command

Linux/macOS:

```bash
./scripts/test.sh
```

Windows PowerShell:

```powershell
.\scripts\test.ps1
```

Both run:

```text
python -m pytest -q
node --check neuralcut/frontend/assets/app.js
```

The Python suite lives in `neuralcut/tests/` and is configured by `pyproject.toml`.

## Current automated coverage

| Area | Test file | Coverage |
|---|---|---|
| Config | `test_config_logging.py` | Defaults, invalid port/log level, JSON save/reload, env-over-JSON priority, `NEURALCUT_CONFIG_FILE` |
| Logging | `test_config_logging.py` | JSON record shape, correlation ID, structured extras, plain-text mode |
| Projects | `test_projects.py` | Save/load roundtrip, validation, clip range, invalid JSON, future schema, migration registry, service lifecycle/recent callback, duplicate/blank names |
| Jobs | `test_jobs.py` | Completion/progress, typed failure details, cooperative cancellation, unknown/reserved payload errors, cancel-completed conflict |
| API | `test_api.py` | Health/diagnostics/config, project lifecycle, API validation, demo job lifecycle, job/log errors, frontend serving, unknown API JSON 404 |
| Adapters | `test_integration_adapters.py` | AI/evaluation/self-improvement adapters still unavailable; media adapter status/probe errors are real in Phase 2 |
| Editing | `test_editing.py` | Import/add/append, move/trim/split/remove, overlap & range validation, exact undo/redo restoration, asset-removal guard, missing media, persistence roundtrip, real ffprobe/ffmpeg probing |
| Rendering | `test_rendering.py` | Segment+gap export with probe-verified duration, empty/missing-media/non-MP4 errors, cancellation, and full editing+render API flow (incl. HTTP Range streaming) using generated videos |
| Media helpers | `tests/media_helpers.py` | Generates short synthetic videos with ffmpeg lavfi (color + sine audio); never personal media. Render/probe tests skip cleanly when no ffmpeg binary is available |
| Intelligence | `test_intelligence.py` | Moving-car detection/tracking (displacement, direction, mask coverage at the car's expected position), RLE roundtrip, scene-cut shots, speech segments, honest transcript-unavailable, fingerprint cache + invalidation, cancellation, full analysis API flow (timeline untouched) |
| Effects | `test_effects.py` | Keyframe linear/hold evaluation, registry validation (incl. per-parameter keyframe ranges), effect CRUD/preset/reorder/disable, exact persistence + undo/redo, v2→v3 migration, pixel-verified renders (brightness Δ, glow spread outside a bright square, bloom, two-track compositing, opacity blending), effects API flow |
| Training | `test_training.py` | Split hygiene (held-out/GGUF refused, held-out never exported), SFT trace generation contains real planner tool calls, VRAM estimator behavior, preflight problem reporting without deps/GPU, CLI dry-run (writes SFT files, executes nothing), unconfirmed training refusal, mocked-stack run (quantization/LoRA/resume/adapter save/manifest). **No real GPU/model training is tested.** |
| Improvement | `test_improvement.py` | Deterministic/disjoint splits + provenance, training dataset validation + dry-run refusal, opt-in feedback (refuses while disabled; CRUD/export when enabled), benchmark isolation (sentinel user project byte-identical) + exact builtin baseline, promotion gates (reviewer + spot-check mandatory, regression blocks), rollback, candidate config smuggling rejection, API flow |
| Agent | `test_agent.py` | Tool-schema rejection, read-only auto-answer, draft→approve→execute→undo-plan, reject, ambiguity/clarification (zero steps), invalid model output fallback, execution-time re-validation with nonexistent IDs, cloud double opt-in routing, full chat→render-job API flow |

API tests use `httpx.ASGITransport`, so they exercise FastAPI routing/serialization without needing a fixed TCP port.

## Additional local checks

Compile Python modules:

```bash
.venv/bin/python -m compileall -q neuralcut
```

Windows equivalent:

```powershell
.\.venv\Scripts\python.exe -m compileall -q neuralcut
```

Validate JSON examples/configs when edited:

```bash
python -m json.tool config.example.json >/dev/null
python -m json.tool src-tauri/tauri.conf.json >/dev/null
```

## Live server smoke test

Start the backend without a browser:

Linux/macOS:

```bash
./scripts/run.sh --no-browser --port 8765
```

Windows:

```powershell
.\scripts\run.ps1 --no-browser --port 8765
```

In another terminal:

```bash
curl http://127.0.0.1:8765/api/v1/health
curl http://127.0.0.1:8765/api/v1/diagnostics
curl http://127.0.0.1:8765/
```

On Windows PowerShell, `curl` may alias `Invoke-WebRequest`; either works for a basic check, or open the URLs in a browser.

Expected health shape:

```json
{"status":"ok","service":"neuralcut","version":"0.1.0"}
```

## Manual UI checklist

1. Open `http://127.0.0.1:8765/`.
2. Dashboard shows “backend reachable,” health JSON, and diagnostics JSON.
3. Projects: create a project in a temporary folder.
4. Confirm the app navigates to Current Project and a `.neuralcut` file exists.
5. Save the project; no error message appears.
6. Return to Projects and confirm it appears under Recent.
7. Background Jobs: submit a demo job with a visible delay; confirm progress updates.
8. Submit a longer demo job and cancel it; confirm status becomes `cancelled`.
9. Settings shows effective config with `models.enabled=false`.
10. Logs shows recent JSON log lines.
11. Restart the backend; open the project by path and confirm it loads.

## Windows verification still required

The Phase 1 development environment was Linux without Rust. Before calling the Windows foundation fully verified, run on a Windows laptop:

1. `.\scripts\setup.ps1`
2. `.\scripts\test.ps1`
3. `.\scripts\run.ps1`
4. Complete the manual UI checklist above.
5. Confirm data/config/logs appear under `%APPDATA%\NeuralCut`.
6. Confirm `NeuralCut.bat` starts the app after setup.
7. Optional Tauri check after installing Rust, Microsoft C++ Build Tools, and WebView2:
   - `npm install`
   - set `NEURALCUT_PYTHON` to `.venv\Scripts\python.exe`
   - `npm run tauri:dev`
   - confirm the window loads and closing it stops the Python backend.

Record Windows version, Python version, commands, and failures in the PR/issue rather than silently adjusting docs.

## Recorded hardening results (2026-10-24, Linux dev environment)

- Full suite: **82 passed** (75 prior + 7 hardening regressions in `test_hardening.py`). Ruff, `node --check`, and `scripts/check_packaging.py` clean.
- Covered regressions: live-logging preservation across benchmark runs, held-out sealing (routine runs + evaluate endpoint cannot reach held-out; promotion blocked until audited gate evaluation), experiment state machine (no demotion/duplicate promotion/invalid rollback), registry audit-failure visibility without operation failure, feedback rating validation, job payload redaction, queued-job cancellation (no spurious timeout failure).
- The Windows installer is built by the `windows-installer` CI workflow; check its latest run for the artifact. Physical-machine install/launch remains unverified.

## Recorded Phase 6–7 results (2026-10-24, Linux dev environment)

- Full suite: **75 passed** (64 prior + 4 agent-hardening regressions + 7 improvement). Ruff and `node --check` clean; CI now runs every test file plus Ruff.
- Benchmark (built-in planner, synthetic dataset 1.0.0): **14/14 cases** (train 9/9, val 3/3, held_out 2/2) after correcting one case expectation (the fade-in preset is keyframed opacity on the `transform` effect). Benchmark isolation verified by a sentinel-project byte-identity assertion.
- Phase 7 verification is configuration/documentation-level only: Tauri JSON validated, icons generated, versions unified. **Tauri/Rust compilation, the PyInstaller sidecar, the NSIS installer, and all interactive Windows flows were NOT run** — no Rust toolchain or Windows in this environment (see docs/PACKAGING.md).

## Recorded Phase 5 results (2026-10-24, Linux dev environment)

- `pytest`: **64 passed** (56 prior + 8 agent tests). Ruff/`node --check` clean.
- Headless intent fixtures cover each supported built-in intent family plus failure modes: unknown tools and shell-like calls are rejected by the schema layer; ambiguous references yield clarification plans with no steps; a model plan referencing a nonexistent clip fails at execution without mutating the timeline; cloud routing stays on the built-in planner until both `allow_cloud` and an env key exist.
- Not verified: a real local LLM endpoint (Ollama/llama.cpp) — the transport is covered by fakes; model plan quality is therefore unmeasured. Physical Windows verification remains pending.

## Recorded Phase 3–4 results (2026-10-24, Linux dev environment)

- `pytest`: **56 passed** (all Phase 1–2 tests plus intelligence/effects suites). Ruff and `node --check` clean.
- Moving-car fixture: the synthetic car (red box crossing a static scene) yields one track with displacement ≈ 0.70 of frame width, ≥5 frames, correct left→right direction, and a mask covering the car's expected centre pixel.
- Compositing/effects fixtures verify rendered pixels, not just durations: brightness raises frame mean, glow brightens pixels *outside* a bright square, a scaled red top clip covers the centre while corners stay blue, and 0.5 opacity blends measurably.
- Live smoke test: analysis job on the car video completed (1 track, displacement 0.70); a two-track project with a `fade-in` preset and keyframed glow saved and rendered to a probe-verified 3.04s composited MP4.
- **GitHub Actions (PR #3): all four jobs passed** (Ubuntu/Windows × Python 3.11/3.12). Ubuntu CI caught a real cross-version bug: the glow render's video stream ran to 2048s on the runner's ffmpeg 8.x (audio stayed 2.02s); composite segments are now hard-bounded (`trim`/`setpts`, `atrim`/`asetpts`, output `-t`) and the suite passes on both ffmpeg generations.
- Not verified: ASR transcription (optional engine not installed), semantic detection (not implemented by design), physical Windows laptop performance/interactive flow.

## Recorded Phase 2 results (2026-10-24, Linux dev environment)

- `pytest`: **42 passed** (Phase 1 suite plus editing/rendering/migration tests).
- `ruff check neuralcut`: clean. `node --check` on the frontend: clean.
- Live smoke test against the real server: create project → import generated 3s video (probed 3.0s, 320×240) → add clip → split → undo → save → submit render job → completed with expected 2.0s / probed 2.02s output; `ffmpeg -i` confirms H.264 + AAC streams. Range request returned `206` with a correct `Content-Range`.
- The sandbox has no system ffmpeg; tests used the optional `imageio-ffmpeg` binary (ffmpeg 7.0.2) installed only into the local `.venv`. It is **not** a project dependency — end users install ffmpeg normally. On machines without any ffmpeg, render/probe tests skip instead of failing.
- **GitHub Actions (PR #2): all four jobs passed** (Ubuntu/Windows × Python 3.11/3.12), including the rendering tests (apt ffmpeg+ffprobe on Ubuntu; imageio-ffmpeg binary — the no-ffprobe fallback path — on Windows). This run caught a real bug: ffmpeg stderr piped but not drained deadlocked the render subprocess on Windows; fixed by redirecting stderr to a temp file. Windows *runner* success still does not verify the PowerShell scripts or interactive browser flow on a physical laptop.

## Manual Phase 2 UI checklist (in addition to the Phase 1 checklist)

1. Create/open a project, go to **Timeline**.
2. Import a short video by full local path; confirm duration/resolution/codec appear.
3. Add it to the timeline; drag the clip and confirm its start time changes; select it and trim source in/out numerically.
4. Split the clip at its midpoint; confirm two clips. Undo → one clip; redo → two clips.
5. Play **Source preview** and seek; play **Edited timeline preview** and confirm it follows the clip order (labelled as approximation).
6. Save the project, restart the backend, reopen, and confirm the timeline is unchanged.
7. Export to an `.mp4` path; watch progress in the Timeline view or Background Jobs; open the exported file in a player and confirm duration/order.
8. Move the source file away, reload the timeline, and confirm the asset is marked missing and export fails with a clear message.

## CI

`.github/workflows/ci.yml` runs pytest and the frontend syntax check on:

- Ubuntu latest.
- Windows latest.
- Python 3.11 and 3.12.

CI runs the full suite including editing tests: Ubuntu runners get ffmpeg+ffprobe via apt; Windows runners get a static ffmpeg binary via the `imageio-ffmpeg` pip package, which the media adapter resolves through its fallback (exercising the no-ffprobe path). Rendering/probing tests skip if no binary is available. CI does not yet compile Tauri/Rust or test AI features (not implemented). Windows PowerShell script execution and the interactive Phase 2 browser flow still require a physical Windows laptop run — record results in the PR.

**Recorded Phase 1 CI result (2026-10-24):** the initial pull-request CI run passed all four jobs (Ubuntu/Windows × Python 3.11/3.12). This verifies the Python test suite and frontend syntax check on Windows runners; it does not by itself verify the PowerShell setup/run scripts, interactive browser flow, or Tauri build on a physical Windows laptop.

## Writing new tests

- Use `tmp_path` for all filesystem state.
- Do not depend on network access, GPU, FFmpeg, or model files unless the test is explicitly marked and skipped when unavailable.
- For background jobs, poll with a deadline instead of fixed long sleeps.
- For API behavior, assert both status code and stable error `code` where applicable.
- For project schema changes, add committed old-version fixtures and migration tests.
- For future media/AI work, separate deterministic unit tests from hardware/model integration tests and document required fixtures/licenses.
