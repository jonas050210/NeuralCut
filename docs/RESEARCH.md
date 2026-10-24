# Research Summary and Technical Implications

This file distills the preserved research deliverable:

- [`BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md`](../BkrR_L97Sx7hVBdMMez7lfX9Rvu4JiTz4Q8Jov79iQY.md)

**Implementation status:** Phases 1–4 follow this document's central recommendation — a deterministic editing core with structured, validated project state. Phase 3 implements analysis with a deliberately non-ML motion detector (learned perception remains a future opt-in replacement with the same artifact representation), and Phase 4 adds the keyframed effects/compositing layer. The LLM orchestrator, learned perception specialists, and training loop described below remain unimplemented research directions for Phases 5–6.

That original file remains unchanged and is the detailed source with citations. Its evidence labels should be preserved when using its claims:

- **[Verified]** — primary source or reproduced benchmark.
- **[Reported]** — vendor/single-source claim.
- **[Estimate]** — extrapolation needing target-hardware validation.
- **[Hypothesis]** — reasoned but unproven design position.

## Executive conclusion

Build a **deterministic editing core with a small local LLM orchestrator**, not a monolithic “neural editor.” The LLM should reason over structured project state and derived artifacts—transcripts, shot lists, captions, embeddings—and select validated tools. It should not directly manipulate pixels or project files.

Phase 1 implements the deterministic boundaries that make this possible later: validated project JSON, typed errors, background jobs, centralized config, logging, and adapters.

## Model-selection findings

### Orchestrator LLM

Research favors Qwen-family 4–9B instruct models for local tool calling, quantized as GGUF and run through llama.cpp-class runtimes. Key points:

- A 9B-class Q4 model is the likely primary tier on an 8 GB NVIDIA GPU; a 4B-class model can serve as a faster/simple-request tier.
- Grammar-constrained decoding (GBNF in llama.cpp) can guarantee JSON/tool-call *syntax*, but semantic validation in code remains mandatory.
- Model routing should start as deterministic rules, not another neural model.
- Larger models are an asynchronous/CPU-offload or explicit escalation case, not the default.

**Foundation implication:** models are optional and disabled by default. `ModelManagerAdapter` is only a contract; no GGUF path is loaded in Phase 1. NeuralCut must also work on laptops without NVIDIA hardware, so CPU-only/no-model operation is a first-class mode.

### Speech and language

Whisper-family pipelines are the mature local option. Word-level alignment (WhisperX-style) is valuable for subtitles and dialogue-aware edits. Parakeet-class models may offer speed/WER advantages for supported languages but bring a different license/language footprint.

**Foundation implication:** transcription belongs in Phase 3 as a cancellable analysis job producing cached artifacts, not as synchronous UI work.

### Video understanding

Recommended future building blocks include:

- PySceneDetect and/or TransNetV2 for shot boundaries.
- CLIP-style embeddings per shot for retrieval.
- A small VLM for selected shot captions, not blanket frame-by-frame captioning.
- VAD/loudness/audio-event features for silence and highlight signals.

**Foundation implication:** the job manager and project/derived-data boundaries must support long-running, cancellable analysis and cache invalidation. Phase 1 provides the job substrate only.

## AI architecture findings

Recommended split:

| Layer | Neural or deterministic? | Rationale |
|---|---|---|
| Timeline/project state | Deterministic | Exact, versionable, auditable |
| Media operations/render | Deterministic | Reliable and debuggable (FFmpeg/MLT-class tools) |
| Import analysis | Pretrained neural models | Batch perception; cache results |
| Tool executor | Deterministic | Schema/semantic validation, transactions, undo |
| Planner | LLM | Language understanding and decomposition |
| Critic/evaluator | Hybrid | Deterministic gates first; model judge advisory only |
| Router | Deterministic rules initially | Predictable latency/cost |
| Memory | Structured DB/retrieval | Avoid stuffing raw media/history into prompts |

The validated interaction pattern is **plan → approve → execute → verify**, following systems such as LAVE. Users should retain control, especially for destructive or ambiguous edits.

## Fine-tuning findings

The research target was an RTX 4060 Ti with 8 GB VRAM. It concludes:

- Full fine-tuning and LoRA on bf16 bases are not realistic for 7–9B models at 8 GB.
- QLoRA is feasible for orchestrator SFT on verified tool-call traces.
- DPO/KTO/ORPO-style preference optimization can use accept/reject feedback; KTO matches unpaired binary UI feedback.
- PPO/GRPO-style on-policy RL is not a realistic default at 8 GB.
- ASR, VLM, and embedding models should not be fine-tuned initially.

These are future Phase 5/6 considerations. They do not justify adding training dependencies or GPU initialization to Phase 1.

## Evaluation and self-improvement findings

Edit quality has no single metric. The recommended gate is a battery of deterministic checks:

- Timeline validity and plan-to-diff correspondence.
- A/V sync and dialogue preservation.
- Subtitle timing/readability.
- Loudness/clipping.
- Render quality where full-reference metrics are appropriate.
- Pacing/content-specific derived checks.

LLM/VLM judges can advise on taste but should not be the promotion gate. Human preference and “how much did the user change afterward?” are important signals.

Self-improvement should begin as an evaluation/data pipeline:

```text
fixtures → sandbox runs → deterministic graders → failure mining
        → human review → versioned datasets → isolated candidate
        → held-out/regression gates → human spot-check → promote or rollback
```

Safeguards include splitting by source video and task template, sealed held-out sets, canary evaluations, multi-signal gates, pinned judge versions, and adapter rollback.

Phase 1 only declares `EvaluationAdapter` and `SelfImprovementAdapter`; the full plan is in [`SELF_IMPROVEMENT.md`](SELF_IMPROVEMENT.md).

## Hardware and scheduling implications

The research hardware is a desktop RTX 4060 Ti 8 GB / 32 GB RAM / i7-12700F, while the product must also support Windows laptops with no NVIDIA GPU. Therefore:

- GPU use is an acceleration path, never a startup requirement.
- Heavy model families should not remain resident simultaneously by default.
- Analysis and agent inference may need serialization on 8 GB VRAM systems.
- Small/CPU-friendly components can remain available when large models are absent.
- Every VRAM/latency claim needs measurement on actual target laptops before becoming a requirement.

Phase 1 `GpuManagerAdapter` only checks for `nvidia-smi` on `PATH`; it does not load CUDA/NVML bindings.

## Licensing watchlist for later phases

Before adding future dependencies, re-check primary license terms for:

- FFmpeg builds (LGPL vs GPL-enabled encoders/filters).
- Speaker diarization models that may be gated.
- ASR models with attribution requirements.
- Quantized model redistributions and base-model licenses.
- Fixture/training video rights.
- Timeline/media frameworks such as MLT/OpenTimelineIO if adopted.

No media/model dependency is bundled in Phase 1.

## Decisions still requiring product input

The research leaves these open:

- Cloud policy: never, teacher/data-generation only, or explicit user-approved escalation.
- Priority content type: short-form, long-form, gaming, or general editing first.
- ASR language priorities beyond English/German.
- Commercial/public distribution plans, which affect licensing strictness.
- Whether the editing core should adopt OpenTimelineIO/MLT concepts directly or keep a custom canonical model with import/export adapters.

Phase 1 avoids locking the product into answers that require later-phase prototypes and measurements.

## Follow-up research (2026-10-24): agent harnesses and evaluation

**Question:** can Harness²-style recursive agent harnessing or comparable
agent-evaluation practice improve NeuralCut's Phase 5/6 design?

**Sources:** google-research/harness2 (GitHub, Apache-2.0; paper
arXiv:2610.14224); Self-Harness (arXiv:2606.09498); SWE-bench (ICLR 2024)
and SWE-Bench Pro (arXiv:2509.16941) for FAIL_TO_PASS/PASS_TO_PASS-style
gating and private held-out sets; LangChain's agent-evaluation readiness
checklist; eval-harness practice write-ups (trajectory/failure taxonomy,
strata floors, holdout discipline).

**What Harness² does:** keeps model weights frozen and recursively edits
the *harness* around the model (system prompt, guardrails, memory, tool
guidance, subagents, skills, scripts, plugins) via a contrastive
Propose–Probe–Compose loop, accumulating lessons across tasks. Reported
gains: up to +11.5 points (WorkBuddy-Bench), +4.5 (JobBench), +11.8pp
partial pass (LAB) after one step with GLM-5 / Gemini 3.5 Flash.

**Useful for NeuralCut (adopted):**

- *Harness-as-candidate:* evaluating prompts/tool-guidance/configuration
  as versioned candidates against a frozen baseline matches our Phase 6
  candidate-configuration model (D-026) — validated externally.
- *Failure taxonomy before fixes:* categorizing failures (wrong plan,
  clarification miss, execution failure, harness error) instead of a
  single score — adopted in `benchmark.py` reports.
- *Held-out discipline + per-stratum gates:* already implemented via
  sealed held-out cases and per-split tolerance gates; SWE-bench's
  PASS_TO_PASS analog is our regression tolerance per split.

**Unsuitable / rejected for NeuralCut:**

- *Automatic harness self-editing and adoption* conflicts with hard
  project constraints: no automatic promotion, no untrusted/generated
  code execution, human spot-check required. Harness²'s loop also assumes
  frontier hosted models (Vertex AI) and open-world professional tasks —
  a different risk and resource profile from a local, offline, single-user
  editor with a deliberately narrow, safety-validated tool surface.
- Adopting the Harness² framework itself (Python 3.12+/uv, cloud model
  calls, code-execution harnesses) would add a large dependency whose
  core capability we are explicitly not allowed to enable. Documented as
  a recommendation to revisit **only** if a future phase permits
  human-reviewed harness proposals: the safe subset is "propose config/
  prompt candidates offline → benchmark gates → human promotion", which
  Phase 6 already implements for model-route configurations.

**Also considered:** LLM-as-judge grading (rejected as a *gate* — drift
and gaming risk; deterministic graders remain the gate), and trajectory
grading of full agent transcripts (useful future extension of the
benchmark runner once a real local LLM endpoint is evaluated on the
home PC).
