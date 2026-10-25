"""Dependency injection container.

Holds the shared runtime objects (settings, logger, job manager, project
service, integration adapters) and wires them into the API layer. A single
container instance is created in ``neuralcut.main`` and passed to
``build_app``.
"""

from __future__ import annotations

from neuralcut.backend.editing.service import TimelineService
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
    def __init__(self, context: AppContext, *, configure_logging: bool = True) -> None:
        self.context = context
        self.settings = context.settings
        if configure_logging:
            self.logger = setup_logging(context)
        else:
            # Isolated/secondary containers (benchmarks, tests) must never
            # close, replace, or redirect the live application's logging.
            import logging

            self.logger = logging.getLogger("neuralcut")

        self.job_manager = JobManager(
            max_workers=self.settings.jobs.max_workers,
            max_jobs=self.settings.jobs.max_jobs,
            result_ttl_seconds=self.settings.jobs.result_ttl_seconds,
        )
        self.project_service = ProjectService(
            recent=list(self.settings.recent_projects),
            on_recent_changed=self._persist_recent_projects,
        )

        # Media/editing/rendering are real Phase 2 systems; AI adapters stay
        # lazy/unavailable until their phases.
        self.media = MediaProcessorAdapter(self)
        from neuralcut.backend.rendering.ffmpeg import FFmpegRenderEngine

        self.render_engine = FFmpegRenderEngine(self.media)
        self.timeline_service = TimelineService(self.project_service, self.media)
        from neuralcut.backend.intelligence.analysis import AnalysisService, AnalysisStore

        self.analysis_service = AnalysisService(
            AnalysisStore(context.data_dir / "analysis"), self.media, self.settings
        )
        self.models = ModelManagerAdapter(self)
        from neuralcut.backend.improvement.service import ImprovementService

        self.improvement_service = ImprovementService(self)
        from neuralcut.backend.agent.service import AgentService

        self.agent_service = AgentService(self)
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
