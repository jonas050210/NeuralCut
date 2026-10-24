# Self-Improvement and Evaluation Plan

This document describes the planned Phase 6 system. **Phase 1 does not train models, collect learning feedback, run autonomous experiments, or change its own behavior.** It only provides `EvaluationAdapter` and `SelfImprovementAdapter` contracts that report unavailable.

## Goal

Improve NeuralCut's future AI assistance through measured, reversible changes:

- Better tools, prompts, retrieval, and deterministic rules first.
- Better model adapters/weights only when logged failures show system-level fixes are insufficient.
- No candidate replaces the incumbent without held-out evaluation, regression checks, and human review.

## Planned loop

```text
Licensed fixture projects/videos
          │
          ▼
Task suite (versioned JSON tasks)
          │
          ▼
Sandbox runner on fixture copies ──► event/tool logs
          │
          ▼
Deterministic graders + advisory judges
          │
      ┌───┴───────────────┐
      ▼                   ▼
Failure mining       Experiment report
      │
      ▼
Human review/corrections
      │
      ▼
Versioned data registry
(SFT, preference, regression, sealed held-out)
      │
      ▼
Candidate change
(prompt/tool/retrieval/config/adapter/model)
      │
      ▼
Promotion gate ── fail ─► keep incumbent / revise candidate
      │ pass
      ▼
Release candidate with rollback artifact
```

## Evaluation layers

### Deterministic gates

These should block promotion when they fail:

- Project/timeline schema validity.
- Requested operations are observable in the resulting timeline diff.
- Clip ranges, gaps/overlaps, and frame/time invariants.
- A/V sync checks.
- Dialogue preservation against transcripts.
- Subtitle timing, duration, and reading-speed rules.
- Loudness, clipping, and required fades/normalization.
- Render/file validity and, where appropriate, full-reference encode quality.
- Task-specific pacing/content checks derived from analysis artifacts.

### Advisory model-based evaluation

- LLM/VLM judges with pinned model, prompt, rubric, and version.
- Caption/semantic relevance scores.
- Taste-level comparisons calibrated against human labels.

Model judges must not be the sole promotion gate because they can drift or be gamed.

### Human signals

- Accept/reject/undo of agent plans and edits.
- A/B “keep version A or B?” choices.
- Corrections made by reviewers.
- Edit distance from agent output to the user's final saved version.

Human feedback collection must be explicit, inspectable, and deletable. Private user media must never enter a training dataset silently.

## Data governance

- Fixture media must be owned, public-domain, or otherwise licensed for the intended evaluation/training use.
- Dataset versions record source, license, task template, preprocessing, and code/model versions.
- Split by **source video** and **task template** to reduce leakage.
- Maintain a sealed held-out set used only at promotion gates.
- Use canary markers and access deny-lists where practical to detect contamination.
- Store derived transcripts/captions/embeddings with the same care as source media.

## Candidate changes: choose the right layer

| Symptom | First fix layer |
|---|---|
| Wrong tool for a covered pattern | Prompt/tool description, then SFT if repeated |
| Hallucinated clip ID or stale duration | Project-state construction/retrieval |
| Cuts consistently too aggressive | Critic thresholds/recipes, then preference data |
| Slow response | Routing, context size, caching, smaller model |
| New phrasing not understood | Prompt/grammar/examples, then targeted SFT |
| Missed visual/audio event | Perception pipeline/features, not the LLM |

Escalate to weight training only with evidence that simpler layers failed on recurring, measured cases.

## Training plan (future, optional)

Research indicates the plausible path on an 8 GB NVIDIA GPU is:

1. **QLoRA SFT** for the orchestrator on verified tool-call/plan traces.
2. **KTO/DPO/ORPO preference passes** from explicit accept/reject or paired preferences.
3. Regression and canary evaluation after every candidate.

Not planned as defaults:

- Full fine-tuning of 7–9B models on 8 GB VRAM.
- PPO/GRPO on-policy RL on consumer 8 GB hardware.
- Fine-tuning ASR/VLM/embedding models before pipeline/prompt fixes are exhausted.

Training must run as an isolated, cancellable job or external process. It must never run automatically while the user is editing.

## Promotion gate

A candidate may be promoted only if:

1. It meets or exceeds the incumbent on the sealed held-out suite.
2. It passes the full regression suite without unacceptable failures.
3. Canary checks show no major loss of general instruction/tool-calling ability.
4. A human spot-checks representative successes and failures.
5. Rollback artifacts and version metadata are stored.
6. The change, metrics, and known regressions are documented.

“Higher average score” alone is insufficient if a critical task class regresses.

## Anti-gaming and regression safeguards

- Multi-signal gates; no single scalar reward.
- Randomized or varied grader thresholds where appropriate.
- Adversarial fixtures where shortcut behavior fails.
- Audit unusually large score jumps manually.
- Pin evaluator/judge versions and hash prompts/configs.
- Separate experiment data from held-out promotion data.
- Keep adapters/models small and versioned for instant rollback.
- Track per-tool and per-task-class regressions, not only global averages.

## Phase 1 boundaries

Current adapters only expose status. There is:

- No fixture library.
- No grader implementation.
- No feedback store.
- No experiment tracker.
- No dataset registry.
- No training job.
- No promotion/rollback mechanism.

Those are Phase 6 deliverables and require the Phase 2 deterministic editing core plus Phase 5 agent/tool surface to exist first.
