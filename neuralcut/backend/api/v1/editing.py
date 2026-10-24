"""Editing endpoints: media import, timeline clips, undo/redo, render, streaming."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from neuralcut.backend.api.deps import get_container
from neuralcut.backend.projects.model import ExportSettings
from neuralcut.errors import NotFoundError, ValidationError

router = APIRouter(tags=["editing"])


# ---- request models ----------------------------------------------------------


class ImportRequest(BaseModel):
    path: str = Field(min_length=1)


class ClipCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    track: int = Field(default=0, ge=0)
    timeline_start_seconds: float | None = Field(default=None, ge=0)
    source_start_seconds: float = Field(default=0.0, ge=0)
    source_end_seconds: float | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, max_length=200)


class ClipUpdateRequest(BaseModel):
    timeline_start_seconds: float | None = Field(default=None, ge=0)
    track: int | None = Field(default=None, ge=0)
    source_start_seconds: float | None = Field(default=None, ge=0)
    source_end_seconds: float | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, max_length=200)


class ClipSplitRequest(BaseModel):
    at_timeline_seconds: float = Field(ge=0)


class RenderRequest(BaseModel):
    output_path: str = Field(min_length=1)
    width: int | None = Field(default=None, ge=16, le=7680)
    height: int | None = Field(default=None, ge=16, le=4320)
    fps: float | None = Field(default=None, gt=0, le=240)
    crf: int | None = Field(default=None, ge=0, le=51)


# ---- timeline -----------------------------------------------------------------


def _timeline_response(request: Request) -> dict:
    return get_container(request).timeline_service.timeline()


@router.get("/projects/current/timeline")
def get_timeline(request: Request) -> dict:
    return _timeline_response(request)


@router.post("/projects/current/assets/import")
def import_asset(request: Request, body: ImportRequest) -> dict:
    container = get_container(request)
    asset = container.timeline_service.import_media(body.path)
    return {"asset": asset.model_dump(mode="json"), "timeline": _timeline_response(request)}


@router.delete("/projects/current/assets/{asset_id}")
def remove_asset(request: Request, asset_id: str) -> dict:
    container = get_container(request)
    container.timeline_service.remove_asset(asset_id)
    return {"timeline": _timeline_response(request)}


@router.post("/projects/current/clips")
def add_clip(request: Request, body: ClipCreateRequest) -> dict:
    container = get_container(request)
    clip = container.timeline_service.add_clip(
        body.asset_id,
        track=body.track,
        timeline_start_seconds=body.timeline_start_seconds,
        source_start_seconds=body.source_start_seconds,
        source_end_seconds=body.source_end_seconds,
        name=body.name,
    )
    return {"clip": clip.model_dump(mode="json"), "timeline": _timeline_response(request)}


@router.patch("/projects/current/clips/{clip_id}")
def update_clip(request: Request, clip_id: str, body: ClipUpdateRequest) -> dict:
    container = get_container(request)
    service = container.timeline_service
    current = service.timeline()
    existing = next((c for c in current["clips"] if c["id"] == clip_id), None)
    if existing is None:
        raise NotFoundError(f"clip not found: {clip_id}")
    if (
        body.source_start_seconds is None
        and body.source_end_seconds is None
        and body.timeline_start_seconds is None
        and body.track is None
        and body.name is None
    ):
        raise ValidationError("no editable fields provided")
    # One PATCH is one undo step: apply the combined edit through the trim
    # path when source fields change, otherwise through the move path.
    if body.source_start_seconds is not None or body.source_end_seconds is not None or (
        body.name is not None and body.track is None
    ):
        clip = service.trim_clip(
            clip_id,
            source_start_seconds=body.source_start_seconds,
            source_end_seconds=body.source_end_seconds,
            timeline_start_seconds=body.timeline_start_seconds,
            name=body.name,
        )
        if body.track is not None and body.track != clip.track:
            clip = service.move_clip(
                clip_id, timeline_start_seconds=clip.timeline_start_seconds, track=body.track
            )
    else:
        clip = service.move_clip(
            clip_id,
            timeline_start_seconds=(
                body.timeline_start_seconds
                if body.timeline_start_seconds is not None
                else existing["timeline_start_seconds"]
            ),
            track=body.track,
        )
        if body.name is not None:
            clip = service.trim_clip(clip_id, name=body.name)
    return {"clip": clip.model_dump(mode="json"), "timeline": _timeline_response(request)}


@router.post("/projects/current/clips/{clip_id}/split")
def split_clip(request: Request, clip_id: str, body: ClipSplitRequest) -> dict:
    container = get_container(request)
    clips = container.timeline_service.split_clip(
        clip_id, at_timeline_seconds=body.at_timeline_seconds
    )
    return {
        "clips": [c.model_dump(mode="json") for c in clips],
        "timeline": _timeline_response(request),
    }


@router.delete("/projects/current/clips/{clip_id}")
def remove_clip(request: Request, clip_id: str) -> dict:
    container = get_container(request)
    container.timeline_service.remove_clip(clip_id)
    return {"timeline": _timeline_response(request)}


@router.post("/projects/current/undo")
def undo(request: Request) -> dict:
    get_container(request).timeline_service.undo()
    return {"timeline": _timeline_response(request)}


@router.post("/projects/current/redo")
def redo(request: Request) -> dict:
    get_container(request).timeline_service.redo()
    return {"timeline": _timeline_response(request)}


# ---- rendering -------------------------------------------------------------------


@router.post("/projects/current/render")
def start_render(request: Request, body: RenderRequest) -> dict:
    container = get_container(request)
    project = container.project_service.get()
    settings = project.export_settings.model_copy(
        update={
            key: value
            for key, value in {
                "width": body.width,
                "height": body.height,
                "fps": body.fps,
                "crf": body.crf,
            }.items()
            if value is not None
        }
    )
    settings = ExportSettings.model_validate(settings.model_dump())
    job = container.job_manager.submit(
        "render",
        name=f"Export {Path(body.output_path).name}",
        payload={
            "project": project.model_dump(mode="json"),
            "output_path": body.output_path,
            "settings": settings.model_dump(mode="json"),
        },
    )
    return {"job": job.to_dict()}


# ---- media streaming (source/preview playback) -------------------------------------

_CHUNK = 1024 * 256


@router.get("/media/assets/{asset_id}/content")
def stream_asset(request: Request, asset_id: str):
    container = get_container(request)
    project = container.project_service.get()
    asset = next((a for a in project.assets if a.id == asset_id), None)
    if asset is None:
        raise NotFoundError(f"asset not found: {asset_id}")
    path = Path(asset.path)
    if not path.is_file():
        raise NotFoundError(
            f"source media file is missing: {asset.path}", details={"asset_id": asset_id}
        )
    size = path.stat().st_size
    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = 200
    if range_header and range_header.startswith("bytes="):
        try:
            raw_start, _, raw_end = range_header[6:].partition("-")
            if raw_start:
                start = int(raw_start)
            if raw_end:
                end = int(raw_end)
            end = min(end, size - 1)
            if start > end or start >= size:
                raise ValueError
            status_code = 206
        except ValueError:
            raise ValidationError(f"invalid Range header: {range_header}") from None
    length = end - start + 1

    def iterator():
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": f'inline; filename="{path.name}"',
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    media_type = "video/mp4" if path.suffix.lower() in {".mp4", ".m4v"} else None
    return StreamingResponse(
        iterator(), status_code=status_code, headers=headers, media_type=media_type
    )


__all__ = ["router"]
