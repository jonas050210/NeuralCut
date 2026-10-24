"""API router assembly for v1."""

from fastapi import APIRouter

from neuralcut.backend.api.v1 import editing, jobs, projects, system

router = APIRouter(prefix="/api/v1")

router.include_router(system.router, tags=["system"])
router.include_router(projects.router, tags=["projects"])
router.include_router(jobs.router, tags=["jobs"])
router.include_router(editing.router)

__all__ = ["router"]
