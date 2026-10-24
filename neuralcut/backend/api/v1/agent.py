"""Phase 5 agent endpoints: chat -> plan -> approve/reject/undo, audit."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from neuralcut.backend.agent.tools import tool_schemas
from neuralcut.backend.api.deps import get_container

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.get("/status")
def agent_status(request: Request) -> dict:
    container = get_container(request)
    return {
        "router": container.agent_service.router.status(),
        "tools": tool_schemas(),
        "approval_policy": (
            "read-only plans execute immediately; edit/external plans wait "
            "for explicit approval; every applied edit is undoable"
        ),
    }


@router.post("/chat")
def agent_chat(request: Request, body: ChatRequest) -> dict:
    container = get_container(request)
    return container.agent_service.chat(body.message)


@router.get("/plans")
def list_plans(request: Request) -> dict:
    container = get_container(request)
    return {"plans": container.agent_service.list_plans()}


@router.get("/plans/{plan_id}")
def get_plan(request: Request, plan_id: str) -> dict:
    container = get_container(request)
    return container.agent_service.get_plan(plan_id)


@router.post("/plans/{plan_id}/approve")
def approve_plan(request: Request, plan_id: str) -> dict:
    container = get_container(request)
    return container.agent_service.approve(plan_id)


@router.post("/plans/{plan_id}/reject")
def reject_plan(request: Request, plan_id: str) -> dict:
    container = get_container(request)
    return container.agent_service.reject(plan_id)


@router.post("/plans/{plan_id}/undo")
def undo_plan(request: Request, plan_id: str) -> dict:
    container = get_container(request)
    return container.agent_service.undo_plan(plan_id)


@router.get("/audit")
def audit(request: Request, limit: int = 100) -> dict:
    container = get_container(request)
    return {"events": container.agent_service.audit_tail(max(1, min(limit, 1000)))}


__all__ = ["router"]
