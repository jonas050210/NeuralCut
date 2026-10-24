"""Background job endpoints: list, get, cancel."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from neuralcut.backend.api.deps import get_container
from neuralcut.errors import NotFoundError
from neuralcut.jobs import JobStatus

router = APIRouter(prefix="/jobs")


class JobSubmitRequest(BaseModel):
    type: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=200)
    payload: dict = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    type: str
    name: str
    status: str
    progress: float
    progress_message: str
    result: object | None = None
    error: str | None = None
    details: dict = {}
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


def _to_response(job) -> JobResponse:
    return JobResponse(**job.to_dict())


@router.get("")
def list_jobs(
    request: Request, status: Annotated[JobStatus | None, Query()] = None
) -> dict:
    container = get_container(request)
    jobs = container.job_manager.list(status=status)
    return {"jobs": [_to_response(j).model_dump() for j in jobs]}


@router.post("")
def submit_job(request: Request, body: JobSubmitRequest) -> JobResponse:
    container = get_container(request)
    job = container.job_manager.submit(
        body.type, name=body.name, payload=body.payload
    )
    return _to_response(job)


@router.get("/{job_id}")
def get_job(request: Request, job_id: str) -> JobResponse:
    container = get_container(request)
    job = container.job_manager.get(job_id)
    if job is None:
        raise NotFoundError(f"job not found: {job_id}")
    return _to_response(job)


@router.post("/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> JobResponse:
    container = get_container(request)
    job = container.job_manager.cancel(job_id)
    return _to_response(job)


__all__ = ["router"]
