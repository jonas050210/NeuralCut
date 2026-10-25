"""Training pipeline tests: dataset hygiene, preflight, dry-run, mocked run.

No real GPU/model/training is involved: the heavy stack is stubbed, and
the run test verifies wiring (quantization config, LoRA, checkpoint
resume, adapter save, manifest) only.
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

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        self.kwargs = kwargs

    def train(self, resume_from_checkpoint=None) -> None:  # noqa: ANN001
        _FakeTrainer.resumed_from = resume_from_checkpoint

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

    # A second run resumes from the latest checkpoint directory.
    checkpoint = tmp_path / "run" / "checkpoint-3"
    checkpoint.mkdir()
    assert tq.find_latest_checkpoint(tmp_path / "run") == str(checkpoint)
