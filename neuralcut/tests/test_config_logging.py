from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from neuralcut.config import NeuralCutSettings, load_settings, save_settings
from neuralcut.logging import CorrelationScope, setup_logging


def test_settings_defaults_are_local_and_models_disabled() -> None:
    settings = NeuralCutSettings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.models.enabled is False
    assert settings.logging.json_logs is True


def test_settings_validation_rejects_bad_port_and_log_level() -> None:
    with pytest.raises(ValidationError):
        NeuralCutSettings(port=80)

    with pytest.raises(ValidationError):
        NeuralCutSettings(logging={"level": "NOPE"})


def test_json_config_save_and_reload(tmp_path: Path) -> None:
    ctx = load_settings(data_dir=tmp_path)
    ctx.settings.port = 9876
    ctx.settings.logging.level = "DEBUG"
    ctx.settings.recent_projects = ["/tmp/example.neuralcut"]

    path = save_settings(ctx)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["port"] == 9876

    reloaded = load_settings(data_dir=tmp_path)
    assert reloaded.settings.port == 9876
    assert reloaded.settings.logging.level == "DEBUG"
    assert reloaded.settings.recent_projects == ["/tmp/example.neuralcut"]


def test_environment_overrides_json_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = load_settings(data_dir=tmp_path)
    ctx.settings.port = 9001
    save_settings(ctx)

    monkeypatch.setenv("NEURALCUT_PORT", "9002")
    monkeypatch.setenv("NEURALCUT_LOGGING__LEVEL", "WARNING")
    reloaded = load_settings(data_dir=tmp_path)

    assert reloaded.settings.port == 9002
    assert reloaded.settings.logging.level == "WARNING"


def test_explicit_config_file_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "custom.json"
    cfg.write_text(json.dumps({"port": 9911}), encoding="utf-8")
    monkeypatch.setenv("NEURALCUT_CONFIG_FILE", str(cfg))

    ctx = load_settings(data_dir=tmp_path / "data")
    assert ctx.config_path == cfg
    assert ctx.settings.port == 9911


def test_json_logging_writes_structured_record_with_correlation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEURALCUT_LOGGING__STDOUT", "false")
    ctx = load_settings(data_dir=tmp_path)
    setup_logging(ctx)

    with CorrelationScope("test-cid-123"):
        logging.getLogger("neuralcut.test").info(
            "hello from test", extra={"answer": 42}
        )

    for handler in logging.getLogger().handlers:
        handler.flush()

    log_file = tmp_path / "logs" / "neuralcut.log"
    lines = log_file.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    match = [r for r in records if r.get("msg") == "hello from test"]
    assert match
    assert match[0]["cid"] == "test-cid-123"
    assert match[0]["answer"] == 42
    assert match[0]["level"] == "INFO"


def test_plain_logging_mode_is_supported(tmp_path: Path) -> None:
    ctx = load_settings(data_dir=tmp_path)
    ctx.settings.logging.json_logs = False
    ctx.settings.logging.stdout = False
    setup_logging(ctx)
    logging.getLogger("neuralcut.test").info("plain mode message")

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = (tmp_path / "logs" / "neuralcut.log").read_text(encoding="utf-8")
    assert "plain mode message" in content
