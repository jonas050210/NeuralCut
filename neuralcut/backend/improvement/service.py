"""ImprovementService: facade used by the API (benchmarks, feedback,
experiments, promotion, training preparation)."""

from __future__ import annotations

from typing import Any

from neuralcut.backend.improvement.benchmark import BenchmarkRunner
from neuralcut.backend.improvement.datasets import build_manifest, save_manifest
from neuralcut.backend.improvement.feedback import FeedbackStore
from neuralcut.backend.improvement.registry import ImprovementRegistry
from neuralcut.backend.improvement.training import (
    TrainingPreparer,
    validate_dataset_for_training,
)
from neuralcut.errors import ValidationError


class ImprovementService:
    def __init__(self, container) -> None:  # noqa: ANN001
        self._container = container
        self.runner = BenchmarkRunner(container)
        self.registry = ImprovementRegistry(container)
        self.feedback = FeedbackStore(
            container.context.data_dir,
            enabled=lambda: container.settings.improvement.feedback_enabled)
        self.training = TrainingPreparer(container)

    def status(self) -> dict[str, Any]:
        settings = self._container.settings.improvement
        return {
            "feedback_enabled": settings.feedback_enabled,
            "feedback_count": len(self.feedback.list(limit=100000)),
            "champion": self.registry.champion(),
            "has_baseline": self.registry.baseline() is not None,
            "auto_promotion": False,
            "training": "prepared (dry-run specs only); never executed in-app",
            "isolation": "benchmarks use temporary data dirs + synthetic fixtures",
        }

    # ---- datasets / benchmarks ------------------------------------------

    def dataset(self) -> dict[str, Any]:
        return build_manifest()

    def run_baseline(self) -> dict[str, Any]:
        report = self.runner.run({"name": "incumbent-builtin", "planner": "builtin"})
        return self.registry.set_baseline(report)

    def run_benchmark(self, candidate: dict[str, Any] | None = None,
                      experiment_id: str | None = None) -> dict[str, Any]:
        report = self.runner.run(candidate)
        if experiment_id:
            self.registry.record_evaluation(experiment_id, report)
        return report

    # ---- experiments ------------------------------------------------------

    def create_experiment(self, name: str,
                          candidate: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.registry.create_experiment(name, candidate or {})

    def evaluate_experiment(self, experiment_id: str) -> dict[str, Any]:
        exp = self.registry.get_experiment(experiment_id)
        report = self.runner.run(exp["candidate"])
        return self.registry.record_evaluation(experiment_id, report)

    # ---- training -----------------------------------------------------------

    def validate_training_dataset(self) -> dict[str, Any]:
        return validate_dataset_for_training()

    def prepare_training(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.training.prepare(config)

    def persist_dataset_manifest(self) -> str:
        return str(save_manifest(self._container.context.data_dir))

    # ---- feedback ---------------------------------------------------------------

    def record_feedback(self, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise ValidationError("feedback event must be an object")
        return self.feedback.record(event)
