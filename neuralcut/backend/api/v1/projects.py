"""Project endpoints: create, open, save, close, list."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from neuralcut.backend.api.deps import get_container
from neuralcut.errors import NeuralCutError

router = APIRouter(prefix="/projects")


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    directory: str = Field(min_length=1)

    @field_validator("name", "directory")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ProjectOpenRequest(BaseModel):
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ProjectResponse(BaseModel):
    id: str
    name: str
    version: int
    created_at: str
    modified_at: str
    asset_count: int
    clip_count: int


def _to_response(project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        version=project.version,
        created_at=project.created_at,
        modified_at=project.modified_at,
        asset_count=len(project.assets),
        clip_count=len(project.clips),
    )


@router.get("")
def list_projects(request: Request) -> dict:
    container = get_container(request)
    return {"recent": container.project_service.recent_projects()}


@router.post("/create")
def create_project(request: Request, body: ProjectCreateRequest) -> ProjectResponse:
    container = get_container(request)
    project = container.project_service.create(body.name, body.directory)
    return _to_response(project)


@router.post("/open")
def open_project(request: Request, body: ProjectOpenRequest) -> ProjectResponse:
    container = get_container(request)
    project = container.project_service.open(body.path)
    return _to_response(project)


@router.post("/close")
def close_project(request: Request) -> dict:
    container = get_container(request)
    container.project_service.close()
    return {"status": "closed"}


@router.get("/current")
def current_project(request: Request) -> ProjectResponse | dict:
    container = get_container(request)
    try:
        project = container.project_service.get()
    except NeuralCutError:
        return {"status": "none"}
    return _to_response(project)


@router.post("/save")
def save_project(request: Request) -> dict:
    container = get_container(request)
    path = container.project_service.save()
    return {"status": "saved", "path": str(path)}


__all__ = ["router"]
