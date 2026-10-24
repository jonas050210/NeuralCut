"""Phase 3/4 endpoints: analysis jobs/artifacts, retrieval, effects & keyframes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from neuralcut.backend.api.deps import get_container
from neuralcut.backend.effects.engine import PRESETS, effect_types
from neuralcut.backend.intelligence.analysis import cosine_similarity
from neuralcut.errors import NotFoundError

router = APIRouter(tags=["intelligence"])


# ---- analysis -----------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    force: bool = False


def _asset_or_404(container, asset_id: str):  # noqa: ANN001, ANN202
    project = container.project_service.get()
    asset = next((a for a in project.assets if a.id == asset_id), None)
    if asset is None:
        raise NotFoundError(f"asset not found: {asset_id}")
    return asset


@router.post("/projects/current/assets/{asset_id}/analyze")
def analyze_asset(request: Request, asset_id: str, body: AnalyzeRequest) -> dict:
    container = get_container(request)
    asset = _asset_or_404(container, asset_id)
    job = container.job_manager.submit(
        "analysis",
        name=f"Analyze {asset.name}",
        payload={"asset": asset.model_dump(mode="json"), "force": body.force},
    )
    return {"job": job.to_dict()}


@router.get("/projects/current/assets/{asset_id}/analysis")
def analysis_status(request: Request, asset_id: str) -> dict:
    container = get_container(request)
    asset = _asset_or_404(container, asset_id)
    return container.analysis_service.status(asset)


@router.get("/projects/current/assets/{asset_id}/analysis/artifacts")
def analysis_artifacts(request: Request, asset_id: str) -> dict:
    container = get_container(request)
    asset = _asset_or_404(container, asset_id)
    artifact = container.analysis_service.cached(asset)
    if artifact is None:
        raise NotFoundError(
            "no analysis artifacts for this asset yet; run analysis first",
            details={"asset_id": asset_id},
        )
    return artifact


@router.get("/projects/current/assets/{asset_id}/analysis/search")
def analysis_search(request: Request, asset_id: str, q: str = "",
                    similar_to: int | None = None) -> dict:
    container = get_container(request)
    asset = _asset_or_404(container, asset_id)
    artifact = container.analysis_service.cached(asset)
    if artifact is None:
        raise NotFoundError("no analysis artifacts for this asset yet")
    shots = artifact["shots"]
    if similar_to is not None:
        target = next((s for s in shots if s["index"] == similar_to), None)
        if target is None:
            raise NotFoundError(f"shot not found: {similar_to}")
        scored = [
            {"shot": s, "score": round(cosine_similarity(target["embedding"], s["embedding"]), 5)}
            for s in shots if s["index"] != similar_to
        ]
        scored.sort(key=lambda r: r["score"], reverse=True)
        return {"results": scored}
    tokens = [t.lower() for t in q.split() if t.strip()]
    results = [
        {"shot": s, "score": 1.0}
        for s in shots
        if not tokens or any(tok in s.get("caption", "").lower() for tok in tokens)
    ]
    return {"results": results}


# ---- effects & keyframes (Phase 4) -----------------------------------------------


class EffectCreateRequest(BaseModel):
    type: str | None = Field(default=None, max_length=50)
    preset: str | None = Field(default=None, max_length=100)
    params: dict[str, float] = Field(default_factory=dict)
    keyframes: dict[str, list[dict]] = Field(default_factory=dict)


class EffectUpdateRequest(BaseModel):
    params: dict[str, float] | None = None
    enabled: bool | None = None


class EffectMoveRequest(BaseModel):
    direction: int = Field(ge=-1, le=1)


class KeyframesRequest(BaseModel):
    property: str = Field(min_length=1, max_length=50)
    keyframes: list[dict] = Field(default_factory=list)


@router.get("/effects/types")
def get_effect_types() -> dict:
    return {"types": effect_types(), "presets": sorted(PRESETS)}


def _timeline(request: Request) -> dict:
    return get_container(request).timeline_service.timeline()


@router.post("/projects/current/clips/{clip_id}/effects")
def add_effect(request: Request, clip_id: str, body: EffectCreateRequest) -> dict:
    container = get_container(request)
    effect = container.timeline_service.add_effect(
        clip_id,
        type=body.type or "",
        params=body.params,
        keyframes=body.keyframes,
        preset=body.preset,
    )
    return {"effect": effect.model_dump(mode="json"), "timeline": _timeline(request)}


@router.patch("/projects/current/clips/{clip_id}/effects/{effect_id}")
def update_effect(request: Request, clip_id: str, effect_id: str,
                  body: EffectUpdateRequest) -> dict:
    container = get_container(request)
    effect = container.timeline_service.update_effect(
        clip_id, effect_id, params=body.params, enabled=body.enabled
    )
    return {"effect": effect.model_dump(mode="json"), "timeline": _timeline(request)}


@router.delete("/projects/current/clips/{clip_id}/effects/{effect_id}")
def remove_effect(request: Request, clip_id: str, effect_id: str) -> dict:
    container = get_container(request)
    container.timeline_service.remove_effect(clip_id, effect_id)
    return {"timeline": _timeline(request)}


@router.post("/projects/current/clips/{clip_id}/effects/{effect_id}/move")
def move_effect(request: Request, clip_id: str, effect_id: str,
                body: EffectMoveRequest) -> dict:
    container = get_container(request)
    container.timeline_service.move_effect(clip_id, effect_id, direction=body.direction)
    return {"timeline": _timeline(request)}


@router.put("/projects/current/clips/{clip_id}/effects/{effect_id}/keyframes")
def set_keyframes(request: Request, clip_id: str, effect_id: str,
                  body: KeyframesRequest) -> dict:
    container = get_container(request)
    effect = container.timeline_service.set_keyframes(
        clip_id, effect_id, property=body.property, keyframes=body.keyframes
    )
    return {"effect": effect.model_dump(mode="json"), "timeline": _timeline(request)}


__all__ = ["router"]
