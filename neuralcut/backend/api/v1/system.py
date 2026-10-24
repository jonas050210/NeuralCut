"""System endpoints: health, diagnostics, configuration."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request

from neuralcut import __version__ as app_version
from neuralcut.backend.api.deps import get_container

router = APIRouter()


def _container(request: Request):
    return get_container(request)


@router.get("/health")
def system_health(request: Request) -> dict:
    return {"status": "ok", "service": "neuralcut", "version": app_version}


@router.get("/diagnostics")
def system_diagnostics(request: Request) -> dict:
    container = _container(request)
    settings = container.settings
    ffmpeg = settings.media.ffmpeg_path or shutil.which("ffmpeg")
    ffprobe = settings.media.probe_path or shutil.which("ffprobe")

    return {
        "service": "neuralcut",
        "version": app_version,
        "phase": "4 — Effects and Animation (Phase 3 intelligence included)",
        "platform": sys.platform,
        "python": sys.version,
        "pid": os.getpid(),
        "data_dir": str(container.context.data_dir),
        "config_file": str(container.context.config_path),
        "debug": settings.debug,
        "bind": {"host": settings.host, "port": settings.port},
        "logging": {
            "level": settings.logging.level,
            "json_logs": settings.logging.json_logs,
            "file": settings.logging.file,
        },
        "jobs": {
            "max_workers": settings.jobs.max_workers,
            "max_jobs": settings.jobs.max_jobs,
            "active": len(
                [
                    job
                    for job in container.job_manager.list()
                    if job.status.value in {"queued", "running"}
                ]
            ),
            "tracked": len(container.job_manager.list()),
        },
        "media": container.media.status(),
        "intelligence": {
            "analysis_store": str(container.analysis_service.store.directory),
            "detector": "motion-background-subtraction (CPU, no model download)",
            "transcription": "optional faster-whisper when models.enabled and installed",
            "effects": ["transform", "color", "blur", "glow", "bloom"],
        },
        "gpu": container.gpu.status(),
        "models": container.models.status(),
        "optional_tools": {
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
        },
    }


@router.get("/logs")
def system_logs(
    request: Request, lines: Annotated[int, Query(ge=1, le=5000)] = 50
) -> dict:
    container = _container(request)
    log_file = Path(
        container.settings.logging.file
        or (container.context.data_dir / "logs" / "neuralcut.log")
    )
    if not log_file.exists():
        return {"lines": [], "file": str(log_file)}
    try:
        raw = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"lines": [], "file": str(log_file), "error": str(exc)}
    all_lines = raw.splitlines()
    return {"lines": all_lines[-lines:], "file": str(log_file), "total": len(all_lines)}


@router.get("/config")
def system_config(request: Request) -> dict:
    container = _container(request)
    s = container.settings
    return {
        "app_name": s.app_name,
        "version": s.version,
        "debug": s.debug,
        "host": s.host,
        "port": s.port,
        "data_dir": str(container.context.data_dir),
        "recent_projects": container.project_service.recent,
        "logging": s.logging.model_dump(),
        "jobs": s.jobs.model_dump(),
        "media": s.media.model_dump(),
        "models": s.models.model_dump(),
        "ui": s.ui.model_dump(),
    }


__all__ = ["router"]
