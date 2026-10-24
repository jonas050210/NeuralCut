"""Evaluation extension point (Phase 6: self-improvement).

Deterministic graders for edit quality run in a sandbox against fixture
projects. Declared here; implemented later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralcut.backend.di import Container

from neuralcut.errors import UnavailableError


class EvaluationAdapter:
    def __init__(self, container: "Container") -> None:
        self.container = container

    def status(self) -> dict:
        return {
            "available": False,
            "reason": "evaluation harness is a Phase 6 extension point",
        }

    def run_suite(self, *args, **kwargs):  # noqa: ARG002
        raise UnavailableError(
            "evaluation suite is not implemented in Phase 1",
            details={"feature": "evaluation.run_suite", "phase": 6},
        )
