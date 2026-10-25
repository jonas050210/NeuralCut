"""Phase 6 self-improvement endpoints: benchmarks, feedback, experiments,
promotion (human-gated), rollback, training preparation (dry-run only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from neuralcut.backend.api.deps import get_container

router = APIRouter(prefix="/improvement", tags=["improvement"])


class CandidateRequest(BaseModel):
    name: str = Field(default="candidate", min_length=1, max_length=120)
    models: dict[str, Any] | None = None


class ExperimentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    candidate: dict[str, Any] | None = None


class PromoteRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    spot_check_confirmed: bool = False


class FeedbackRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    plan_id: str | None = None
    instruction: str | None = None
    note: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


@router.get("/status")
def status(request: Request) -> dict:
    return get_container(request).improvement_service.status()


@router.get("/dataset")
def dataset(request: Request) -> dict:
    return get_container(request).improvement_service.dataset()


@router.post("/dataset/persist")
def persist_dataset(request: Request) -> dict:
    service = get_container(request).improvement_service
    return {"path": service.persist_dataset_manifest()}


@router.post("/benchmarks/baseline")
def run_baseline(request: Request) -> dict:
    return get_container(request).improvement_service.run_baseline()


@router.post("/benchmarks/run")
def run_benchmark(request: Request, body: CandidateRequest) -> dict:
    service = get_container(request).improvement_service
    return service.run_benchmark({"name": body.name, "models": body.models or {}})


@router.post("/experiments")
def create_experiment(request: Request, body: ExperimentRequest) -> dict:
    service = get_container(request).improvement_service
    return service.create_experiment(body.name, body.candidate or {})


@router.get("/experiments")
def list_experiments(request: Request) -> dict:
    service = get_container(request).improvement_service
    return {"experiments": service.registry.list_experiments(),
            "champion": service.registry.champion(),
            "baseline": service.registry.baseline()}


@router.post("/experiments/{experiment_id}/evaluate")
def evaluate_experiment(request: Request, experiment_id: str) -> dict:
    return get_container(request).improvement_service.evaluate_experiment(experiment_id)


@router.post("/experiments/{experiment_id}/gate-evaluate")
def gate_evaluate(request: Request, experiment_id: str) -> dict:
    return get_container(request).improvement_service.gate_evaluate_experiment(
        experiment_id)


@router.post("/experiments/{experiment_id}/promote")
def promote(request: Request, experiment_id: str, body: PromoteRequest) -> dict:
    service = get_container(request).improvement_service
    return service.promote_experiment(
        experiment_id, reviewer=body.reviewer,
        spot_check_confirmed=body.spot_check_confirmed)


@router.post("/rollback")
def rollback(request: Request) -> dict:
    return get_container(request).improvement_service.registry.rollback()


@router.get("/audit")
def audit(request: Request, limit: int = 100) -> dict:
    service = get_container(request).improvement_service
    return {"events": service.registry.audit_tail(max(1, min(limit, 1000)))}


@router.get("/feedback")
def list_feedback(request: Request, limit: int = 100) -> dict:
    service = get_container(request).improvement_service
    return {"enabled": service.feedback.enabled,
            "events": service.feedback.list(max(1, min(limit, 1000)))}


@router.post("/feedback")
def record_feedback(request: Request, body: FeedbackRequest) -> dict:
    service = get_container(request).improvement_service
    return service.record_feedback(body.model_dump())


@router.get("/feedback/export")
def export_feedback(request: Request) -> dict:
    return get_container(request).improvement_service.feedback.export()


@router.delete("/feedback/{event_id}")
def delete_feedback(request: Request, event_id: str) -> dict:
    service = get_container(request).improvement_service
    return service.feedback.delete(None if event_id == "all" else event_id)


@router.get("/training/validate-dataset")
def validate_training_dataset(request: Request) -> dict:
    return get_container(request).improvement_service.validate_training_dataset()


@router.post("/training/prepare")
def prepare_training(request: Request, body: dict[str, Any] | None = None) -> dict:
    return get_container(request).improvement_service.prepare_training(body or {})


__all__ = ["router"]
