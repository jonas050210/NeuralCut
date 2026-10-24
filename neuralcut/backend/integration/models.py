"""AI model management extension point (Phase 3+).

Models are optional: disabled by default, no downloads, no GPU init at
startup. Later phases load quantized GGUF orchestrator/specialist models via
llama.cpp etc., one heavy model family resident at a time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralcut.backend.di import Container

from neuralcut.errors import UnavailableError


class ModelManagerAdapter:
    """No-op in Phase 1."""

    def __init__(self, container: "Container") -> None:
        self.container = container
        self.enabled = container.settings.models.enabled

    def status(self) -> dict:
        return {
            "available": False,
            "enabled": self.enabled,
            "reason": "AI models are optional and disabled in Phase 1",
            "orchestrator_path": self.container.settings.models.orchestrator_path,
        }

    def load_model(self, *args, **kwargs):  # noqa: ARG002
        raise UnavailableError(
            "model loading is not implemented in Phase 1",
            details={"feature": "models.load", "phase": 3},
        )

    def infer(self, *args, **kwargs):  # noqa: ARG002
        raise UnavailableError(
            "model inference is not implemented in Phase 1",
            details={"feature": "models.infer", "phase": 3},
        )
