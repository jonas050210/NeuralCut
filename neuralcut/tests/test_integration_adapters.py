from __future__ import annotations

import pytest

from neuralcut.backend.di import Container
from neuralcut.errors import UnavailableError, ValidationError


def test_ai_adapters_remain_unavailable_in_phase2(container: Container) -> None:
    assert container.models.status()["available"] is False
    assert container.evaluation.status()["available"] is False
    assert container.self_improvement.status()["available"] is False

    gpu = container.gpu.status()
    assert "gpu_detected" in gpu
    assert "does not require an NVIDIA GPU" in gpu["note"]


def test_media_adapter_is_real_in_phase2(container: Container) -> None:
    status = container.media.status()
    assert "ffmpeg" in status
    assert ".mp4" in status["supported_extensions"]
    # Probing a missing file is a validation error, not "unimplemented".
    with pytest.raises(ValidationError):
        container.media.probe("/definitely/missing/clip.mp4")


def test_phase2_adapter_operations_raise_unavailable(container: Container) -> None:
    with pytest.raises(UnavailableError):
        container.models.load_model("model.gguf")

    with pytest.raises(UnavailableError):
        container.models.infer("prompt")

    with pytest.raises(UnavailableError):
        container.evaluation.run_suite()

    with pytest.raises(UnavailableError):
        container.self_improvement.record_feedback({})
