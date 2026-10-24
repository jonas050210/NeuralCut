"""Self-improvement extension point (Phase 6).

Feedback collection, preference data (KTO/DPO), adapter registry, rollback.
Declared here; no training runs in Phase 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralcut.backend.di import Container

from neuralcut.errors import UnavailableError


class SelfImprovementAdapter:
    def __init__(self, container: "Container") -> None:
        self.container = container

    def status(self) -> dict:
        return {
            "available": False,
            "reason": "self-improvement pipeline is a Phase 6 extension point",
        }

    def record_feedback(self, *args, **kwargs):  # noqa: ARG002
        raise UnavailableError(
            "feedback recording is not implemented in Phase 1",
            details={"feature": "self_improvement.record_feedback", "phase": 6},
        )
