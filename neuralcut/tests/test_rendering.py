from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import httpx
import pytest

from neuralcut.backend.di import Container
from neuralcut.backend.projects.model import ExportSettings
from neuralcut.backend.rendering.ffmpeg import RenderCancelled
from neuralcut.errors import ValidationError
from neuralcut.tests.media_helpers import make_video, require_ffmpeg


@pytest.fixture()
def rendered_project(container: Container, tmp_path: Path):
    require_ffmpeg()
    container.project_service.create("Render Test", tmp_path / "proj")
    service = container.timeline_service
    red = make_video(tmp_path / "red.mp4", duration=3.0, color="red")
    blue = make_video(tmp_path / "blue.mp4", duration=3.0, color="blue", with_audio=False)
    asset_red = service.import_media(red)
    asset_blue = service.import_media(blue)
    # Clip 1: 2s of red at t=0. Gap 0.5s. Clip 2: 1.5s of blue (no audio track).
    service.add_clip(asset_red.id, source_start_seconds=0, source_end_seconds=2)
    service.add_clip(
        asset_blue.id,
        timeline_start_seconds=2.5,
        source_start_seconds=0.5,
        source_end_seconds=2.0,
    )
    return container, tmp_path


def test_render_export_duration_and_probe(rendered_project) -> None:  # noqa: ANN001
    container, tmp_path = rendered_project
    project = container.project_service.get()
    output = tmp_path / "out" / "export.mp4"
    result = container.render_engine.render(
        project,
        output,
        ExportSettings(width=320, height=240, fps=10),
        work_dir=tmp_path / "work",
    )
    assert output.is_file() and output.stat().st_size > 0
    assert result["segments"] == 3  # clip, gap, clip
    assert result["expected_duration_seconds"] == pytest.approx(4.0)
    info = container.media.probe(output)
    assert info.has_video and info.has_audio
    assert info.duration_seconds == pytest.approx(4.0, abs=1.0)


def test_render_empty_and_missing_media_errors(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("Empty", tmp_path / "proj")
    project = container.project_service.get()
    with pytest.raises(ValidationError):
        container.render_engine.render(project, tmp_path / "x.mp4")

    video = make_video(tmp_path / "gone.mp4", duration=2.0)
    service = container.timeline_service
    asset = service.import_media(video)
    service.add_clip(asset.id)
    video.unlink()
    with pytest.raises(ValidationError) as exc:
        container.render_engine.render(container.project_service.get(), tmp_path / "x.mp4")
    assert "missing" in exc.value.message


def test_render_rejects_non_mp4_and_overlap(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("BadOut", tmp_path / "proj")
    video = make_video(tmp_path / "a.mp4", duration=2.0)
    service = container.timeline_service
    asset = service.import_media(video)
    service.add_clip(asset.id)
    with pytest.raises(ValidationError):
        container.render_engine.render(container.project_service.get(), tmp_path / "x.mkv")


def test_render_cancellation(rendered_project) -> None:  # noqa: ANN001
    container, tmp_path = rendered_project
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RenderCancelled):
        container.render_engine.render(
            container.project_service.get(),
            tmp_path / "cancelled.mp4",
            ExportSettings(width=320, height=240, fps=10),
            cancel_event=cancel,
            work_dir=tmp_path / "work",
        )
    assert not (tmp_path / "cancelled.mp4").exists()


@pytest.mark.asyncio()
async def test_editing_and_render_via_api(client: httpx.AsyncClient, tmp_path: Path) -> None:
    require_ffmpeg()
    created = await client.post(
        "/api/v1/projects/create",
        json={"name": "API Edit", "directory": str(tmp_path / "proj")},
    )
    assert created.status_code == 200, created.text

    empty = await client.get("/api/v1/projects/current/timeline")
    assert empty.status_code == 200
    assert empty.json()["clips"] == []

    video = make_video(tmp_path / "api.mp4", duration=3.0, color="green")
    imported = await client.post(
        "/api/v1/projects/current/assets/import", json={"path": str(video)}
    )
    assert imported.status_code == 200, imported.text
    asset_id = imported.json()["asset"]["id"]

    added = await client.post(
        "/api/v1/projects/current/clips",
        json={"asset_id": asset_id, "source_start_seconds": 0, "source_end_seconds": 2},
    )
    assert added.status_code == 200, added.text
    clip_id = added.json()["clip"]["id"]

    split = await client.post(
        f"/api/v1/projects/current/clips/{clip_id}/split",
        json={"at_timeline_seconds": 1.0},
    )
    assert split.status_code == 200, split.text
    assert len(split.json()["timeline"]["clips"]) == 2

    undone = await client.post("/api/v1/projects/current/undo")
    assert len(undone.json()["timeline"]["clips"]) == 1
    redone = await client.post("/api/v1/projects/current/redo")
    assert len(redone.json()["timeline"]["clips"]) == 2

    # Source streaming supports range requests (preview seeking).
    ranged = await client.get(
        f"/api/v1/media/assets/{asset_id}/content", headers={"Range": "bytes=0-99"}
    )
    assert ranged.status_code == 206
    assert ranged.headers["content-range"].startswith("bytes 0-99/")

    saved = await client.post("/api/v1/projects/save")
    assert saved.status_code == 200

    output = tmp_path / "api-export.mp4"
    submitted = await client.post(
        "/api/v1/projects/current/render",
        json={"output_path": str(output), "width": 320, "height": 240, "fps": 10},
    )
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job"]["id"]

    final = None
    for _ in range(200):
        resp = await client.get(f"/api/v1/jobs/{job_id}")
        if resp.json()["status"] in {"completed", "failed", "cancelled"}:
            final = resp.json()
            break
        await asyncio.sleep(0.1)
    assert final is not None and final["status"] == "completed", final
    assert final["result"]["actual_duration_seconds"] == pytest.approx(2.0, abs=1.0)
    assert output.is_file()


@pytest.mark.asyncio()
async def test_editing_api_errors_without_project(client: httpx.AsyncClient) -> None:
    timeline = await client.get("/api/v1/projects/current/timeline")
    assert timeline.status_code == 404

    imported = await client.post(
        "/api/v1/projects/current/assets/import", json={"path": "/nope.mp4"}
    )
    assert imported.status_code == 404
