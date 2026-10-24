# Project Overview

## Vision

NeuralCut aims to become a **local-first AI-assisted video editor for Windows** that combines a reliable deterministic editing core with optional local AI assistance. The product should work on ordinary Windows laptops, including machines without an NVIDIA GPU, and should not require cloud services for core editing.

The long-term experience is an editor that can:

- Organize and analyze local footage.
- Understand transcripts, shots, objects, and important moments.
- Help users assemble and refine edits through a timeline and, later, natural-language requests.
- Apply effects and animation through controlled, validated editing operations.
- Learn from explicit user feedback and evaluated experiments without silently changing behavior.

## Core product principles

1. **Local-first and private** — media, projects, analysis, and preferences stay on the user's machine by default.
2. **Deterministic editing core** — timeline state, media operations, rendering, undo/redo, and validation must be exact and auditable.
3. **AI as an assistant, not an uncontrolled editor** — future AI should propose or invoke validated tools against structured project state, with user control and rollback.
4. **Hardware-realistic** — core workflows must not require a discrete NVIDIA GPU. Heavy models are optional, lazy-loaded, and scheduled.
5. **No silent automation** — analysis may prepare information, but future editing actions must be explicit, reviewable, and reversible.
6. **Evidence over hype** — quality claims require tests, fixtures, metrics, and on-target hardware measurements.

## Target users (long term)

- Creators editing short-form or long-form video on Windows laptops.
- Users who want AI help without uploading footage to cloud services.
- Power users who need understandable project data, repeatable operations, and control over automated changes.

## Phase 2 scope (current)

Phase 2 adds the editing core on top of the foundation:

- Schema-v2 timeline model with a v1→v2 migration (see `DATA_MODELS.md`).
- Local media import/probing (ffprobe/ffmpeg), asset metadata in the project.
- Deterministic clip operations — add, move, trim, split, remove — with same-track overlap and source-range validation.
- Snapshot-based undo/redo for all editing operations.
- Source preview (range-streamed original file) and an in-browser edited-timeline preview, clearly distinguished.
- Deterministic FFmpeg export (timeline order, trims, gap segments, silence for audio-less clips) as a cancellable background job with output-duration verification.
- Automated tests using short generated videos.

Phase 2 explicitly excludes object tracking, advanced effects, AI chat commands, model training, and self-improvement.

## Phase 1 scope

Phase 1 builds the foundation required by all later phases:

- Application startup/shutdown structure.
- Local Python backend and web frontend.
- Validated HTTP communication and error handling.
- Centralized configuration.
- Versioned JSON project persistence.
- Background jobs with progress/cancellation.
- Structured logging and diagnostics.
- Extension points for media, models, GPU scheduling, evaluation, and self-improvement.
- Tests, scripts, CI definition, and project documentation.

## Explicit non-goals for Phase 1 (delivered in Phase 2 where noted)

Phase 1 did not implement (Phase 2 has since added the timeline items):

- Timeline UI or editing operations. *(Phase 2: implemented)*
- Media import, transcoding, preview, render, or export. *(Phase 2: implemented, MP4 export)*
- Transcription, shot detection, embeddings, object detection/tracking, or masks.
- Effects, keyframes, compositing, glow, or bloom.
- AI chat, planning, tool calling, or model inference.
- Fine-tuning, preference learning, or autonomous self-improvement.
- A Windows installer or self-contained Tauri production bundle.

## Long-term roadmap summary

1. **Foundation** — architecture, infrastructure, persistence, docs, tests. *(done)*
2. **Editing Core** — timeline, clip operations, undo/redo, rendering, export. *(current — implemented; Windows-laptop verification pending)*
3. **Video Intelligence** — analysis, object detection, tracking, masks.
4. **Effects and Animation** — keyframes, compositing, glow, bloom, effect chains.
5. **AI Editing Agent** — chat, model routing, validated tool calls, controlled execution.
6. **Self-Improvement** — evaluation, feedback, isolated experiments, optional fine-tuning, rollback.
7. **Packaging** — Windows installer, performance, usability, release testing.

Detailed acceptance criteria are in [`ROADMAP.md`](ROADMAP.md).

## Research position

The preserved research document (`BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md`) recommends a deterministic editing core with a small local LLM orchestrator and specialized pretrained perception models. Phase 1 adopts the architectural implications—structured state, validated boundaries, background analysis jobs, and optional/lazy AI—without implementing the AI features themselves.

See [`RESEARCH.md`](RESEARCH.md) for the distilled findings.
