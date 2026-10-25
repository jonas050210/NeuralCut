"""QLoRA SFT entrypoint: `python -m neuralcut.training.train_qlora`.

Connects to the Phase 6 dry-run specification
(`backend.improvement.training.TrainingPreparer`):

- Default behaviour (no flags) is a **dry run**: validate the dataset,
  build the SFT example files, estimate VRAM, print the plan. Nothing is
  downloaded and no training happens.
- `--preflight` reports dependency/CUDA/VRAM/dataset readiness and exits
  non-zero when requirements are missing.
- Real training requires the explicit `--confirm-training` flag, the
  separate training environment (requirements-training.txt), and a CUDA
  GPU. It writes a LoRA adapter + `training_manifest.json`; the adapter
  is afterwards only a *candidate* for the human-gated promotion flow.
- Held-out data is never trained on and never written to the SFT files;
  requesting it raises.

Recommended base model (license verified 2026-10-24 against the
Hugging Face LICENSE file): `Qwen/Qwen3-4B-Instruct-2507`, Apache 2.0,
4.0B parameters, `transformers>=4.51`. GGUF files are for inference
servers (llama.cpp/Ollama) and cannot be QLoRA-trained with this stack;
use the HF safetensors repo id or a local HF-format directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
BASE_MODEL_INFO = {
    "id": DEFAULT_BASE_MODEL,
    "license": "Apache-2.0 (verified on the HF repo LICENSE file)",
    "parameters_b": 4.0,
    "min_transformers": "4.51",
    "format": "HF safetensors (not GGUF)",
}


class TrainingError(RuntimeError):
    """Raised for any refusal/misconfiguration in the training pipeline."""


@dataclass
class TrainingJobConfig:
    dataset: str = ""  # path to a benchmark manifest JSON (or "" = built-in)
    base_model: str = DEFAULT_BASE_MODEL
    output_dir: str = "adapters/orchestrator-v1"
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    learning_rate: float = 1e-4
    epochs: float = 2.0
    max_seq_len: int = 2048
    per_device_train_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    seed: int = 42
    train_splits: tuple[str, ...] = ("train",)
    eval_split: str = "val"

    def validate(self) -> None:
        if "held_out" in self.train_splits or self.eval_split == "held_out":
            raise TrainingError(
                "held-out data is sealed: it must never be used for "
                "training or tuning")
        if self.base_model.lower().endswith(".gguf"):
            raise TrainingError(
                "GGUF models are inference artifacts and cannot be trained "
                "with transformers/PEFT; use the HF repo id or an "
                "HF-format directory")
        if self.max_seq_len > 8192:
            raise TrainingError(
                "max_seq_len > 8192 will not fit an 8 GB GPU at these "
                "settings; reduce it (2048 is ample for tool-call plans)")


# --------------------------------------------------------------------------
# Dataset -> SFT examples
# --------------------------------------------------------------------------

_SYSTEM = (
    "You are NeuralCut's editing planner. Reply with ONLY a JSON object: "
    '{"steps": [{"tool": "<tool name>", "args": {...}}], "explanation": '
    '"<short text>"}. Use only IDs from the project context.'
)

# Synthetic project contexts mirroring benchmark setups (fixed IDs so the
# builtin planner can resolve references deterministically).
_CONTEXTS: dict[str, dict[str, Any]] = {
    "empty": {"assets": [], "clips": [], "duration_seconds": 0.0},
    "single": {
        "assets": [{"id": "asset-hero", "name": "hero.mp4"}],
        "clips": [{"id": "clip-hero", "name": "hero.mp4", "asset_id": "asset-hero",
                   "track": 0, "timeline_start_seconds": 0.0,
                   "source_start_seconds": 0.0, "source_end_seconds": 3.0,
                   "effects": []}],
        "duration_seconds": 3.0},
    "single_plus_asset": {
        "assets": [{"id": "asset-hero", "name": "hero.mp4"},
                   {"id": "asset-broll", "name": "broll.mp4"}],
        "clips": [{"id": "clip-hero", "name": "hero.mp4", "asset_id": "asset-hero",
                   "track": 0, "timeline_start_seconds": 0.0,
                   "source_start_seconds": 0.0, "source_end_seconds": 3.0,
                   "effects": []}],
        "duration_seconds": 3.0},
    "two": {
        "assets": [{"id": "asset-hero", "name": "hero.mp4"},
                   {"id": "asset-broll", "name": "broll.mp4"}],
        "clips": [{"id": "clip-hero", "name": "hero.mp4", "asset_id": "asset-hero",
                   "track": 0, "timeline_start_seconds": 0.0,
                   "source_start_seconds": 0.0, "source_end_seconds": 3.0,
                   "effects": []},
                  {"id": "clip-broll", "name": "broll.mp4", "asset_id": "asset-broll",
                   "track": 0, "timeline_start_seconds": 3.0,
                   "source_start_seconds": 0.0, "source_end_seconds": 3.0,
                   "effects": []}],
        "duration_seconds": 6.0},
    "ambiguous": {
        "assets": [{"id": "asset-hero", "name": "hero.mp4"},
                   {"id": "asset-broll", "name": "broll.mp4"}],
        "clips": [{"id": "clip-hero-a", "name": "hero-a.mp4", "asset_id": "asset-hero",
                   "track": 0, "timeline_start_seconds": 0.0,
                   "source_start_seconds": 0.0, "source_end_seconds": 3.0,
                   "effects": []},
                  {"id": "clip-hero-b", "name": "hero-b.mp4", "asset_id": "asset-broll",
                   "track": 0, "timeline_start_seconds": 3.0,
                   "source_start_seconds": 0.0, "source_end_seconds": 3.0,
                   "effects": []}],
        "duration_seconds": 6.0},
}


def load_manifest(dataset_path: str = "") -> dict[str, Any]:
    from neuralcut.backend.improvement.datasets import build_manifest

    if not dataset_path:
        return build_manifest()
    path = Path(dataset_path)
    if not path.is_file():
        raise TrainingError(f"dataset manifest not found: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrainingError(f"dataset manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or "cases" not in manifest:
        raise TrainingError("dataset manifest must be an object with 'cases'")
    return manifest


def build_sft_examples(manifest: dict[str, Any],
                       splits: tuple[str, ...]) -> list[dict[str, str]]:
    """Generate instruction -> JSON-plan traces with the builtin planner.

    Traces come from the deterministic planner on synthetic contexts (the
    same setups the benchmark grades), so the training signal is verified
    behaviour, not model-generated text.
    """
    from neuralcut.backend.agent.planner import builtin_plan
    from neuralcut.backend.improvement.training import validate_dataset_for_training

    validation = validate_dataset_for_training(manifest)
    if not validation["valid"]:
        raise TrainingError(
            f"dataset failed validation: {validation['problems']}")
    if "held_out" in splits:
        raise TrainingError("held-out data is sealed and cannot be exported for training")
    examples: list[dict[str, str]] = []
    for case in manifest["cases"]:
        if case["split"] not in splits:
            continue
        context = _CONTEXTS[case["setup"]]
        result = builtin_plan(case["instruction"], context)
        if result.get("steps"):
            target = {"steps": [s.model_dump() for s in result["steps"]],
                      "explanation": result.get("explanation", "")}
        else:
            target = {"steps": [],
                      "explanation": result.get("clarification", "needs clarification")}
        prompt = (
            f"<|system|>\n{_SYSTEM}\n<|user|>\n"
            + json.dumps({"request": case["instruction"],
                          "project_context": context}, sort_keys=True)
            + "\n<|assistant|>\n")
        examples.append({
            "text": prompt + json.dumps(target, sort_keys=True) + "<|end|>",
            "case_id": case["id"], "split": case["split"],
            "dataset_fingerprint": manifest.get("fingerprint", ""),
        })
    if not examples:
        raise TrainingError(f"no cases found for splits {splits}")
    return examples


def write_sft_files(config: TrainingJobConfig, out_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(config.dataset)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Any] = {"fingerprint": manifest.get("fingerprint")}
    for label, splits in (("train", tuple(config.train_splits)),
                          ("eval", (config.eval_split,))):
        examples = build_sft_examples(manifest, splits)
        path = out_dir / f"sft_{label}.jsonl"
        contents = "".join(json.dumps(e, sort_keys=True) + "\n" for e in examples)
        if path.exists():
            if path.read_text(encoding="utf-8") != contents:
                raise TrainingError(
                    f"refusing to overwrite existing SFT data: {path}; use a new output directory")
        else:
            path.write_text(contents, encoding="utf-8")
        written[label] = {"file": str(path), "examples": len(examples),
                          "splits": list(splits)}
    return written


# --------------------------------------------------------------------------
# Hardware / dependency preflight
# --------------------------------------------------------------------------

def estimate_vram_gb(config: TrainingJobConfig,
                     parameters_b: float = BASE_MODEL_INFO["parameters_b"]) -> dict[str, Any]:
    """Rough QLoRA memory budget (estimates, labelled as such).

    4-bit NF4 weights ~0.55 B/param incl. quant metadata; LoRA trainable
    weights + AdamW states scale with rank; activations assume gradient
    checkpointing. These are planning numbers, not measurements.
    """
    weights = parameters_b * 0.55
    lora_trainable_m = 45 * (config.lora_r / 16)  # ~45M trainable at r=16 for 4B
    optimizer = lora_trainable_m * 12 / 1000  # AdamW fp32 states+moments+master
    gradients = lora_trainable_m * 2 / 1000
    activations = 0.6 + 0.35 * (config.max_seq_len / 2048) * config.per_device_train_batch_size
    total = weights + optimizer + gradients + activations + 0.8  # CUDA context/misc
    return {
        "estimate": True,
        "weights_4bit_gb": round(weights, 2),
        "optimizer_gb": round(optimizer, 2),
        "gradients_gb": round(gradients, 2),
        "activations_gb": round(activations, 2),
        "total_estimate_gb": round(total, 2),
        "budget_gb": 8.0,
        "fits_8gb": total <= 7.2,
        "note": "planning estimate for RTX 4060 Ti 8 GB; keep >=0.8 GB "
                "headroom. Reduce max_seq_len/batch if preflight disagrees.",
    }


def preflight(config: TrainingJobConfig) -> dict[str, Any]:
    import importlib
    import importlib.metadata

    config.validate()
    report: dict[str, Any] = {"ready": True, "problems": [], "warnings": []}
    modules = {}
    for name, minimum in (("torch", None), ("transformers", "4.51"),
                          ("peft", None), ("trl", None), ("datasets", None),
                          ("accelerate", None), ("bitsandbytes", None)):
        try:
            importlib.import_module(name)
            version = importlib.metadata.version(name)
            modules[name] = version
            if minimum and version.split(".")[:2] < minimum.split(".")[:2]:
                report["problems"].append(
                    f"{name} {version} < required {minimum} (Qwen3 support)")
        except Exception:  # noqa: BLE001 - missing dep is the expected state here
            modules[name] = None
            report["problems"].append(
                f"{name} is not installed (use the separate training env: "
                "scripts/setup_training.ps1)")
    report["modules"] = modules
    if modules.get("torch"):
        torch = importlib.import_module("torch")
        report["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            report["gpu"] = {"name": props.name,
                             "vram_gb": round(props.total_memory / 1e9, 2)}
            if props.total_memory / 1e9 < 7.5:
                report["warnings"].append("GPU has <7.5 GB VRAM; expect OOM at defaults")
        else:
            report["problems"].append("CUDA is not available (training needs an NVIDIA GPU)")
    report["vram_estimate"] = estimate_vram_gb(config)
    if not report["vram_estimate"]["fits_8gb"]:
        report["warnings"].append("VRAM estimate exceeds the safe 8 GB budget")
    try:
        manifest = load_manifest(config.dataset)
        from neuralcut.backend.improvement.training import validate_dataset_for_training

        validation = validate_dataset_for_training(manifest)
        report["dataset"] = validation
        if not validation["valid"]:
            report["problems"].append(f"dataset invalid: {validation['problems']}")
    except TrainingError as exc:
        report["problems"].append(str(exc))
    out = Path(config.output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report["output_dir_writable"] = True
    except OSError as exc:
        report["output_dir_writable"] = False
        report["problems"].append(f"output dir not writable: {exc}")
    report["ready"] = not report["problems"]
    return report


# --------------------------------------------------------------------------
# Training (explicitly confirmed only)
# --------------------------------------------------------------------------

def find_latest_checkpoint(output_dir: str | Path) -> str | None:
    """Return the numerically latest checkpoint (selection is never implicit)."""
    out = Path(output_dir)
    if not out.is_dir():
        return None
    checkpoints = sorted(
        (p for p in out.glob("checkpoint-*") if p.is_dir()),
        key=lambda p: int(p.name.split("-")[-1]) if p.name.split("-")[-1].isdigit() else -1)
    return str(checkpoints[-1]) if checkpoints else None


def validate_resume_checkpoint(output_dir: str | Path, checkpoint: str | Path) -> str:
    """Ensure a selected checkpoint is inside this run and can make progress."""
    out = Path(output_dir).resolve()
    selected = Path(checkpoint)
    if not selected.is_absolute():
        selected = out / selected
    selected = selected.resolve()
    if (selected.parent != out or not selected.is_dir()
            or not selected.name.startswith("checkpoint-")):
        raise TrainingError(
            "resume checkpoint must be a checkpoint-* directory inside the output directory")
    latest = find_latest_checkpoint(out)
    if latest is not None and Path(latest).resolve() != selected:
        raise TrainingError(
            "refusing to resume an older checkpoint while newer checkpoints exist; "
            "use the latest checkpoint or a new output directory")
    state_path = selected / "trainer_state.json"
    if not state_path.is_file():
        raise TrainingError(f"checkpoint is not resumable (missing trainer_state.json): {selected}")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        global_step = int(state["global_step"])
        max_steps = int(state["max_steps"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise TrainingError(f"checkpoint has invalid trainer state: {selected}") from exc
    if global_step >= max_steps:
        raise TrainingError(
            f"checkpoint is already complete (global_step={global_step}, max_steps={max_steps}); "
            "choose an incomplete checkpoint or a new output directory")
    required = ("optimizer.pt", "scheduler.pt")
    missing = [name for name in required if not (selected / name).is_file()]
    if missing:
        raise TrainingError(f"checkpoint is not resumable; missing {', '.join(missing)}")
    weight_files = (
        "adapter_model.safetensors", "adapter_model.bin",
        "model.safetensors", "pytorch_model.bin")
    if not any((selected / name).is_file() for name in weight_files):
        raise TrainingError("checkpoint is not resumable (missing model/adapter weights)")
    return str(selected)


def _json_safe(value: Any) -> Any:
    """Convert trainer metrics (including numpy scalar values) to JSON values."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _load_stack() -> dict[str, Any]:
    """Import the heavy training stack (isolated so tests can stub it)."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
    )
    from trl import SFTConfig, SFTTrainer

    return {
        "torch": torch, "Dataset": Dataset, "LoraConfig": LoraConfig,
        "get_peft_model": get_peft_model,
        "prepare_model_for_kbit_training": prepare_model_for_kbit_training,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "BitsAndBytesConfig": BitsAndBytesConfig,
        "SFTConfig": SFTConfig, "SFTTrainer": SFTTrainer,
    }


def run_training(config: TrainingJobConfig, *, confirm: bool = False,
                 resume_from_checkpoint: str | None = None) -> dict[str, Any]:
    """Run QLoRA SFT. Refuses without confirmation, explicit resume, and a GPU."""
    if not confirm:
        raise TrainingError(
            "real training requires the explicit --confirm-training flag; "
            "run with --dry-run or --preflight instead")
    config.validate()
    out_dir = Path(config.output_dir)
    if resume_from_checkpoint is None:
        if out_dir.exists() and not out_dir.is_dir():
            raise TrainingError(f"output path is not a directory: {out_dir}")
        if out_dir.exists() and any(out_dir.iterdir()):
            raise TrainingError(
                f"output directory is not empty: {out_dir}; use a new output directory "
                "or explicitly resume from an incomplete checkpoint")
        resume = None
    else:
        selected = (find_latest_checkpoint(out_dir)
                    if resume_from_checkpoint == "latest" else resume_from_checkpoint)
        if selected is None:
            raise TrainingError(f"no checkpoint found to resume in {out_dir}")
        resume = validate_resume_checkpoint(out_dir, selected)
        if (out_dir / "adapter").exists():
            raise TrainingError(
                f"refusing to overwrite existing adapter: {out_dir / 'adapter'}; "
                "use a new output directory")
    check = preflight(config)
    if not check["ready"]:
        raise TrainingError(f"preflight failed: {check['problems']}")
    stack = _load_stack()
    torch = stack["torch"]
    if not torch.cuda.is_available():  # belt-and-braces; preflight checks too
        raise TrainingError("CUDA GPU required for QLoRA training")

    files = write_sft_files(config, out_dir / "data")
    train_data = [json.loads(line) for line in
                  Path(files["train"]["file"]).read_text(encoding="utf-8").splitlines()]
    eval_data = [json.loads(line) for line in
                 Path(files["eval"]["file"]).read_text(encoding="utf-8").splitlines()]

    tokenizer = stack["AutoTokenizer"].from_pretrained(config.base_model)
    if getattr(tokenizer, "pad_token", None) is None:
        tokenizer.pad_token = tokenizer.eos_token
    quant = stack["BitsAndBytesConfig"](
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = stack["AutoModelForCausalLM"].from_pretrained(
        config.base_model, quantization_config=quant, device_map="auto")
    model = stack["prepare_model_for_kbit_training"](model)
    lora = stack["LoraConfig"](
        r=config.lora_r, lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])
    model = stack["get_peft_model"](model, lora)

    sft_config = stack["SFTConfig"](
        output_dir=str(out_dir), num_train_epochs=config.epochs,
        per_device_train_batch_size=config.per_device_train_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate, lr_scheduler_type="cosine",
        warmup_ratio=0.03, logging_strategy="steps", logging_steps=1,
        eval_strategy="epoch", save_strategy="epoch",
        bf16=True, gradient_checkpointing=True, seed=config.seed,
        dataset_text_field="text", max_length=config.max_seq_len,
        report_to=[])
    trainer = stack["SFTTrainer"](
        model=model, args=sft_config,
        train_dataset=stack["Dataset"].from_list(train_data),
        eval_dataset=stack["Dataset"].from_list(eval_data),
        processing_class=tokenizer)
    train_result = trainer.train(resume_from_checkpoint=resume)
    training_metrics = getattr(train_result, "metrics", {}) or {}
    evaluation_metrics = trainer.evaluate()
    adapter_dir = out_dir / "adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    metrics = {
        "training": _json_safe(training_metrics),
        "evaluation": _json_safe(evaluation_metrics),
        "global_step": getattr(getattr(trainer, "state", None), "global_step", None),
        "log_history": _json_safe(getattr(getattr(trainer, "state", None), "log_history", [])),
    }
    metrics_path = out_dir / "training_metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "job": "orchestrator-qlora-sft", "base_model": config.base_model,
        "base_model_license": BASE_MODEL_INFO["license"],
        "config": asdict(config), "dataset_files": files,
        "metrics_file": metrics_path.name,
        "resumed_from": resume, "seed": config.seed,
        "promotion": "adapter is a candidate only; promotion requires the "
                     "improvement registry gates + human spot-check",
    }
    (out_dir / "training_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {"adapter_dir": str(adapter_dir), "manifest": manifest,
            "resumed_from": resume, "metrics_file": str(metrics_path)}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="neuralcut-training",
        description="NeuralCut QLoRA training (home PC, explicit opt-in)")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--output", default="adapters/orchestrator-v1")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--preflight", action="store_true",
                        help="check deps/CUDA/VRAM/dataset and exit")
    parser.add_argument("--resume", nargs="?", const="latest", default=None,
                        metavar="CHECKPOINT",
                        help="explicitly resume an incomplete checkpoint (path or 'latest')")
    parser.add_argument("--confirm-training", action="store_true",
                        help="actually train (requires CUDA + training env)")
    args = parser.parse_args(argv)
    config = TrainingJobConfig(
        dataset=args.dataset, base_model=args.base_model,
        output_dir=args.output, epochs=args.epochs, lora_r=args.lora_r,
        max_seq_len=args.max_seq_len, seed=args.seed)
    try:
        config.validate()
        if args.resume is not None and not args.confirm_training:
            raise TrainingError("--resume is only valid together with --confirm-training")
        if args.preflight:
            report = preflight(config)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["ready"] else 2
        if args.confirm_training:
            result = run_training(config, confirm=True,
                                  resume_from_checkpoint=args.resume)
            print(json.dumps({"adapter_dir": result["adapter_dir"],
                              "resumed_from": result["resumed_from"],
                              "metrics_file": result["metrics_file"]}, indent=2))
            return 0
        # Default: dry run only.
        check = preflight(config)
        files = write_sft_files(config, Path(config.output_dir) / "data")
        plan = {
            "dry_run": True, "executes_training": False,
            "base_model": BASE_MODEL_INFO, "config": asdict(config),
            "sft_files": files, "vram_estimate": estimate_vram_gb(config),
            "preflight_ready": check["ready"],
            "preflight_problems": check["problems"],
            "next_step": "install the training env (scripts/setup_training.ps1), "
                         "re-run with --preflight, then --confirm-training",
        }
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    except TrainingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
