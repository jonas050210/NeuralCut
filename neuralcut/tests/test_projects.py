from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from neuralcut.backend.projects import model as project_model
from neuralcut.backend.projects.model import (
    Project,
    ProjectClip,
    migrate_data,
    register_migration,
)
from neuralcut.backend.projects.service import ProjectService
from neuralcut.backend.projects.store import ProjectStore
from neuralcut.errors import ConflictError, ProjectError, ValidationError


def test_project_roundtrip(tmp_path: Path) -> None:
    project = Project(id="proj-1", name="Roundtrip")
    path = tmp_path / "Roundtrip.neuralcut"

    saved = ProjectStore.save(project, path)
    loaded = ProjectStore.load(saved)

    assert loaded.id == "proj-1"
    assert loaded.name == "Roundtrip"
    assert loaded.version == 3
    assert saved.exists()


def test_project_validation_and_clip_range() -> None:
    with pytest.raises(PydanticValidationError):
        Project(id="proj-1", name="   ")

    with pytest.raises(PydanticValidationError):
        ProjectClip(
            id="clip-1",
            asset_id="asset-1",
            start_seconds=5,
            end_seconds=4,
        )


def test_project_store_rejects_invalid_json_and_newer_version(tmp_path: Path) -> None:
    bad = tmp_path / "bad.neuralcut"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValidationError):
        ProjectStore.load(bad)

    future = tmp_path / "future.neuralcut"
    future.write_text(
        json.dumps({"id": "p1", "name": "Future", "version": 999}),
        encoding="utf-8",
    )
    with pytest.raises(ProjectError) as exc:
        ProjectStore.load(future)
    assert "newer than supported" in exc.value.message


def test_v1_project_migrates_to_current_with_sequential_clips(tmp_path: Path) -> None:
    v1 = {
        "version": 1,
        "id": "p1",
        "name": "Old Project",
        "assets": [
            {"id": "a1", "name": "clip.mp4", "path": "/tmp/clip.mp4", "duration_seconds": 10.0}
        ],
        "clips": [
            {"id": "c1", "asset_id": "a1", "track": 0, "start_seconds": 1.0, "end_seconds": 4.0},
            {"id": "c2", "asset_id": "a1", "track": 0, "start_seconds": 5.0, "end_seconds": 9.0},
        ],
    }
    path = tmp_path / "old.neuralcut"
    path.write_text(json.dumps(v1), encoding="utf-8")

    loaded = ProjectStore.load(path)

    assert loaded.version == 3
    assert loaded.clips[0].timeline_start_seconds == 0.0
    assert loaded.clips[0].source_start_seconds == 1.0
    assert loaded.clips[0].duration_seconds == 3.0
    assert loaded.clips[1].timeline_start_seconds == 3.0
    assert loaded.timeline_duration_seconds == 7.0


def test_migration_registry_applies_in_order() -> None:
    original = dict(project_model.RAW_MIGRATIONS)
    try:
        project_model.RAW_MIGRATIONS.clear()

        @register_migration(1, 2)
        def to_v2(data: dict) -> dict:
            data = dict(data)
            data["metadata"] = {"migrated": True}
            data["version"] = 2
            return data

        migrated = migrate_data({"id": "p1", "name": "Migrate", "version": 1}, target_version=2)
        assert migrated["version"] == 2
        assert migrated["metadata"]["migrated"] is True
    finally:
        project_model.RAW_MIGRATIONS.clear()
        project_model.RAW_MIGRATIONS.update(original)


def test_project_service_create_open_save_recent(tmp_path: Path) -> None:
    recent_changes: list[list[str]] = []
    service = ProjectService(on_recent_changed=recent_changes.append)

    created = service.create("Demo Project", tmp_path)
    assert service.get().id == created.id
    assert service.current_path() is not None
    assert service.current_path().exists()
    assert service.recent_projects()[0]["exists"] is True
    assert recent_changes

    path = service.current_path()
    service.close()
    opened = service.open(path)
    assert opened.id == created.id

    opened.metadata["note"] = "saved by test"
    service.save()
    reloaded = ProjectStore.load(path)
    assert reloaded.metadata["note"] == "saved by test"


def test_project_service_rejects_duplicate_and_blank_name(tmp_path: Path) -> None:
    service = ProjectService()
    service.create("Same", tmp_path)

    with pytest.raises(ConflictError):
        service.create("Same", tmp_path)

    with pytest.raises(ValidationError):
        service.create("   ", tmp_path)
