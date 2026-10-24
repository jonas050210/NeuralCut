from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from neuralcut.backend.projects import model as project_model
from neuralcut.backend.projects.model import (
    Project,
    ProjectClip,
    migrate,
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
    assert loaded.version == 1
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


def test_migration_registry_applies_in_order() -> None:
    original = dict(project_model.MIGRATIONS)
    try:
        project_model.MIGRATIONS.clear()

        @register_migration(1, 2)
        def to_v2(project: Project) -> Project:
            project.metadata["migrated"] = True
            return project

        migrated = migrate(Project(id="p1", name="Migrate"), target_version=2)
        assert migrated.version == 2
        assert migrated.metadata["migrated"] is True
    finally:
        project_model.MIGRATIONS.clear()
        project_model.MIGRATIONS.update(original)


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
