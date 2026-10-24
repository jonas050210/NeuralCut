# AI Infrastructure Plan

This document describes planned AI integration. **NeuralCut (through Phase 2) implements no AI models, downloads, inference, GPU initialization, or cloud calls.** It only defines configuration fields, adapter contracts, diagnostics, and background-job boundaries.

## Current state (Phases 1–2)

| Piece | Current behavior |
|---|---|
| `models.enabled` | Defaults to `false` |
| `models.orchestrator_path` | Optional path placeholder; never loaded |
| `models.max_vram_gb` | Optional future budget; not enforced yet |
| `ModelManagerAdapter` | Reports unavailable; `load_model()`/`infer()` raise 503 |
| `GpuManagerAdapter` | Checks whether `nvidia-smi` exists; loads no CUDA/NVML bindings |
| `MediaProcessorAdapter` | Reports unavailable; only resolves optional ffmpeg/ffprobe paths |
| Background jobs | Working substrate for future analysis/inference/render jobs |

Setting `models.enabled=true` does not enable a hidden AI feature; diagnostics will still report the model adapter as unavailable.

## Design principles for future AI

1. **Optional and local by default** — the editor must remain useful without models or an NVIDIA GPU.
2. **Lazy loading** — no heavy model loads at application startup.
3. **Explicit downloads** — model size, license, disk location, and hardware requirements are shown before any download.
4. **One heavy family at a time initially** — serialize or swap LLM/ASR/VLM workloads when VRAM is constrained.
5. **Structured context** — AI receives project summaries and retrieved derived artifacts, not raw video by default.
6. **Validated actions** — an LLM may propose plans/tool calls; deterministic code validates and executes them.
7. **Measured claims** — latency, memory, WER, tool accuracy, and edit quality must be measured on representative Windows laptops.

## Planned component map

```text
Media files
   │
   ▼
Analysis jobs (Phase 3)
   ├─ probe/metadata
   ├─ shots/scenes
   ├─ transcript + word timings
   ├─ embeddings/captions
   ├─ objects/tracks/masks
   └─ audio features
   │
   ▼
Derived artifact store ─────► retrieval/context builder
   │                                  │
Project/timeline state ───────────────┤
                                      ▼
                              Planner/orchestrator (Phase 5)
                                      │ structured plan/tool calls
                                      ▼
                              Validator + Tool Executor
                                      │
                                      ▼
                              Deterministic editing core
                                      │
                                      ▼
                              Critic/evaluation checks
```

## Candidate model families from research

These are research directions, not current dependencies. Re-validate versions, licenses, and benchmarks at implementation time.

**Phase 2 status note:** the deterministic tool surface this plan assumes now exists — `TimelineService` operations (import/add/move/trim/split/remove), snapshot undo, and the `render` job are validated, typed, and test-covered. A future Phase 5 orchestrator should call exactly these operations; no AI/model code was added in Phase 2.

### Orchestrator LLM

- Candidate class: Qwen-family 4–9B instruct GGUF models.
- Runtime candidate: llama.cpp / llama-server with grammar-constrained decoding for tool-call syntax.
- Routing: deterministic rules may choose a fast small model for simple calls and a larger local model for complex planning.
- Safety: grammar validity is not semantic validity. Tool names, IDs, ranges, preconditions, and permissions must be checked in code.

### Speech

- Candidate: faster-whisper and/or WhisperX-style alignment for word timestamps and subtitles.
- Considerations: language coverage, diarization model gating/license, CPU fallback, model size, and German/English fixture accuracy.

### Vision/video understanding

- Shot detection: PySceneDetect and/or TransNetV2-class models.
- Retrieval: CLIP-style per-shot embeddings.
- Captions: small VLM on selected keyframes/shots.
- Tracking/masks: Phase 3 must prototype accuracy/performance before committing to a stack.

### Audio understanding

- VAD, loudness, silence maps, music/speech segments, and event spikes.
- Start with deterministic signal features where they are sufficient.

## Resource management plan

Future `GpuManagerAdapter` and `ModelManagerAdapter` should provide:

- Device inventory that degrades gracefully when no GPU/driver is present.
- A VRAM/RAM budget policy based on measured free memory, not vendor marketing numbers.
- Job classes such as `cpu`, `gpu-light`, and `gpu-heavy`.
- Serialization for heavy GPU jobs on constrained systems.
- Load/unload events in structured logs.
- Cancellation that can stop queued work and, where necessary, terminate an isolated worker process.
- Clear UI status: model absent, downloading, loading, ready, busy, failed, or CPU fallback.

Subprocess isolation should be considered for model/media workers before Phase 5 so a native crash or hung inference cannot take down the editor backend.

## Context and memory plan

Future agent context should be assembled from:

- Compact current project/timeline state.
- Recent user/agent actions and audit events.
- Retrieved transcript spans, shot captions, and analysis metadata.
- Tool schemas and capability limits.

It should not include raw video frames or entire transcripts by default. Derived artifacts need versioning and invalidation when source media or analysis settings change.

## Tool-call safety plan

Phase 5 should implement:

1. Flat, versioned JSON schemas for each editing tool.
2. Grammar-constrained generation where supported.
3. Semantic validation: existing IDs, media ranges, track constraints, permissions, and current project revision.
4. Plan preview/approval policy.
5. Transactional application with undo checkpoints.
6. Deterministic post-checks and a user-visible diff/audit record.
7. Clarification/refusal behavior for ambiguous or unsupported requests.

## Hardware tiers to test later

- **No discrete GPU / integrated graphics:** editing core, CPU analysis fallbacks, no LLM or small quantized CPU model only if latency is acceptable.
- **NVIDIA 8 GB VRAM:** one 4–9B quantized orchestrator or one major perception job at a time; measure swapping.
- **NVIDIA 12–16 GB+ VRAM:** more concurrency/larger tiers may be justified by measurements.

No tier should be promised until fixture benchmarks exist.

## Privacy and network policy

- No telemetry or cloud inference by default.
- Model downloads are explicit network actions.
- Any future cloud escalation requires product approval, per-action user consent, data minimization, and documentation.
- Logs must not include raw transcripts/prompts by default if they may contain private media content; future logging needs redaction controls.
