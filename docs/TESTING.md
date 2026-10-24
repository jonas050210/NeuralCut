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
| Adapters | `test_integration_adapters.py` | Phase 1 adapters report unavailable and raise `UnavailableError` for future operations |

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

## CI

`.github/workflows/ci.yml` runs pytest and the frontend syntax check on:

- Ubuntu latest.
- Windows latest.
- Python 3.11 and 3.12.

CI does not yet compile Tauri/Rust or test media/AI features because those are not implemented Phase 1 systems.

## Writing new tests

- Use `tmp_path` for all filesystem state.
- Do not depend on network access, GPU, FFmpeg, or model files unless the test is explicitly marked and skipped when unavailable.
- For background jobs, poll with a deadline instead of fixed long sleeps.
- For API behavior, assert both status code and stable error `code` where applicable.
- For project schema changes, add committed old-version fixtures and migration tests.
- For future media/AI work, separate deterministic unit tests from hardware/model integration tests and document required fixtures/licenses.
