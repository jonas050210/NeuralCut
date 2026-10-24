from __future__ import annotations

import pytest

from neuralcut.backend.di import Container
from neuralcut.errors import UnavailableError


def test_phase1_adapters_are_explicitly_unavailable(container: Container) -> None:
    assert container.media.status()["available"] is False
    assert container.models.status()["available"] is False
    assert container.evaluation.status()["available"] is False
    assert container.self_improvement.status()["available"] is False

    gpu = container.gpu.status()
    assert "gpu_detected" in gpu
    assert "does not require an NVIDIA GPU" in gpu["note"]


def test_phase1_adapter_operations_raise_unavailable(container: Container) -> None:
    with pytest.raises(UnavailableError):
        container.media.import_asset("clip.mp4")

    with pytest.raises(UnavailableError):
        container.models.load_model("model.gguf")

    with pytest.raises(UnavailableError):
        container.models.infer("prompt")

    with pytest.raises(UnavailableError):
        container.evaluation.run_suite()

    with pytest.raises(UnavailableError):
        container.self_improvement.record_feedback({})
