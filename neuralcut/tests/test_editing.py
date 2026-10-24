from __future__ import annotations

from pathlib import Path

import pytest

from neuralcut.backend.di import Container
from neuralcut.backend.editing.service import TimelineService
from neuralcut.backend.integration.media import MediaInfo
from neuralcut.backend.projects.model import ProjectAsset
from neuralcut.backend.projects.store import ProjectStore
from neuralcut.errors import NotFoundError, ValidationError
from neuralcut.tests.media_helpers import make_video, require_ffmpeg


class FakeMedia:
    """Deterministic probe stub for pure timeline-logic tests."""

    def __init__(self, duration: float = 10.0) -> None:
        self.duration = duration

    def probe(self, path) -> MediaInfo:  # noqa: ANN001
        return MediaInfo(
            path=str(path),
            duration_seconds=self.duration,
            width=320,
            height=240,
            fps=10.0,
            has_audio=True,
            has_video=True,
            codec="h264",
        )


@pytest.fixture()
def editing(container: Container, tmp_path: Path) -> TimelineService:
    container.project_service.create("Edit Test", tmp_path / "proj")
    service = TimelineService(container.project_service, FakeMedia())
    container._test_media_file = tmp_path / "source.mp4"  # type: ignore[attr-defined]
    container._test_media_file.write_bytes(b"fake")  # type: ignore[attr-defined]
    return service


def _import(editing: TimelineService, container: Container) -> ProjectAsset:
    return editing.import_media(container._test_media_file)  # type: ignore[attr-defined]


def test_import_add_and_timeline_shape(editing: TimelineService, container: Container) -> None:
    asset = _import(editing, container)
    assert asset.duration_seconds == 10.0
    clip = editing.add_clip(asset.id)
    assert clip.timeline_start_seconds == 0.0
    assert clip.duration_seconds == 10.0
    # Second clip appends after the first on the same track.
    clip2 = editing.add_clip(asset.id, source_start_seconds=0, source_end_seconds=2)
    assert clip2.timeline_start_seconds == 10.0
    timeline = editing.timeline()
    assert timeline["duration_seconds"] == 12.0
    assert [c["id"] for c in timeline["clips"]] == [clip.id, clip2.id]
    # Re-importing the same path is a no-op.
    again = _import(editing, container)
    assert again.id == asset.id
    assert len(editing.timeline()["assets"]) == 1


def test_move_trim_split_remove(editing: TimelineService, container: Container) -> None:
    asset = _import(editing, container)
    clip = editing.add_clip(asset.id, source_start_seconds=0, source_end_seconds=4)

    moved = editing.move_clip(clip.id, timeline_start_seconds=2.0)
    assert moved.timeline_start_seconds == 2.0

    trimmed = editing.trim_clip(clip.id, source_start_seconds=1.0, source_end_seconds=3.0)
    assert trimmed.duration_seconds == 2.0

    first, second = editing.split_clip(clip.id, at_timeline_seconds=3.0)
    assert first.duration_seconds == 1.0
    assert second.duration_seconds == 1.0
    assert second.timeline_start_seconds == 3.0
    assert second.source_start_seconds == 2.0

    editing.remove_clip(second.id)
    assert [c["id"] for c in editing.timeline()["clips"]] == [first.id]


def test_validation_overlap_and_ranges(editing: TimelineService, container: Container) -> None:
    asset = _import(editing, container)
    editing.add_clip(asset.id, source_start_seconds=0, source_end_seconds=4)
    with pytest.raises(ValidationError):
        editing.add_clip(
            asset.id, timeline_start_seconds=2.0, source_start_seconds=0, source_end_seconds=1
        )
    with pytest.raises(ValidationError):
        editing.add_clip(asset.id, source_start_seconds=8, source_end_seconds=99)
    with pytest.raises(ValidationError):
        editing.split_clip(editing.timeline()["clips"][0]["id"], at_timeline_seconds=0.0)
    with pytest.raises(NotFoundError):
        editing.add_clip("missing-asset")
    with pytest.raises(NotFoundError):
        editing.remove_clip("missing-clip")


def test_undo_redo_restores_exact_states(editing: TimelineService, container: Container) -> None:
    asset = _import(editing, container)
    clip = editing.add_clip(asset.id, source_start_seconds=0, source_end_seconds=4)
    state_after_add = editing.timeline()
    editing.move_clip(clip.id, timeline_start_seconds=5.0)
    editing.trim_clip(clip.id, source_end_seconds=2.0)
    assert editing.history_state()["can_undo"] is True

    editing.undo()
    editing.undo()
    restored = editing.timeline()
    assert restored["clips"] == state_after_add["clips"]
    assert editing.history_state()["can_redo"] is True

    editing.redo()
    redone = editing.timeline()["clips"][0]
    assert redone["timeline_start_seconds"] == 5.0

    # A new edit clears redo.
    editing.undo()
    editing.remove_clip(clip.id)
    assert editing.history_state()["can_redo"] is False
    assert editing.timeline()["clips"] == []
    editing.undo()
    assert len(editing.timeline()["clips"]) == 1


def test_missing_media_and_remove_asset_guard(
    editing: TimelineService, container: Container, tmp_path: Path
) -> None:
    asset = _import(editing, container)
    clip = editing.add_clip(asset.id, source_start_seconds=0, source_end_seconds=2)
    with pytest.raises(ValidationError):
        editing.remove_asset(asset.id)
    editing.remove_clip(clip.id)
    editing.remove_asset(asset.id)
    assert editing.timeline()["assets"] == []

    ghost = tmp_path / "ghost.mp4"
    ghost.write_bytes(b"x")
    asset2 = editing.import_media(ghost)
    ghost.unlink()
    with pytest.raises(ValidationError):
        editing.add_clip(asset2.id)


def test_timeline_persistence_roundtrip(
    editing: TimelineService, container: Container
) -> None:
    asset = _import(editing, container)
    clip = editing.add_clip(
        asset.id, source_start_seconds=1, source_end_seconds=4, name="Intro"
    )
    editing.move_clip(clip.id, timeline_start_seconds=2.5)
    path = container.project_service.current_path()
    container.project_service.save()

    loaded = ProjectStore.load(path)
    assert loaded.version == 3
    assert len(loaded.clips) == 1
    saved_clip = loaded.clips[0]
    assert saved_clip.name == "Intro"
    assert saved_clip.timeline_start_seconds == 2.5
    assert saved_clip.source_start_seconds == 1.0
    assert saved_clip.duration_seconds == 3.0
    assert loaded.assets[0].duration_seconds == 10.0


def test_real_media_probe(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    video = make_video(tmp_path / "real.mp4", duration=2.0)
    info = container.media.probe(video)
    assert info.has_video is True
    assert info.has_audio is True
    assert info.width == 320 and info.height == 240
    assert info.duration_seconds is not None and 1.5 < info.duration_seconds < 2.6
    with pytest.raises(ValidationError):
        container.media.probe(tmp_path / "nope.mp4")
    bad = tmp_path / "bad.txt"
    bad.write_text("not media")
    with pytest.raises(ValidationError):
        container.media.probe(bad)
