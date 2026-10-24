from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import httpx
import pytest

from neuralcut.backend.di import Container
from neuralcut.backend.intelligence.detection import rle_decode, rle_encode
from neuralcut.backend.projects.store import ProjectStore
from neuralcut.errors import ValidationError
from neuralcut.tests.media_helpers import (
    make_moving_car_video,
    make_scene_change_video,
    make_video,
    require_ffmpeg,
)


def test_rle_roundtrip() -> None:
    mask = [False, False, True, True, True, False, True]
    assert rle_decode(rle_encode(mask), len(mask)) == mask
    assert rle_decode(rle_encode([True, True]), 2) == [True, True]
    assert rle_decode(rle_encode([]), 0) == []


def test_moving_car_is_detected_and_tracked(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("Car", tmp_path / "proj")
    car = make_moving_car_video(tmp_path / "car.mp4", duration=3.0)
    asset = container.timeline_service.import_media(car)

    artifact = container.analysis_service.analyze(asset)

    assert artifact["version"] == 1
    assert len(artifact["tracks"]) >= 1
    track = max(artifact["tracks"], key=lambda t: t["displacement"])
    # The car crosses most of the frame over 3 seconds.
    assert track["displacement"] > 0.35
    assert track["frame_count"] >= 5
    first, last = track["frames"][0], track["frames"][-1]
    first_cx = first["bbox"][0] + first["bbox"][2] / 2
    last_cx = last["bbox"][0] + last["bbox"][2] / 2
    assert last_cx > first_cx + 0.3  # moves left -> right

    # Mask at a mid-time frame covers the car's expected location.
    mid = min(track["frames"], key=lambda f: abs(f["time_seconds"] - 1.4))
    width, height = track["mask_resolution"]
    mask = rle_decode(mid["mask_rle"], width * height)
    expected_cx = int(((20 + mid["time_seconds"] * 80 + 30) / 320) * width)
    expected_cy = int((157 / 240) * height)
    assert mask[expected_cy * width + expected_cx] is True
    assert sum(mask) > 20  # non-trivial mask area

    # Artifacts are cached and reloadable without reprocessing.
    again = container.analysis_service.analyze(asset)
    assert again["from_cache"] is True
    status = container.analysis_service.status(asset)
    assert status["status"] == "ready" and status["tracks"] >= 1


def test_cache_invalidates_when_source_changes(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("Cache", tmp_path / "proj")
    video = make_video(tmp_path / "v.mp4", duration=2.0, color="red")
    asset = container.timeline_service.import_media(video)
    first = container.analysis_service.analyze(asset)
    assert first["from_cache"] is False

    # Replace the source with different content (different fingerprint).
    make_video(video, duration=2.0, color="blue")
    second = container.analysis_service.analyze(asset)
    assert second["from_cache"] is False
    assert second["fingerprint"] != first["fingerprint"]


def test_shots_speech_and_transcript_status(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("Scenes", tmp_path / "proj")
    video = make_scene_change_video(tmp_path / "scenes.mp4")
    asset = container.timeline_service.import_media(video)

    artifact = container.analysis_service.analyze(asset)

    assert len(artifact["shots"]) >= 2  # hard cut red -> blue
    assert artifact["shots"][0]["start_seconds"] == 0.0
    assert all("embedding" in s and "caption" in s for s in artifact["shots"])
    # Continuous sine tone counts as speech/sound; no silence gaps expected.
    assert artifact["speech_segments"]
    assert artifact["speech_segments"][0]["start_seconds"] == 0.0
    # No ASR by default: honest unavailable, never fabricated words.
    assert artifact["transcript"]["status"] == "unavailable"
    assert artifact["transcript"]["segments"] == []


def test_analysis_cancellation(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("Cancel", tmp_path / "proj")
    video = make_video(tmp_path / "v.mp4", duration=2.0)
    asset = container.timeline_service.import_media(video)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ValidationError):
        container.analysis_service.analyze(asset, cancel_event=cancel)


@pytest.mark.asyncio()
async def test_analysis_via_api(client: httpx.AsyncClient, tmp_path: Path) -> None:
    require_ffmpeg()
    await client.post(
        "/api/v1/projects/create",
        json={"name": "API Intel", "directory": str(tmp_path / "proj")},
    )
    car = make_moving_car_video(tmp_path / "car.mp4")
    imported = await client.post(
        "/api/v1/projects/current/assets/import", json={"path": str(car)}
    )
    asset_id = imported.json()["asset"]["id"]

    before = await client.get(f"/api/v1/projects/current/assets/{asset_id}/analysis")
    assert before.json()["status"] == "none"

    submitted = await client.post(
        f"/api/v1/projects/current/assets/{asset_id}/analyze", json={"force": False}
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
    assert final["result"]["tracks"], "expected a moving-car track in job result"

    artifacts = await client.get(
        f"/api/v1/projects/current/assets/{asset_id}/analysis/artifacts"
    )
    assert artifacts.status_code == 200
    assert artifacts.json()["tracks"][0]["label"] == "moving_object"

    search = await client.get(
        f"/api/v1/projects/current/assets/{asset_id}/analysis/search",
        params={"q": "shot"},
    )
    assert search.json()["results"]
    similar = await client.get(
        f"/api/v1/projects/current/assets/{asset_id}/analysis/search",
        params={"similar_to": 0},
    )
    assert "results" in similar.json()

    # Analysis never edits the timeline.
    timeline = await client.get("/api/v1/projects/current/timeline")
    assert timeline.json()["clips"] == []

    # Analysis artifacts live outside the project document.
    saved = await client.post("/api/v1/projects/save")
    project = ProjectStore.load(saved.json()["path"])
    assert "tracks" not in project.model_dump()
