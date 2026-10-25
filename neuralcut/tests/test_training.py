"""Training pipeline tests: dataset hygiene, preflight, dry-run, mocked run.

No real GPU/model/training is involved: the heavy stack is stubbed, and
the run tests verify wiring (quantization config, LoRA, explicit checkpoint
resume, logging/evaluation, adapter save, metrics and manifest) only.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from neuralcut.training import train_qlora as tq


def test_config_refuses_held_out_and_gguf() -> None:
    with pytest.raises(tq.TrainingError):
        tq.TrainingJobConfig(train_splits=("train", "held_out")).validate()
    with pytest.raises(tq.TrainingError):
        tq.TrainingJobConfig(eval_split="held_out").validate()
    with pytest.raises(tq.TrainingError):
        tq.TrainingJobConfig(base_model="model.gguf").validate()


def test_sft_examples_exclude_held_out_and_contain_plans(tmp_path: Path) -> None:
    config = tq.TrainingJobConfig(output_dir=str(tmp_path / "out"))
    files = tq.write_sft_files(config, tmp_path / "data")
    train = [json.loads(x) for x in
             Path(files["train"]["file"]).read_text().splitlines()]
    assert train and all(e["split"] == "train" for e in train)
    assert any('"split_clip"' in e["text"] for e in train)
    manifest = tq.load_manifest("")
    with pytest.raises(tq.TrainingError):
        tq.build_sft_examples(manifest, ("held_out",))


def test_vram_estimate_fits_8gb_at_defaults() -> None:
    estimate = tq.estimate_vram_gb(tq.TrainingJobConfig())
    assert estimate["fits_8gb"] is True
    assert estimate["total_estimate_gb"] < 7.2
    big = tq.estimate_vram_gb(tq.TrainingJobConfig(max_seq_len=8192,
                                                   per_device_train_batch_size=4))
    assert big["total_estimate_gb"] > estimate["total_estimate_gb"]


def test_preflight_reports_missing_deps_without_gpu(tmp_path: Path) -> None:
    config = tq.TrainingJobConfig(output_dir=str(tmp_path / "out"))
    report = tq.preflight(config)
    # This environment intentionally has no training stack installed.
    assert report["ready"] is False
    assert any("not installed" in p for p in report["problems"])
    assert report["dataset"]["valid"] is True
    assert report["output_dir_writable"] is True


def test_cli_dry_run_and_refusals(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    out = tmp_path / "adapter-out"
    assert tq.main(["--output", str(out)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True and plan["executes_training"] is False
    assert (out / "data" / "sft_train.jsonl").is_file()
    with pytest.raises(tq.TrainingError):
        tq.run_training(tq.TrainingJobConfig(output_dir=str(out)), confirm=False)
    assert tq.main(["--preflight", "--output", str(out)]) == 2  # deps missing here


class _FakeModel:
    def save_pretrained(self, path):  # noqa: ANN001
        Path(path).mkdir(parents=True, exist_ok=True)
        Path(path, "adapter_model.safetensors").write_bytes(b"fake")


class _FakeTrainer:
    saved_to: str | None = None
    resumed_from = "unset"
    instance = None

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        self.kwargs = kwargs
        self.state = types.SimpleNamespace(global_step=4, log_history=[{"loss": 0.5}])
        _FakeTrainer.instance = self

    def train(self, resume_from_checkpoint=None):  # noqa: ANN001
        _FakeTrainer.resumed_from = resume_from_checkpoint
        return types.SimpleNamespace(metrics={"train_loss": 0.5, "train_runtime": 2.0})

    def evaluate(self):
        return {"eval_loss": 0.4, "eval_runtime": 0.5}

    def save_model(self, path) -> None:  # noqa: ANN001
        _FakeTrainer.saved_to = path
        _FakeModel().save_pretrained(path)


def _fake_stack() -> dict:
    torch = types.SimpleNamespace(
        bfloat16="bf16", cuda=types.SimpleNamespace(is_available=lambda: True))
    return {
        "torch": torch,
        "Dataset": types.SimpleNamespace(from_list=lambda rows: rows),
        "LoraConfig": lambda **kw: ("lora", kw),
        "get_peft_model": lambda model, cfg: model,
        "prepare_model_for_kbit_training": lambda model: model,
        "AutoModelForCausalLM": types.SimpleNamespace(
            from_pretrained=lambda *a, **kw: _FakeModel()),
        "AutoTokenizer": types.SimpleNamespace(from_pretrained=lambda *a, **kw: (
            types.SimpleNamespace(pad_token=None, eos_token="<eos>",
                                  save_pretrained=lambda p: Path(p).mkdir(
                                      parents=True, exist_ok=True)))),
        "BitsAndBytesConfig": lambda **kw: ("bnb", kw),
        "SFTConfig": lambda **kw: ("sftconfig", kw),
        "SFTTrainer": _FakeTrainer,
    }


def test_mocked_training_run_saves_adapter_and_manifest(
        monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    config = tq.TrainingJobConfig(output_dir=str(tmp_path / "run"))
    monkeypatch.setattr(tq, "_load_stack", _fake_stack)
    monkeypatch.setattr(tq, "preflight", lambda cfg: {"ready": True, "problems": []})
    result = tq.run_training(config, confirm=True)
    adapter = Path(result["adapter_dir"])
    assert (adapter / "adapter_model.safetensors").is_file()
    manifest = json.loads(
        (tmp_path / "run" / "training_manifest.json").read_text())
    assert manifest["base_model"] == tq.DEFAULT_BASE_MODEL
    assert "candidate only" in manifest["promotion"]
    assert result["resumed_from"] is None
    assert _FakeTrainer.resumed_from is None
    args = _FakeTrainer.instance.kwargs["args"][1]
    assert args["logging_strategy"] == "steps" and args["logging_steps"] == 1
    assert args["eval_strategy"] == "epoch" and args["save_strategy"] == "epoch"
    metrics = json.loads(Path(result["metrics_file"]).read_text())
    assert metrics["training"]["train_loss"] == 0.5
    assert metrics["evaluation"]["eval_loss"] == 0.4
    assert metrics["global_step"] == 4

    checkpoint = tmp_path / "run" / "checkpoint-3"
    checkpoint.mkdir()
    assert tq.find_latest_checkpoint(tmp_path / "run") == str(checkpoint)


def _valid_checkpoint(path: Path, *, global_step: int = 2, max_steps: int = 4) -> None:
    path.mkdir(parents=True)
    (path / "trainer_state.json").write_text(json.dumps({
        "global_step": global_step, "max_steps": max_steps}), encoding="utf-8")
    for filename in ("optimizer.pt", "scheduler.pt", "adapter_model.safetensors"):
        (path / filename).write_bytes(b"fake")


def test_fresh_run_never_auto_resumes_and_protects_existing_output(
        monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    out = tmp_path / "existing"
    _valid_checkpoint(out / "checkpoint-4", global_step=4, max_steps=4)
    config = tq.TrainingJobConfig(output_dir=str(out))
    monkeypatch.setattr(tq, "preflight", lambda cfg: {"ready": True, "problems": []})
    monkeypatch.setattr(tq, "_load_stack", lambda: pytest.fail("must refuse before loading model"))
    with pytest.raises(tq.TrainingError, match="not empty"):
        tq.run_training(config, confirm=True)
    assert (out / "checkpoint-4" / "trainer_state.json").is_file()


def test_explicit_resume_requires_incomplete_valid_checkpoint(
        monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    out = tmp_path / "resume"
    checkpoint = out / "checkpoint-2"
    _valid_checkpoint(checkpoint)
    config = tq.TrainingJobConfig(output_dir=str(out))
    monkeypatch.setattr(tq, "_load_stack", _fake_stack)
    monkeypatch.setattr(tq, "preflight", lambda cfg: {"ready": True, "problems": []})
    result = tq.run_training(config, confirm=True, resume_from_checkpoint="latest")
    assert result["resumed_from"] == str(checkpoint.resolve())
    assert _FakeTrainer.resumed_from == str(checkpoint.resolve())


def test_completed_or_incomplete_checkpoints_are_rejected_as_unresumable(
        tmp_path: Path) -> None:
    out = tmp_path / "run"
    completed = out / "checkpoint-4"
    _valid_checkpoint(completed, global_step=4, max_steps=4)
    with pytest.raises(tq.TrainingError, match="already complete"):
        tq.validate_resume_checkpoint(out, completed)
    invalid = out / "checkpoint-5"
    invalid.mkdir()
    with pytest.raises(tq.TrainingError, match="trainer_state"):
        tq.validate_resume_checkpoint(out, invalid)


def test_existing_adapter_is_never_overwritten_on_resume(
        monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    out = tmp_path / "resume"
    checkpoint = out / "checkpoint-2"
    _valid_checkpoint(checkpoint)
    (out / "adapter").mkdir()
    config = tq.TrainingJobConfig(output_dir=str(out))
    monkeypatch.setattr(tq, "preflight", lambda cfg: {"ready": True, "problems": []})
    with pytest.raises(tq.TrainingError, match="overwrite existing adapter"):
        tq.run_training(config, confirm=True, resume_from_checkpoint="latest")
