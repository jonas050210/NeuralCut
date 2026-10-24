# Changelog

All significant changes to NeuralCut are recorded here.

## [Unreleased]

- No unreleased changes yet.

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

Phase 1 was implemented and automated-tested in a Linux environment. Windows laptop execution and Tauri compilation require follow-up verification as documented in `docs/TESTING.md` and `docs/KNOWN_ISSUES.md`.
