from __future__ import annotations

import json
from pathlib import Path

import pytest

from neuralcut.backend.di import Container
from neuralcut.backend.effects.engine import (
    evaluate_keyframes,
    validate_effect,
    value_at,
)
from neuralcut.backend.projects.model import ClipEffect, EffectKeyframe, Project
from neuralcut.backend.projects.store import ProjectStore
from neuralcut.errors import ValidationError
from neuralcut.tests.media_helpers import (
    frame_mean_gray,
    make_video,
    pixel_rgb,
    require_ffmpeg,
)

SETTINGS = {"width": 320, "height": 240, "fps": 10}


def _project_with_clip(container: Container, tmp_path: Path, *, color: str = "gray"):
    require_ffmpeg()
    container.project_service.create("FX", tmp_path / "proj")
    video = make_video(tmp_path / "v.mp4", duration=3.0, color=color)
    asset = container.timeline_service.import_media(video)
    clip = container.timeline_service.add_clip(asset.id)
    return asset, clip


def test_keyframe_evaluation_linear_and_hold() -> None:
    frames = [
        EffectKeyframe(time_seconds=0.0, value=0.0),
        EffectKeyframe(time_seconds=2.0, value=10.0),
    ]
    assert evaluate_keyframes(frames, 1.0, 99.0) == 5.0
    assert evaluate_keyframes(frames, -1.0, 99.0) == 0.0
    assert evaluate_keyframes(frames, 5.0, 99.0) == 10.0
    hold = [
        EffectKeyframe(time_seconds=0.0, value=1.0),
        EffectKeyframe(time_seconds=2.0, value=3.0, interpolation="hold"),
    ]
    assert evaluate_keyframes(hold, 1.5, 0.0) == 1.0
    effect = ClipEffect(id="e1", type="transform", params={"opacity": 0.2},
                        keyframes={"opacity": frames})
    assert value_at(effect, "opacity", 1.0) == 5.0  # keyframes override the base value


def test_effect_validation_errors() -> None:
    with pytest.raises(ValidationError):
        validate_effect("does-not-exist", {})
    with pytest.raises(ValidationError):
        validate_effect("glow", {"strength": 5.0})
    with pytest.raises(ValidationError):
        validate_effect("color", {"hue": 1.0})
    with pytest.raises(ValidationError):
        validate_effect("transform", {}, {"opacity": [
            EffectKeyframe(time_seconds=2.0, value=0.5),
            EffectKeyframe(time_seconds=1.0, value=0.5),
        ]})


def test_effect_crud_presets_reorder_and_undo(container: Container, tmp_path: Path) -> None:
    _asset, clip = _project_with_clip(container, tmp_path)
    service = container.timeline_service

    glow = service.add_effect(clip.id, type="glow", params={"strength": 0.4})
    color = service.add_effect(clip.id, type="color", params={"brightness": 0.2})
    chain = service.timeline()["clips"][0]["effects"]
    assert [e["type"] for e in chain] == ["glow", "color"]

    service.move_effect(clip.id, color.id, direction=-1)
    chain = service.timeline()["clips"][0]["effects"]
    assert [e["type"] for e in chain] == ["color", "glow"]

    updated = service.update_effect(clip.id, glow.id, enabled=False)
    assert updated.enabled is False
    with pytest.raises(ValidationError):
        service.update_effect(clip.id, glow.id, params={"strength": 9.0})
    with pytest.raises(ValidationError):
        service.add_effect(clip.id, type="sparkles")

    preset = service.add_effect(clip.id, preset="fade-in", type="")
    assert preset.type == "transform"
    assert preset.keyframes["opacity"][0].value == 0.0

    service.set_keyframes(
        clip.id, glow.id, property="strength",
        keyframes=[{"time_seconds": 0.0, "value": 0.1},
                   {"time_seconds": 2.0, "value": 0.9}],
    )
    effect = next(e for e in service.timeline()["clips"][0]["effects"] if e["id"] == glow.id)
    assert effect["keyframes"]["strength"][1]["value"] == 0.9
    with pytest.raises(ValidationError):
        service.set_keyframes(
            clip.id, glow.id, property="strength",
            keyframes=[{"time_seconds": 0.0, "value": 42.0}],
        )

    # Persistence: exact effect state survives save/load.
    path = container.project_service.current_path()
    container.project_service.save()
    loaded = ProjectStore.load(path)
    assert loaded.version == 3
    saved_effects = loaded.clips[0].effects
    assert [e.type for e in saved_effects] == ["color", "glow", "transform"]
    assert saved_effects[1].keyframes["strength"][1].value == 0.9

    # Undo removes the keyframe edit; redo restores it.
    service.undo()
    undone = next(
        e for e in service.timeline()["clips"][0]["effects"] if e["id"] == glow.id
    )
    assert "strength" not in undone["keyframes"]
    service.redo()
    redone = next(
        e for e in service.timeline()["clips"][0]["effects"] if e["id"] == glow.id
    )
    assert redone["keyframes"]["strength"][1]["value"] == 0.9

    service.remove_effect(clip.id, preset.id)
    assert all(e["id"] != preset.id for e in service.timeline()["clips"][0]["effects"])


def test_v2_project_migrates_to_v3(tmp_path: Path) -> None:
    v2 = {
        "version": 2, "id": "p1", "name": "V2",
        "assets": [{"id": "a1", "name": "c.mp4", "path": "/tmp/c.mp4"}],
        "clips": [{
            "id": "c1", "asset_id": "a1", "name": "clip", "track": 0,
            "timeline_start_seconds": 0.0, "source_start_seconds": 0.0,
            "source_end_seconds": 2.0,
        }],
    }
    path = tmp_path / "v2.neuralcut"
    path.write_text(json.dumps(v2), encoding="utf-8")
    loaded = ProjectStore.load(path)
    assert loaded.version == 3
    assert loaded.clips[0].effects == []
    assert isinstance(loaded, Project)


def _render(container: Container, tmp_path: Path, name: str):  # noqa: ANN001, ANN202
    from neuralcut.backend.projects.model import ExportSettings

    output = tmp_path / name
    result = container.render_engine.render(
        container.project_service.get(), output,
        ExportSettings(**SETTINGS), work_dir=tmp_path / "work",
    )
    assert output.is_file()
    return output, result


def test_color_effect_changes_rendered_pixels(container: Container, tmp_path: Path) -> None:
    _asset, clip = _project_with_clip(container, tmp_path)
    plain, plain_result = _render(container, tmp_path, "plain.mp4")
    assert plain_result["composited"] is False

    container.timeline_service.add_effect(clip.id, type="color", params={"brightness": 0.35})
    bright, result = _render(container, tmp_path, "bright.mp4")
    assert result["composited"] is True
    assert frame_mean_gray(bright) > frame_mean_gray(plain) + 10


def test_glow_and_bloom_render(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("Glow", tmp_path / "proj")
    # Small bright square on black: glow must spread light beyond the square.
    import subprocess

    from neuralcut.tests.media_helpers import ffmpeg_exe

    exe = ffmpeg_exe()
    src = tmp_path / "spot.mp4"
    proc = subprocess.run(
        [exe, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=10:d=2",
         "-vf", "drawbox=x=140:y=100:w=40:h=40:color=white:t=fill",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    asset = container.timeline_service.import_media(src)
    clip = container.timeline_service.add_clip(asset.id)

    plain, _ = _render(container, tmp_path, "spot-plain.mp4")
    container.timeline_service.add_effect(
        clip.id, type="glow", params={"strength": 0.9, "radius": 25.0}
    )
    glowed, _ = _render(container, tmp_path, "spot-glow.mp4")
    # A point outside the square is brighter with glow than without.
    outside = (0.32, 0.42)
    assert pixel_rgb(glowed, at_seconds=0.5, x_fraction=outside[0], y_fraction=outside[1])[0] > \
        pixel_rgb(plain, at_seconds=0.5, x_fraction=outside[0], y_fraction=outside[1])[0]

    container.timeline_service.add_effect(
        clip.id, type="bloom", params={"strength": 0.7, "radius": 20.0, "threshold": 0.5}
    )
    bloomed, result = _render(container, tmp_path, "spot-bloom.mp4")
    assert result["actual_duration_seconds"] == pytest.approx(2.0, abs=1.0)


def test_compositing_overlay_and_opacity_keyframes(
    container: Container, tmp_path: Path
) -> None:
    require_ffmpeg()
    container.project_service.create("Comp", tmp_path / "proj")
    service = container.timeline_service
    blue = make_video(tmp_path / "blue.mp4", duration=2.0, color="blue")
    red = make_video(tmp_path / "red.mp4", duration=2.0, color="red")
    blue_asset = service.import_media(blue)
    red_asset = service.import_media(red)
    service.add_clip(blue_asset.id, track=0)
    top = service.add_clip(red_asset.id, track=1, timeline_start_seconds=0.0)
    service.add_effect(top.id, type="transform", params={"scale": 0.5, "opacity": 1.0})

    output, result = _render(container, tmp_path, "comp.mp4")
    assert result["composited"] is True
    # Center is covered by the scaled red top clip; corner stays blue.
    center = pixel_rgb(output, at_seconds=0.5, x_fraction=0.5, y_fraction=0.5)
    corner = pixel_rgb(output, at_seconds=0.5, x_fraction=0.03, y_fraction=0.03)
    assert center[0] > 150 and center[2] < 100
    assert corner[2] > 120 and corner[0] < 100

    # Half opacity blends toward blue at the center.
    effects = service.timeline()["clips"]
    top_now = next(c for c in effects if c["id"] == top.id)
    effect_id = top_now["effects"][0]["id"]
    service.update_effect(top.id, effect_id, params={"opacity": 0.5})
    blended, _ = _render(container, tmp_path, "comp-blend.mp4")
    mid = pixel_rgb(blended, at_seconds=0.5, x_fraction=0.5, y_fraction=0.5)
    assert 60 < mid[0] < 220 and mid[2] > 40


@pytest.mark.asyncio()
async def test_effects_via_api(client, tmp_path: Path) -> None:  # noqa: ANN001

    require_ffmpeg()
    await client.post(
        "/api/v1/projects/create",
        json={"name": "API FX", "directory": str(tmp_path / "proj")},
    )
    video = make_video(tmp_path / "v.mp4", duration=2.0)
    imported = await client.post(
        "/api/v1/projects/current/assets/import", json={"path": str(video)}
    )
    asset_id = imported.json()["asset"]["id"]
    added = await client.post(
        "/api/v1/projects/current/clips", json={"asset_id": asset_id}
    )
    clip_id = added.json()["clip"]["id"]

    types = await client.get("/api/v1/effects/types")
    assert types.status_code == 200
    assert "glow" in types.json()["types"]
    assert "fade-in" in types.json()["presets"]

    created = await client.post(
        f"/api/v1/projects/current/clips/{clip_id}/effects",
        json={"type": "bloom", "params": {"strength": 0.6}},
    )
    assert created.status_code == 200, created.text
    effect_id = created.json()["effect"]["id"]

    bad = await client.post(
        f"/api/v1/projects/current/clips/{clip_id}/effects",
        json={"type": "bloom", "params": {"strength": 7.0}},
    )
    assert bad.status_code == 400

    keyframed = await client.put(
        f"/api/v1/projects/current/clips/{clip_id}/effects/{effect_id}/keyframes",
        json={"property": "strength", "keyframes": [
            {"time_seconds": 0.0, "value": 0.1},
            {"time_seconds": 1.5, "value": 0.9},
        ]},
    )
    assert keyframed.status_code == 200, keyframed.text

    undone = await client.post("/api/v1/projects/current/undo")
    effect = undone.json()["timeline"]["clips"][0]["effects"][0]
    assert effect["keyframes"] == {}
