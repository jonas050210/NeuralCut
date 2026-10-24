"""Dependency injection container.

Holds the shared runtime objects (settings, logger, job manager, project
service, integration adapters) and wires them into the API layer. A single
container instance is created in ``neuralcut.main`` and passed to
``build_app``.
"""

from __future__ import annotations

from neuralcut.backend.integration.evaluation import EvaluationAdapter
from neuralcut.backend.integration.gpu import GpuManagerAdapter
from neuralcut.backend.integration.media import MediaProcessorAdapter
from neuralcut.backend.integration.models import ModelManagerAdapter
from neuralcut.backend.integration.self_improvement import SelfImprovementAdapter
from neuralcut.backend.projects.service import ProjectService
from neuralcut.config import AppContext, save_settings
from neuralcut.jobs import JobManager
from neuralcut.logging import setup_logging


class Container:
    def __init__(self, context: AppContext) -> None:
        self.context = context
        self.settings = context.settings
        self.logger = setup_logging(context)

        self.job_manager = JobManager(
            max_workers=self.settings.jobs.max_workers,
            max_jobs=self.settings.jobs.max_jobs,
            result_ttl_seconds=self.settings.jobs.result_ttl_seconds,
        )
        self.project_service = ProjectService(
            recent=list(self.settings.recent_projects),
            on_recent_changed=self._persist_recent_projects,
        )

        # Integration adapters — extension points. All are disabled/no-op in
        # Phase 1; they define the contract later phases implement.
        self.media = MediaProcessorAdapter(self)
        self.models = ModelManagerAdapter(self)
        self.gpu = GpuManagerAdapter(self)
        self.evaluation = EvaluationAdapter(self)
        self.self_improvement = SelfImprovementAdapter(self)

        self.logger.info(
            "container initialized",
            extra={
                "app": self.settings.app_name,
                "version": self.settings.version,
                "data_dir": str(context.data_dir),
                "models_enabled": self.settings.models.enabled,
            },
        )

    def _persist_recent_projects(self, recent: list[str]) -> None:
        self.settings.recent_projects = list(recent)[:50]
        try:
            save_settings(self.context)
        except OSError as exc:  # pragma: no cover - depends on filesystem state
            self.logger.warning("could not persist recent projects: %s", exc)
