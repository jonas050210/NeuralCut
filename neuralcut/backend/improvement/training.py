"""Fine-tuning preparation -- deliberately NOT executed here (Phase 6).

This module produces everything a home-PC training run needs and nothing
it shouldn't do from inside the app:

- dataset validation (manifest, provenance, split hygiene);
- a versioned ``TrainingConfig``;
- a reproducible dry-run job specification (exact command, dataset
  version/fingerprint, hardware requirements, expected outputs).

``TrainingPreparer.start`` always refuses: training runs as an external,
user-supervised process on the home PC (see docs/PACKAGING_AND_TRAINING.md
/ docs/SELF_IMPROVEMENT.md), never as an unattended in-app job and never
on user media. Only validated synthetic/feedback datasets may be used.
"""

from __future__ import annotations

from typing import Any

from neuralcut.backend.improvement.datasets import DATASET_VERSION, build_manifest
from neuralcut.errors import UnavailableError, ValidationError

HARDWARE_REQUIREMENTS = {
    "gpu": "NVIDIA RTX 4060 Ti 8 GB VRAM (research target) or better",
    "ram_gb": 32,
    "disk_gb_free": 40,
    "method": "QLoRA SFT (4-bit base, LoRA adapters) -- full fine-tuning of "
              "7-9B models does not fit 8 GB VRAM and is not supported",
    "expected_duration": "hours for a small adapter on thousands of traces "
                         "(estimate; measure on the home PC, not here)",
}


def validate_dataset_for_training(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest or build_manifest()
    problems: list[str] = []
    if manifest.get("dataset_version") != DATASET_VERSION:
        problems.append("dataset version mismatch")
    cases = manifest.get("cases") or []
    if not cases:
        problems.append("dataset has no cases")
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        problems.append("duplicate case ids")
    splits: dict[str, set[str]] = {}
    for case in cases:
        if not case.get("provenance", {}).get("source"):
            problems.append(f"case {case['id']} lacks provenance")
        splits.setdefault(case["split"], set()).add(case["id"])
    names = list(splits)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if splits[a] & splits[b]:
                problems.append(f"split leakage between {a} and {b}")
    if "held_out" not in splits:
        problems.append("no held-out split present")
    return {"valid": not problems, "problems": problems,
            "dataset_version": manifest.get("dataset_version"),
            "fingerprint": manifest.get("fingerprint"),
            "split_counts": manifest.get("split_counts")}


class TrainingPreparer:
    def __init__(self, container) -> None:  # noqa: ANN001
        self._container = container

    def prepare(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build a dry-run training job specification. Executes nothing."""
        config = config or {}
        validation = validate_dataset_for_training()
        if not validation["valid"]:
            raise ValidationError(
                "dataset is not valid for training",
                details={"validation": validation})
        base_model = config.get(
            "base_model",
            "Qwen/Qwen3-4B-Instruct-2507 (HF safetensors, Apache-2.0 -- "
            "license verified on the HF repo; GGUF is inference-only)")
        spec = {
            "job": "orchestrator-qlora-sft",
            "dry_run": True,
            "executes_training": False,
            "base_model": base_model,
            "dataset": {
                "version": validation["dataset_version"],
                "fingerprint": validation["fingerprint"],
                "splits_used": ["train", "val"],
                "held_out": "sealed -- promotion gates only, never trained on",
            },
            "hyperparameters": {
                "method": "QLoRA (nf4, double quant)",
                "lora_r": config.get("lora_r", 16),
                "lora_alpha": config.get("lora_alpha", 32),
                "learning_rate": config.get("learning_rate", 1e-4),
                "epochs": config.get("epochs", 2),
                "max_seq_len": config.get("max_seq_len", 4096),
                "seed": config.get("seed", 42),
            },
            "hardware_requirements": HARDWARE_REQUIREMENTS,
            "command_preview": [
                "# On the home PC, in the separate training env (scripts/setup_training.ps1):",
                ".venv-training\\Scripts\\python.exe -m neuralcut.training.train_qlora --preflight",
                ".venv-training\\Scripts\\python.exe -m neuralcut.training.train_qlora \\",
                f"  --dataset benchmark-{DATASET_VERSION}.json \\",
                "  --base-model Qwen/Qwen3-4B-Instruct-2507 --output adapters/orchestrator-v1",
                "# add --confirm-training to actually train; default is a dry run",
            ],
            "outputs": ["adapter weights (versioned)", "training log",
                        "evaluation report vs incumbent on val + held-out"],
            "promotion": "adapter becomes a *candidate configuration*; it "
                         "must pass the same registry gates + human "
                         "spot-check before any promotion",
        }
        return spec

    def start(self, *args, **kwargs):  # noqa: ANN002, ARG002
        raise UnavailableError(
            "training is prepared but never executed inside NeuralCut. "
            "Use the dry-run job specification on the home PC.",
            details={"feature": "improvement.training.start", "phase": 6})
