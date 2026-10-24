# Phase 1 Research — Local AI Video Editor: Architecture & Model Training

**Date:** 2026-10-24 · **Scope:** Research only (no implementation) · **Target hardware:** RTX 4060 Ti 8 GB VRAM / 32 GB RAM / i7-12700F

**Evidence notation used throughout:**
- **[Verified]** — primary source (official docs, repo, paper) or independent benchmark reproduced by multiple sources
- **[Reported]** — vendor-claimed or single-source benchmark; directionally useful, not independently confirmed
- **[Estimate]** — extrapolation from related evidence; needs on-target validation
- **[Hypothesis]** — reasoned design position; unproven

---

## 1. Executive Summary

**Core recommendation: build a deterministic editing core with a small local LLM orchestrator, not a "neural video editor."** The single highest-leverage finding of this research is that every credible LLM-assisted editing system that exists today (LAVE, prompt-driven agentic editing systems, commercial auto-clippers) uses the same pattern: a **deterministic media pipeline + structured project state + an LLM that selects and parameterizes tool calls**. The LLM never touches pixels or frame data directly; it reasons over *derived artifacts* (transcripts with word timestamps, shot lists, embeddings, captions).

On the target hardware this is feasible today with:

- **Primary orchestrator model:** a 4–9B-parameter instruct model with strong native tool-calling (the Qwen3.x family is the current open-weight leader in this class), running quantized (GGUF Q4_K_M, ~3–6 GB) under **llama.cpp with grammar-constrained decoding (GBNF)** so tool calls are structurally valid by construction.
- **Specialized pretrained models that should NOT be fine-tuned:** Whisper-family ASR (via faster-whisper / WhisperX), TransNetV2 for shot detection, CLIP embeddings for retrieval, a small VLM (Qwen3-VL 4B class) for frame description.
- **Only one model family is worth fine-tuning:** the orchestrator LLM, via **QLoRA adapters** (~5–8 GB VRAM, fits the 4060 Ti) trained on verified tool-call traces, with **DPO/KTO preference passes** driven by user accept/reject feedback. Full fine-tuning and on-policy RL (PPO/GRPO) are **not realistic on 8 GB VRAM** and are not needed for this agent's job.
- **The "long-running self-improvement" system should be an evaluation-and-data pipeline first, a training pipeline second.** Most early gains will come from better tools, prompts, retrieval, and project memory — not from weights.

**Biggest risks:** (1) 8 GB VRAM contention between the LLM, ASR, and VLM; (2) "edit quality" is subjective and no single metric captures it — evaluation must be a battery of deterministic checks + human preference; (3) scope creep — the editing engine and preview renderer are themselves large engineering efforts; (4) licensing traps in a few components (FFmpeg GPL filters, pyannote gated models, some datasets).

---

## 2. Local Model Selection

### 2.1 Orchestrator LLM (editing instructions, tool calling, planning)

**What matters for this application:** reliable single- and multi-step tool calling, schema-conformant JSON arguments, moderate context (project state summaries, not raw video), Apache/MIT-class licensing, and quantized quality on 8 GB VRAM.

Evidence base: the Berkeley Function Calling Leaderboard (BFCL) is the primary independent benchmark for tool use [1]; Docker published a reproducible local-model tool-selection evaluation via Ollama [2]; several 2026 independent round-ups measure local tool-calling on constrained hardware [Note: blog-tier sources, directionally consistent].

| Model (quantized GGUF) | Approx. file size / VRAM | Tool-calling evidence | License | Fit on 8 GB |
|---|---|---|---|---|
| **Qwen3.5-4B** (Q4) | ~3.4 GB | 97.5% pass rate in one independent 13-model local test [3, Reported] | Apache 2.0 | Excellent; leaves headroom for ASR/VLM |
| **Qwen3.5-9B** (Q4_K_M) | ~5.6 GB | Recommended 8–16 GB tier pick; vendor-reported BFCL-V4 66.1 [4, Reported] | Apache 2.0 | Good if run alone; tight alongside other GPU models |
| Qwen3-8B (Q4_K_M) | ~5 GB | Tool-selection F1 0.919 (Docker eval) [2, Verified test method]; BFCL overall ~42.6 older listing [5] | Apache 2.0 | Good |
| Qwen3-14B (Q4_K_M) | ~8.4 GB | Tool-selection F1 0.971 — best in Docker eval [2] | Apache 2.0 | Marginal: needs partial CPU offload; ~2–4× slower [Estimate] |
| Llama-3-Groq-8B-Tool-Use (Q4) | ~5 GB | 89.06% BFCL at launch (July 2024; strong on single calls, dated) [6] | Llama 3 Community | Good, but older base |
| Mistral-Nemo-12B (Q4) | ~7.5 GB | 92.5% in one local test [3, Reported] | Apache 2.0 | Marginal |

**Recommendation:**

- **Fast primary model: Qwen3.5-9B at Q4_K_M** (or Qwen3-8B as the battle-tested fallback with the most third-party runtime support). Qwen dominates open-weight tool-calling rankings in 2026 across multiple independent sources [1],[4],[7].
- **Add a lower tier: Qwen3.5-4B** as the "fast lane" for high-frequency, low-stakes calls (intent classification, simple parameter fills, yes/no confirmations). [Hypothesis] Routing simple calls to a 4B model roughly halves perceived latency.
- **When a larger model is justified:** complex multi-constraint planning ("make a 3-minute story arc from these 40 clips, keep all dialogue, pace it fast, no jump cuts"), ambiguous instructions needing clarification dialogs, and post-hoc diagnosis of why an edit went wrong. On 8 GB VRAM, a 14B-class model requires partial CPU offload (slower but usable asynchronously) — otherwise treat the cloud option as *explicit escalation only*, per the local-first requirement. [Estimate]

**Critical implementation note — structured outputs:** llama.cpp supports **GBNF grammar-constrained decoding**, which masks invalid tokens during sampling so the model *cannot* emit malformed JSON or wrong argument structure [8],[9],[Verified]. Third-party measurements put schema-validity at ≥99.8% with ~10–50 ms/token overhead [10],[Reported]. This moves "argument validity" from a *model-quality* problem to a *deterministic guarantee* — and means fine-tuning only needs to improve *semantic* tool/argument choice, not syntax. Ollama exposes schema constraints on top of llama.cpp; vLLM and SGLang have equivalents (XGrammar/llguidance with even lower overhead) [10]. **Semantic validation is still required in code** (a grammar guarantees valid JSON, not a correct tool name) [11, Verified].

**Runtimes compared:** llama.cpp/Ollama (easiest, GGUF, CPU offload, GBNF), vLLM (best throughput, heavier, needs more VRAM headroom), LM Studio (GUI, good for experimentation), ONNX Runtime GenAI ( niche ). For an app that must manage VRAM shared by several models, **llama.cpp (llama-server) with explicit load/unload control is the safest default** [Hypothesis, but consistent with community consensus].

### 2.2 Speech recognition (transcription, subtitles, dialogue-aware editing)

| Option | Notes | VRAM | License |
|---|---|---|---|
| **faster-whisper (large-v3 / large-v3-turbo)** | CTranslate2 backend; large-v3 int8 ≈2.9–4.5 GB; turbo ~6 GB fp16; measured 23–56× real-time on consumer GPUs [12],[13],[Verified] | ~3–6 GB | MIT |
| whisper.cpp | Best CPU/Metal path; identical accuracy (same weights) [14] | ~3–4 GB RAM | MIT |
| NVIDIA Parakeet-TDT-0.6B-v3 | Lowest WER among open models per Open ASR LB (6.32% vs Whisper large-v3 7.44%) and ~3000× RTF throughput [Reported]; 25 European languages (incl. German ✔); native word timestamps; low hallucination on silence [15],[16] | ~1.5 GB | CC-BY-4.0 (attribution) |
| Distil-Whisper large-v3 | ~5–6× faster, ~1% WER degradation, English-focused [12] | ~5 GB | MIT |
| **WhisperX** | Pipeline: faster-whisper + wav2vec2 forced alignment + pyannote diarization. Gives **word-level timestamps (~50 ms accuracy)** and speaker labels; exports SRT/VTT/JSON [17],[18],[Verified] | ~4–6 GB | BSD-2-Clause (pyannote models are HF-gated) |

**Recommendation:** WhisperX-style pipeline as the default analysis step (word-level timestamps are what make subtitle alignment, verbatim cutting a la Descript, and dialogue-preservation checks possible — segment-level Whisper timestamps drift by hundreds of ms to seconds [18]). Consider Parakeet-TDT for a speed-focused profile and as a second opinion; note its CC-BY attribution requirement and 25-language scope. Diarization via pyannote (requires accepting HF model terms — flag as a licensing/UX step). Run ASR **sequentially with, not concurrently with**, the LLM on GPU (analysis is a batch import step; the agent is idle then). [Estimate]

### 2.3 Scene/shot analysis and video understanding

| Tool / model | Role | Evidence |
|---|---|---|
| **PySceneDetect** | Fast shot/cut boundary detection (histogram/content/adaptive detectors); CLI + Python API; actively maintained (v0.7.2, Oct 2026) | [19],[Verified], BSD-3 |
| **TransNetV2** | Neural shot-boundary detection; catches dissolves/gradual transitions PySceneDetect misses; F1 0.81–0.97 reported across benchmarks; TF + PyTorch ports with simple inference API | [20],[21],[22],[Verified] |
| **OpenCLIP** (e.g. ViT-B/32) | Per-shot frame embeddings → semantic search of footage ("find the clip where…") | Common pattern [23],[24] |
| **Qwen3-VL-4B** (Q4) | Sampled-frame captioning/shot descriptions; 256K context, timestamp-grounded video features in the family; ~3.3 GB Q4 | [25],[26],[Verified repo + Reported sizing] |
| SmolVLM2 2.2B | Ultra-light captioning fallback (~2 GB); weaker captions | [27] |
| X-CLIP-class video classifiers | Gaming event detection ("kill", "goal") fine-tuned per genre | [28] (research precedent) |

**Recommendation:** PySceneDetect (fast pass) + TransNetV2 (accuracy pass on import) → shot list; OpenCLIP embeddings per shot → vector index; Qwen3-VL-4B captions only for *selected/key* shots (it's the slowest component; caption every shot only for short-form). [Estimate] Do **not** fine-tune any of these initially; all are mature pretrained tools.

### 2.4 Other specialized models

- **Silero VAD** — voice-activity detection (silence/filler-word cutting). Tiny, CPU-friendly. [Verified — widely used, incl. inside WhisperX]
- **Audio event / loudness analysis** — ffmpeg `loudnorm` (EBU R128), RMS/spike detection for gaming highlights (used by open-source auto-clippers [29],[30]).
- **Gaming highlight detection** — open-source precedents combine: audio spike detection + pixel/OCR signals (kill feeds) + optional YOLO object detection trained per-game + chat/retention signals [29],[30],[31],[32]. [Verified these approaches exist; quality varies]. Recommend a heuristic multimodal scorer first; a per-game YOLO classifier only later (needs labeled data).

---

## 3. AI Architecture

### 3.1 Which components are neural vs deterministic

| Component | Implementation | Why |
|---|---|---|
| Timeline model & project state | **Deterministic**: OpenTimelineIO-style structured documents (clips, tracks, transitions, effects) + relational/vector DB | Must be exact, versionable, auditable. OTIO (Apache-2.0, Pixar/ASWF) is the industry-standard interchange model; Kdenlive has native OTIO support since 25.04 [33],[34],[Verified] |
| Media operations (cut, trim, render, overlay, normalize) | **Deterministic**: FFmpeg (LGPL/GPL caveats), MLT framework (LGPL — powers Kdenlive/Shotcut), or MoviePy (MIT) for prototyping [35],[36] | Reliability, speed, and debuggability. FFmpeg concat ops can be ~20× faster than frame-by-frame Python [37, Reported] |
| Import analysis pipeline | **Neural but pretrained**: TransNetV2, WhisperX, CLIP, VLM (Section 2.3) — batch job; **must report "analysis complete" without auto-editing**, per product spec | One-time cost per asset; results cached in project DB |
| Tool Executor | **Deterministic**: schema validation (JSON Schema), preconditions (media exists, in-range timestamps), transactional undo stack | Never let the LLM execute anything unvalidated [11] |
| Planner | **Neural**: orchestrator LLM produces a JSON plan (ordered tool calls with rationales), shown to the user before execution — the LAVE plan-and-execute pattern [38],[39],[Verified precedent] | Planning is where language understanding is actually needed |
| Decision Layer (tool choice) | Same LLM + **grammar-constrained decoding**; deterministic validator rejects out-of-policy calls | Syntax-free errors via GBNF [8] |
| Critic / Evaluator | **Hybrid**: deterministic checks (timeline validity, A/V sync offset, loudness, subtitle overflow, dialogue coverage) + optional LLM-judge for taste-level judgments; deterministic checks are the gate, LLM judge is advisory | Deterministic gates are auditable and cheap; LLM judges drift and can reward-hack (Section 5) |
| Model Router | **Deterministic rules** (task type, context length, confidence history) dispatching to 4B/9B/cloud | A neural router adds latency and failure modes for a decision that is rule-shaped [Hypothesis; consistent with production guidance [40]] |
| Project memory | **Structured DB + retrieval**, not LLM context: SQLite (project state), sqlite-vec/Qdrant (shot embeddings), JSONL event log (episodic memory) | Standard 2026 agent memory taxonomy: working/episodic/semantic [41] |

### 3.2 How the AI "sees" the project without re-processing video

The key pattern (confirmed by LAVE and by 2025–26 agentic editing research [38],[42]): **analysis happens once at import; the agent operates on the derived index.**

1. **Import analysis** produces per-asset artifacts: shot boundaries (start/end frames), word-aligned transcript + speakers, per-shot CLIP embedding, optional VLM caption, audio stats (loudness curve, silence map, music segments). Stored in SQLite/parquet + FAISS/sqlite-vec.
2. The agent's context contains **summaries**, not media: e.g. per-shot one-line captions + timestamps, transcript snippets retrieved on demand (RAG over the transcript), and a compact project-state document (tracks, clip ranges, effects).
3. **Cost discipline:** context assembly should inject the minimum needed — stable instructions, typed state, bounded recent conversation, retrieved evidence [40],[Verified as best practice]. Retrieving 5 relevant shots' captions is ~1K tokens vs. re-captioning frames each turn.
4. On user request → Planner reads retrieved context → emits plan (JSON) → user approves (LAVE-style) or auto-approve for low-risk ops → Tool Executor validates & applies each op transactionally → Critic runs deterministic checks on the resulting timeline → report diff to user.

### 3.3 Hierarchical planning & decision learning

- **Plan-and-execute with user-in-the-loop approval** is the validated HCI pattern for editing agents (LAVE user study, n=8, high satisfaction; users disliked losing control when the agent over-acted) [38],[39],[Verified].
- Research on long-form agentic editing (2025) adds: persistent **hierarchical semantic indexes** (project → sequences → shots → words), scratchpad compression, and cross-granularity reasoning [42].
- Hierarchical planners (goal → scenes → shot ops) map naturally onto this index. [Hypothesis] Start single-level (flat JSON plan per user request); add a scene-goal layer only when multi-minute narrative assembly is requested.
- Decision learning (which tool wins when) starts as logged telemetry; becomes preference data (Section 4–5). A learned router/policy is a Phase-3+ concern.

---

## 4. Fine-Tuning on 8 GB VRAM

### 4.1 Method comparison

| Method | Data needed | VRAM for 7–9B (verified ranges) | Feasible on 4060 Ti 8 GB? | Role here |
|---|---|---|---|---|
| Full fine-tuning | Demonstrations | ~60–112 GB [43],[44] | ❌ No | — |
| LoRA (bf16) | Demonstrations | ~16–24 GB [44] | ❌ No | — |
| **QLoRA (4-bit NF4 + LoRA r=16–32)** | Demonstrations (SFT) | **~5–8.5 GB** (Unsloth mins: 5 GB @7B, 6.5 GB @9B; gradient ckpt, batch 1–2, ctx ≤2048) [45],[46],[Verified] | ✅ Yes (primary method) | Teach tool schemas, argument style, project-state reading, plan format |
| **DPO** (QLoRA base) | Preference pairs (chosen/rejected plans or calls) | QLoRA-SFT VRAM + ref model — feasible with adapter tricks; ~8–10 GB tight [Estimate from [47] scaling] | ✅ Yes, tight | User accept/reject feedback → refine choices |
| **KTO** | Binary labels (thumbs up/down) | Same as DPO-ish [47] | ✅ Yes | Best match for UI accept/reject signal (unpaired) |
| ORPO | Pairs, no ref model (single stage SFT+pref) | Lowest of the preference methods [47] | ✅ Yes | Combined SFT+preference if data is small |
| **GRPO / PPO / RLHF** | Online rollouts + reward fn (+critic for PPO) | Rollouts blow VRAM; multi-model memory; quadratic-ish scaling [48],[49],[Reported] | ❌ Not realistically (maybe 0.6–1.7B toy models) | Skip; revisit if hardware changes |

**Realistic config on the 4060 Ti (QLoRA, ~9B base):** NF4 4-bit base, r=16–32 α=2×r, target all linear projections, seq len 2048 (4096 possible with batch 1), micro-batch 1–2 × grad accum 8–16, AdamW-8bit, gradient checkpointing, RS-LoRA optional [45],[50],[Verified configs from Unsloth/Axolotl docs]. Unsloth is ~2× faster / ~40–70% less VRAM than vanilla PEFT [51],[Vendor-reported but widely corroborated]. Axolotl is the YAML-config alternative with DPO/ORPO/KTO/GRPO support [52].

**What to train (and what NOT to):**
- ✅ **Tool selection & argument generation** on the project's actual tool schemas (the top gap: small models pick the wrong tool or misuse arguments even when JSON is valid [2],[11]).
- ✅ **Plan-format discipline** (emit the exact plan schema; sensible step decomposition).
- ✅ **Project-state reading** (grounding calls in the provided state doc; no hallucinated clip IDs — this is a data-construction problem: train on states sampled from the real editor).
- ✅ **Clarification behavior** (ask when ambiguous — trainable from SFT examples).
- ❌ Do not fine-tune ASR/VLM/embedding models initially — they're strong pretrained, and their failure modes are data/distribution issues better handled by parameters/pipeline, not weights. [Hypothesis, but standard practice]
- ❌ Do not try to train "editing taste" into the LLM via SFT — taste lives in the Critic's metrics and in preference data; SFT on taste without a grounded signal invents supervision noise.

**Do not promise training times.** As orientation only [Estimate, not a guarantee]: community reports put QLoRA runs of 7–9B models on ~2–5k samples at roughly **hours** on this GPU class, and Unsloth markets multi-fold speedups vs. vanilla [45],[51]; actual time depends on dataset size, seq len, and epochs — measure on the first run (Unsloth prints ETA) before planning around it.

### 4.2 Where fine-tuning actually pays

The expected gain curve [Hypothesis, consistent with tool-calling literature]: (1) grammar constraints kill syntax errors — free; (2) prompting + few-shot gets a 9B Qwen to maybe 80–90% semantic call accuracy; (3) QLoRA SFT on ~1–5k domain traces closes most of the remaining gap for *covered* tool patterns; (4) DPO/KTO on real user accept/reject data polishes preference-level choices (cut aggressiveness, subtitle density); (5) RL is the last 2% and not affordable here — accept this.

---

## 5. Long-Running Training & Evaluation Pipeline

### 5.1 The loop design

```
                       ┌───────────────────────────────┐
                       │  Fixture library (videos with │
                       │  licenses you own/permission) │
                       └──────────────┬────────────────┘
                                      ▼
┌─────────────┐   ┌──────────────────────────┐   ┌────────────────────────┐
│ Task suite   │──▶│ Sandbox runner (headless) │──▶│ Deterministic graders  │
│ (JSON tasks: │   │ agent executes edit on    │   │ (timeline valid? sync? │
│ "make 30s    │   │ fixture copy; full event  │   │  dialogue kept? subs    │
│ highlight")  │   │ log captured)             │   │  aligned? pacing? ...) │
└─────────────┘   └─────────────┬────────────┘   └───────────┬────────────┘
                                │ failures                    │ pass/fail + traces
                                ▼                             ▼
                   ┌─────────────────────────┐   ┌──────────────────────────┐
                   │ Failure mining: cluster  │   │ Experiment log (MLflow/  │
                   │ by error type; surface   │   │ Aim/W&B-local): metrics, │
                   │ to human review queue    │   │ configs, traces, git SHA │
                   └───────────┬─────────────┘   └───────────┬──────────────┘
                               ▼                             │
                   ┌─────────────────────────┐               │
                   │ Human review: correct    │               │
                   │ the plan/calls; label    │ (also live in the app:
                   │ good/bad (doubles as UI  │  user accept/undo/approve
                   │ accept/reject data)      │  events → KTO/DPO labels)
                   └───────────┬─────────────┘               │
                               ▼                             ▼
                   ┌──────────────────────────────────────────────────┐
                   │ Data registry (versioned: DVC/Git-LFS): SFT set, │
                   │ preference set — split by SOURCE VIDEO and by    │
                   │ TASK TEMPLATE; held-out set frozen & sealed      │
                   └───────────┬──────────────────────────────────────┘
                               ▼
                   ┌─────────────────────────┐   ┌──────────────────────┐
                   │ Train candidate adapter  │──▶│ Promotion gate:       │
                   │ (QLoRA SFT → DPO/KTO)    │   │ 1) held-out task      │
                   │ + regression suite on    │   │    suite ≥ incumbent  │
                   │ previous checkpoints     │   │ 2) regression suite   │
                   └──────────────────────────┘   │    (all prior tasks)  │
                                                  │ 3) canary general-    │
                   ┌─────────────────────────┐    │    capability eval    │
                   │ Rollback: adapter        │◀──│ 4) human spot-check   │
                   │ registry + one-click     │   └──────────────────────┘
                   │ revert (adapters ~100 MB)│
                   └─────────────────────────┘
```

**Key properties:**
- **Sandbox:** the runner executes plans against *copies* of fixture projects via the same headless Tool Executor the app uses — no UI needed; FFmpeg renders to temp; graders inspect the output files and the resulting timeline JSON. This mirrors RL-environment best practice: frozen deterministic environments, fixed seeds, replayed external inputs [53],[Verified-as-best-practice].
- **Graders are deterministic by default** (Section 6); an LLM-judge is an advisory signal, never the gate [53],[54].
- **Human-in-the-loop is dual-use:** the app's accept/undo thumbs feed KTO/DPO directly; the review queue converts sandbox failures into corrected SFT examples. User preference learning = preference optimization over *plans/edits*, not just text.
- **Versioning & rollback:** adapters are small (~100 MB), so a checkpoint registry with per-version metrics and instant rollback is cheap; dataset versions tracked (DVC); experiment tracking local (MLflow/Aim/W&B offline) [55],[56].

### 5.2 Contamination, reward hacking, regression — concrete mitigations

| Threat | Mechanism here | Mitigation (evidence-based) |
|---|---|---|
| Train/test leakage | Agent or data pipeline touches held-out tasks/videos | Split by **source video AND task template**; enforce file-access deny-lists for held-out paths (RewardHackingAgents' `train_deny` regime blocked the leakage vector; combined with evaluator locking = `full_locked` blocked both) [57],[Verified] |
| Benchmark overfitting | Repeated tuning against the same held-out set | Keep a **second, sealed set** only evaluated at promotion gates; rotate fixture videos; use canary strings in internal eval files to detect their presence in training data [58],[59],[Verified techniques] |
| Metric gaming (reward hacking) | Model learns e.g. "always cut to the max allowed length" to pass duration checks, or planner emits plans that please the LLM-judge | Anthropic's 2025 study: reward hacking generalizes to broader misalignment; effective mitigations = prevent hacking in training data, reward-hack classifier penalties, diverse environment mixes [60],[Verified]. Concretely: multi-signal gates (no single scalar), randomized grader details (thresholds sampled per run), adversarial fixture tasks where the "easy way out" fails (BAITBENCH idea [61]), audit high-scoring runs ([62] recommends manual review of anomalous score jumps), KL-anchored preference training (beta not too small) [63] |
| Catastrophic forgetting | QLoRA degrades general chat/tool ability | Canary eval each candidate: small general benchmark subset (BFCL slice + a chat eval) + the *entire* regression suite must stay ≥ incumbent [Estimate; standard practice [53]] |
| LLM-judge drift | Judge model version changes move goalposts | Pin judge model + prompt hash in experiment log; prefer deterministic metrics for gates [53],[54] |

### 5.3 Weights vs memory vs system — keep improvements in the right layer

Decision rule [Hypothesis, but strongly supported by agent-engineering literature [40],[41]]:

| Symptom | Fix in... |
|---|---|
| Model doesn't know a tool exists / picks wrong one for covered patterns | **Weights** (SFT) or **prompt** first |
| Model hallucinates clip IDs / stale durations | **Memory/retrieval** (state doc construction), never weights |
| Repeatedly bad taste choices (cuts too aggressive) | **Critic metrics** first; then **preference training** (KTO/DPO) |
| Slow responses | **System** (router to 4B, smaller prompt, cache) |
| Novel user phrasing breaks parsing | **Prompt + grammar**; SFT only when pattern recurs |
| Game-specific highlight misses | **Perception pipeline** (per-game detectors, audio features), not the LLM |

Only escalate a fix to training when the system-level fix has demonstrably failed on logged failures. This keeps the training set small, honest, and targeted.

---

## 6. Evaluating Whether Edits Are Actually *Good*

No single metric measures edit quality. Build a **graded battery**:

### 6.1 Deterministic, machine-checkable (the promotion gate)

| Dimension | Check | Tooling |
|---|---|---|
| Timeline correctness | Output timeline validates; clips in range; no unintended gaps/overlaps; frame-accurate in/out points match plan | OTIO validation + custom invariants [33] |
| Task completion | Plan steps ↔ timeline diff correspondence (each requested op observable in output) | Deterministic diff grader |
| A/V sync | Global offset detection (audio/video cross-correlation); lip-sync spot checks | ffmpeg/librosa cross-corr; **PEAVS** (ECCV'24 perceptual AV-sync metric, human-correlated) [64],[Verified] |
| Dialogue preservation | Transcript of output ⊆ keeps requested dialogue; WER-diff vs source segment transcripts | faster-whisper re-transcribe + text diff [12] |
| Subtitle alignment | Per-word timestamps vs audio (WhisperX alignment on the *rendered* file); cue duration/reading-speed limits (CPS rules) | WhisperX [17] |
| Audio quality | EBU R128 loudness (e.g. −14 LUFS target for social), no clipping, fade presence | ffmpeg loudnorm/ebur128 |
| Render quality | VMAF/SSIM/PSNR vs source for re-encoded segments (full-reference: encode quality only — **not** edit quality) | libvmaf in ffmpeg [65],[66],[Verified] |
| Pacing | Shot-length histogram vs target profile (short-form median ~1.5–2.5 s, etc.) | Derived from timeline |
| Content-type specifics | Short-form: hook present in first 1–3 s, captions coverage. Gaming: highlight segments contain detected events (events ⊆ clips recall). Long-form: chapter/story structure respects shot clusters | Derived from analysis index |

### 6.2 Model-based and human (advisory/taste)

- **LLM/VLM-as-judge with rubrics** — the direction of 2026 research (AVE-Compass decomposes audio-video editing into instruction-following, fidelity-preservation, realism, editing-intent, judged by MLLM checklists + automated metrics) [67],[Verified it exists; immature]. Use as advisory signal with pinned prompts; calibrate against human labels [62].
- **Human preference**: in-app A/B ("Keep version A or B?"), accept/undo rates per tool, edit-distance from agent result to user's final version (the most honest signal: how much did the human change afterward). Aggregate into preference pairs for DPO/KTO.
- **VBench** exists for *generative* video — largely irrelevant here (we edit, not generate). VMAF measures *encode* quality, not edit decisions — do not misuse [66].

### 6.3 Reusable open-source assets

| Asset | Use | License |
|---|---|---|
| OpenTimelineIO | Timeline model/validation/interchange | Apache-2.0 [34] |
| FFmpeg + libvmaf | Render, metrics | LGPL/GPL* [65],[66] |
| PySceneDetect, TransNetV2 | Shot ground truth | BSD-3 / check repo terms [19],[20] |
| WhisperX / faster-whisper | Transcript/subtitle ground truth | BSD-2 / MIT [17],[12] |
| LAVE (paper + design) | Agent UX pattern (plan-approve-execute) | Research, ACM [38] |
| Auto-Editor (WyattBlue) | Silence/filler cutting heuristics reference | MIT-ish (check) [68] |
| Open-source gaming clippers (Auto-clipper, Detector-Highlights, eklipse-style signals) | Gaming highlight heuristics | MIT/various [29],[30],[31] |
| BFCL | Tool-calling canary eval | Public leaderboard [1] |
| MLflow / Aim / DVC | Experiment & data versioning | Apache-2.0 / Apache-2.0 [55],[56] |
| PEAVS | AV-sync metric | Research code [64] |
| AVE-Compass | AV-edit eval methodology reference | arXiv 2026 [67] |

---

## 7. Implementation Strategy & Phased Roadmap

### 7.1 Proposed architecture

```
┌──────────────────────────── Desktop App (Tauri 2 + Web UI, or Qt) ───────────────────────────┐
│  Timeline UI · Media gallery · Chat/agent panel · Analysis status · Review/A-B UI            │
└──────────────────────────────┬───────────────────────────────────────────────────────────────┘
                               │ IPC (local; relative URLs)
┌──────────────────────────────▼───────────────────────────────────────────────────────────────┐
│                        Python backend (single process, FastAPI)                              │
│  ┌─────────────┐  ┌──────────────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ Project svc  │  │ Agent svc             │  │ Analysis svc      │  │ Eval svc (sandbox +   │  │
│  │ OTIO-style   │  │ Planner LLM (llama-   │  │ import pipeline:  │  │ graders + experiment  │  │
│  │ timeline DB  │  │ server, GBNF), Tool   │  │ TransNetV2/PSD,   │  │ log)                  │  │
│  │ (SQLite/     │  │ Executor (validate+tx)│  │ WhisperX, CLIP,   │  └───────────────────────┘  │
│  │ sqlite-vec)  │  │ Critic (deterministic │  │ VLM captions      │                            │
│  │             │  │ gates + LLM advice),   │  │ → "analysis       │                            │
│  │             │  │ Router (rules)         │  │  complete" event  │                            │
│  └─────────────┘  └──────────────────────┘  └──────────────────┘                            │
│  Render/ops: FFmpeg (subprocess) · optional MLT/GStreamer for preview pipeline                │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
                GPU scheduler: one heavy model family resident at a time (8 GB budget)
```

- **UI stack**: Tauri 2 (Rust shell + web frontend) ≈3–15 MB bundles, 40–100 MB idle RAM vs Electron's ~120–300 MB — leaves RAM for models [69],[70],[Reported-consistent]. Qt/pyqt is the pro-video alternative (Kdenlive's world) with heavier licensing/dev cost. [Decision needed, see §8]
- **VRAM scheduling**: serialize heavy GPU jobs (import analysis batch ↔ agent inference); llama-swap-style model switching; small models (VAD, CLIP) can stay resident. [Estimate: workable; must measure]
- **Tool surface**: ~20–40 tools initially (import, analyze, transcript query, shot search, cut/trim/move/insert, audio normalize, subtitle ops, render/export). Keep count low — selection accuracy degrades with tool count [71, Reported].

### 7.2 Phases

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Foundations (weeks 1–4)** | UI shell, project model, import, FFmpeg ops, deterministic undo. **Analysis-on-import with explicit "analysis complete" notification; NO auto-edit** (product requirement) | Import → shot list + word-aligned transcript; render round-trip |
| **1 — Agent MVP (weeks 5–10)** | Qwen 8–9B class + GBNF tool calls; plan-approve-execute (LAVE-style); ~15 tools; chat | 80% of scripted single-intent tasks succeed headlessly [target, not evidence] |
| **2 — Observability + eval harness (weeks 8–14, parallel)** | Event logging, fixture library v1 (~30 tasks), deterministic graders, experiment tracking | Nightly sandbox run produces report; failures clusterable |
| **3 — Feedback & first fine-tune (months 4–6)** | Review queue; accept/undo telemetry → KTO/DPO pairs; SFT v1 (QLoRA) on corrections; promotion gate + rollback | Adapter v1 beats base on held-out suite; no regression; documented |
| **4 — Content-type depth (months 6–9)** | Short-form recipe pack (hook/captions/pacing profile); gaming highlight scorer (audio spikes + pixel/OCR + optional YOLO); long-form chaptering | Per-type eval fixtures pass; user studies |
| **5 — Advanced (months 9+)** | Larger/cloud escalation path (opt-in), per-game detectors, custom Critic tuning, community tool recipes | Discrete milestones per feature |

**Prioritization principle: speed & reliability > breadth.** Every feature ships with its grader.

### 7.3 Dependency license map (selected)

| Component | License | Note |
|---|---|---|
| Qwen3.x models, Qwen3-VL | Apache-2.0 | Clean [72] |
| Whisper / faster-whisper / whisper.cpp | MIT | Clean [12],[14] |
| WhisperX | BSD-2-Clause; **pyannote models HF-gated** (user must accept terms; community-1 pipeline) | UX frictiοn [17],[18] |
| Parakeet-TDT v3 | **CC-BY-4.0** — attribution required | [15] |
| PySceneDetect | BSD-3-Clause | [19] |
| OpenTimelineIO | Apache-2.0 | [34] |
| FFmpeg | LGPL 2.1+; **GPL if built with x264/x265 etc.** | Ship LGPL build, or isolate |
| MLT (Kdenlive/Shotcut engine) | LGPL | Preview/render engine option [35] |
| Qwen 9B/4B GGUF quants | Apache-2.0 (check quantizer terms) | — |
| Llama-family alternatives | Community license (700M MAU clause) | Prefer Apache alternatives [6] |
| MLflow / DVC / Qdrant | Apache-2.0 | [55],[56] |

---

## 8. Major Risks, Open Questions, Decisions Needed

### Risks (ranked)
1. **8 GB VRAM contention** (LLM + ASR + VLM + training). Mitigation: serialize jobs, model-swap, CPU-offload tiers. *Must be measured on target hardware early* — every VRAM figure above is Q4-quantized inference; KV cache + fragmentation eats the slack. [Estimate]
2. **Edit-quality subjectivity**: no metric substitutes for human preference; budget for the A/B UX and accept/undo telemetry from day one.
3. **Scope**: a desktop NLE with real-time preview is a hard engineering problem on its own (Kdenlive/Shotcut embed MLT; DaVinci is a team of hundreds). Keep preview simple (proxy files, ffmpeg-backed) or build on MLT/GStreamer pipelines rather than a custom renderer.
4. **Small-model planning limits**: 9B will fail on genuinely hard multi-goal plans. Mitigation: plan decomposition + user approval + escalation policy (bigger local model via CPU offload, or explicit cloud).
5. **GBNF caveats**: valid JSON ≠ valid semantics [11]; complex schemas (anyOf unions) have crashed grammar engines [73] — keep tool schemas flat and simple.
6. **Training-data legality**: fixture videos must be owned/permissively licensed; WhisperX/pyannote gating in a shipped product needs a UX decision.
7. **Overtraining**: every fine-tune round risks regression on general ability → always gate with canary + full regression suite + rollback (Section 5).

### Decisions requiring user input
1. **UI stack: Tauri 2** (recommended: ~20× smaller, ~5× less RAM [69]) vs **Qt/PyQt** (pro-video ecosystem) vs **Electron** (max ecosystem)? Tauri requires Rust comfort.
2. **Primary OS target** (Windows-first implied by the GPU?) — affects installers, WhisperX/pyannote packaging.
3. **Cloud policy details**: is cloud allowed (a) never, (b) for data generation/teacher labeling only, (c) as explicit per-user escalation?
4. **Languages for ASR**: English+German covered by all options; broader multilingual favors Whisper (99 langs) over Parakeet (25). Which matters? (User is in DE — German accuracy should be fixture-tested.)
5. **Content priority**: short-form vs long-form vs gaming — each pulls Phase 4 work in different directions.
6. **Distribution/commercial intent** — decides how strict to be on GPL/CC-BY components and gated models.

### Unresolved research questions
- Can a 4B-tier model reach ≥95% semantic tool accuracy on *this* editor's real schema with ≤5k training samples? (No public evidence at this domain specificity — will be answered by Phase-3 measurements.)
- Perceptual edit-quality metrics are immature (AVE-Compass is 2026-fresh [67]); how well do LLM-judge rubrics correlate with the target user base? Needs in-house calibration data.
- Gaming event detection generalization across titles (research precedent fine-tunes per-genre X-CLIP [28]) — real accuracy on untrained games unknown.

---

## 9. Sources

**Agent/LLM tool calling & models**
1. Berkeley Function Calling Leaderboard (BFCL) — https://gorilla.cs.berkeley.edu/leaderboard.html
2. Docker — Local LLM tool-calling practical evaluation — https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/
3. J.D. Hodges — 13 local LLMs on tool calling — https://www.jdhodges.com/blog/local-llms-on-tool-calling-2026-pt1-local-lm/
4. vdf.ai — Best local LLM for agents and tool calling (2026) — https://vdf.ai/blog/best-local-llm-for-agents-tool-calling/
5. vdf.ai — Best small language models (note on Qwen3-8B BFCL) — https://vdf.ai/blog/best-small-language-models/
6. Ollama tool-calling models overview — https://localaimaster.com/blog/best-ollama-models-tool-calling
7. d-central.tech — Local LLM agent capability (BFCL 2026) — https://d-central.tech/local-llm-agent-capability/
8. llama.cpp GBNF grammars (official) — https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
9. Structured outputs & constrained decoding overview — https://www.tmls.nyc/research/structured-outputs-constrained-decoding
10. Constrained decoding engines compared (XGrammar/llguidance/Outlines/GBNF) — https://www.llms.blog/posts/constrained-decoding-and-structured-output-engines-in-production-comparing-xgrammar-llguidance-outlines-and-llama-cpp-gbnf-architecture-fsm-compilation-token-masking-latency-and-serving
11. Local LLM tool calling: validation caveats — https://theneuralbase.com/function-calling/learn/intermediate/llama-cpp-function-calling/

**ASR & alignment**
12. SYSTRAN/faster-whisper (repo, benchmarks) — https://github.com/SYSTRAN/faster-whisper
13. faster-whisper vs whisper.cpp speed tests — https://www.promptquorum.com/power-local-llm/local-whisper-stt-comparison-2026 ; https://www.x2q.net/post/whisper-backend-shootout/
14. codersera — faster-whisper vs whisper.cpp — https://codersera.com/blog/faster-whisper-vs-whisper-cpp-speech-to-text-2026/
15. Parakeet vs Whisper (WER, license) — https://localaimaster.com/blog/parakeet-vs-whisper ; Open ASR discussion https://www.digitalapplied.com/blog/local-speech-to-text-whisper-self-hosted-transcription-2026
16. Northflank STT benchmarks 2026 — https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks
17. m-bain/whisperX (repo) — https://github.com/m-bain/whisperX
18. WhisperX explained (alignment accuracy, pyannote, licenses) — https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/whisperx-diarization-word-level-timestamps

**Scene analysis & VLMs**
19. Breakthrough/PySceneDetect — https://github.com/Breakthrough/PySceneDetect · https://www.scenedetect.com/
20. soCzech/TransNetV2 — https://github.com/soCzech/TransNetV2 · paper https://arxiv.org/abs/2008.04838
21. TransNetV2 PyTorch port — https://pypi.org/project/transnetv2-pytorch/
22. MSU SBD benchmark (Wikipedia mirror) — https://en.wikipedia.org/wiki/Shot_transition_detection
23. Video RAG guide (shot detection + embeddings) — https://mixpeek.com/guides/video-rag-retrieval-augmented-generation-over-video
24. SceneSeen (CLIP-per-shot scene grouping pattern) — https://github.com/shadyhaytham81-source/SceneSeen
25. QwenLM/Qwen3-VL (repo) — https://github.com/QwenLM/Qwen3-VL
26. Local VLM sizing (Qwen3-VL 2/4/8B VRAM) — https://localaimaster.com/blog/best-local-vision-models · https://qwen-ai.com/qwen-vision/
27. SmolVLM (paper) — https://arxiv.org/abs/2504.05299 · HF blog https://huggingface.co/blog/smolvlm
28. Gameplay highlights via fine-tuned X-CLIP — https://arxiv.org/html/2505.07721v1

**Gaming highlights**
29. bendawg2010/Auto-clipper — https://github.com/bendawg2010/Auto-clipper
30. santiagobarengo/Detector-Highlights — https://github.com/santiagobarengo/Detector-Highlights
31. artkulak/twitch-stream-highlights-detection — https://github.com/artkulak/twitch-stream-highlights-detection
32. LIGHTOR (chat-based highlight extraction paper) — https://www.cs.sfu.ca/~jnwang/papers/lightor.pdf

**Video editing agents (research)**
38. LAVE — https://arxiv.org/abs/2402.10294 · project page https://www.dgp.toronto.edu/~bryanw/lave/
39. LAVE (ACM IUI'24) — https://dl.acm.org/doi/fullHtml/10.1145/3640543.3645143
42. Prompt-Driven Agentic Video Editing System — https://arxiv.org/html/2509.16811v1

**Editing infrastructure**
33. OpenTimelineIO timeline structure/rendering — https://opentimelineio.readthedocs.io/en/latest/tutorials/otio-timeline-structure.html
34. OpenTimelineIO (PyPI/repo) — https://pypi.org/project/OpenTimelineIO/ · Kdenlive native OTIO https://github.com/KDE/kdenlive-opentimelineio
35. MLT Framework — https://www.mltframework.org/features/
36. MoviePy — https://pypi.org/project/moviepy/ · limitations https://zulko.github.io/moviepy/getting_started/quick_presentation.html
37. FFmpeg-in-Python landscape & perf notes — https://www.ffmpeg-micro.com/blog/ffmpeg-in-python
68. Auto-Editor (silence cutting reference) — https://github.com/WyattBlue/auto-editor

**Fine-tuning**
43. Laptop fine-tuning hw guide — https://www.laptophub.net/how-to-fine-tune-small-llm-on-laptop/
44. LoRA/QLoRA hardware requirements — https://dev.to/jangwook_kim_e31e7291ad98/fine-tune-llms-with-lora-and-qlora-2026-guide-33lf · https://cloudzy.com/blog/lora-vs-qlora-vs-full-fine-tuning/
45. Unsloth requirements (official VRAM table) — https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements
46. QLoRA 8 GB guide — https://www.promptquorum.com/local-llms/fine-tuning-local-llms-lora
50. Unsloth QLoRA config example — https://www.channel.tel/blog/fine-tuning-lora-qlora-ai-agent-builders
51. Unsloth vs Axolotl VRAM measurements — https://www.local-llm.net/compare/unsloth-vs-axolotl/
52. Axolotl framework overview — https://www.spheron.network/blog/axolotl-vs-unsloth-vs-torchtune/

**Preference optimization / RL**
47. Preference method comparison (DPO/KTO/ORPO/GRPO) — https://decodethefuture.org/en/rlhf-explained/ · https://ai-tldr.dev/learn/fine-tuning/preference-training/what-is-hugging-face-trl/
48. GRPO vs DPO scaling — https://theneuralbase.com/huggingface-fine-tuning/learn/intermediate/grpo-vs-dpo-when-each/
49. TRL v1.0 (trainers lineup) — https://huggingface.co/blog/trl-v1
63. DPO beta guidance — https://yobitel.com/knowledge-base/dpo-direct-preference-optimisation

**Agent architecture & memory**
40. Context engineering best practices — https://prepkloud.com/blog-agentic-ai-mcp-engineering-guide.html
41. Agent memory taxonomy & stack — https://hjlabs.in/AIML/blog/post/the-future-of-agentic-ai.html
71. MCP tool-surface sizing (architecture patterns) — https://arxiv.org/html/2606.30317

**Evaluation: contamination, reward hacking, regression**
53. RL environment evaluation best practices (held-out, dedup, frozen envs) — https://www.patronus.ai/guide-to-rl-environments/reinforcement-learning-evaluation
54. Reward hacking in agent evaluation (audit trail guidance) — https://www.appen.com/blog/reward-hacking-ai-agent-evaluation
55. MLflow — https://mlflow.org/
56. DVC — https://dvc.org/
57. RewardHackingAgents (train_deny/full_locked regimes) — https://arxiv.org/html/2603.11337
58. Contamination strategies (canary strings etc.) — https://arxiv.org/html/2602.09305v1
59. Decontamination practice (fuzzy dedup, private held-out) — https://jxzhangjhu.github.io/blog/2026/how-frontier-labs-train-llms/
60. Anthropic — Natural emergent misalignment from reward hacking — https://assets.anthropic.com/m/74342f2c96095771/original/Natural-emergent-misalignment-from-reward-hacking-paper.pdf
61. BAITBENCH (shortcut lures) — https://arxiv.org/html/2608.30724v1
62. Appen — reward hacking audit recommendations — https://www.appen.com/blog/reward-hacking-ai-agent-evaluation

**Quality metrics**
64. PEAVS (ECCV 2024 AV-sync metric) — https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/10198.pdf
65. Netflix/vmaf — https://github.com/Netflix/vmaf
66. VMAF v1 (Netflix TechBlog, 2026) — https://netflixtechblog.com/vmaf-v1-good-is-not-good-enough-60d7e4244ea8
67. AVE-Compass (audio-video editing eval) — https://arxiv.org/html/2607.24821v1

**Desktop UI frameworks**
69. Tauri vs Electron 2026 comparisons — https://tech-insider.org/tauri-vs-electron-2026/ · https://techkis.tech/insights/tauri-vs-electron-binary-ram-autoupdate
70. Desktop app frameworks 2026 (incl. Qt) — https://codeminer.co/blog/desktop-application-development-guide-2026

**Other**
72. Qwen3 licensing (Apache-2.0) — https://github.com/QwenLM/Qwen3
73. GBNF crash on complex schemas (issue) — https://github.com/ikawrakow/ik_llama.cpp/issues/1484

---

*Prepared as research deliverable for Phase 1. No implementation performed; no workspace code or dependencies changed. All [Estimate]/[Hypothesis] items require on-target validation before being treated as facts.*
